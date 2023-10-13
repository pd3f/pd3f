import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from zipfile import ZipFile

import flair
import redis
import shortuuid
from flask import Flask, abort, redirect, render_template, request, send_from_directory, url_for
from rq import Queue, get_current_job
from rq_scheduler import Scheduler
from werkzeug.utils import secure_filename

from pd3f import extract

flair.cache_root = "/root/.cache/flair"

REDIS_HOSTNAME = os.environ.get("REDIS_HOSTNAME")
if REDIS_HOSTNAME is None:
    REDIS_HOSTNAME = "redis"
else:
    REDIS_HOSTNAME = str(REDIS_HOSTNAME)
    
JOB_TIMEOUT = os.environ.get("JOB_TIMEOUT")
if JOB_TIMEOUT is None:
    # to disable timeout: set to -1
    JOB_TIMEOUT = -1
else:
    JOB_TIMEOUT = int(JOB_TIMEOUT)

if "SENTRY_URL" in os.environ:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(dsn=os.environ["SENTRY_URL"], integrations=[FlaskIntegration()])


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "/uploads"

r = redis.from_url(f"redis://{REDIS_HOSTNAME}:6379")
q = Queue(connection=r)
scheduler = Scheduler(connection=r)


def allow_pdf(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in "pdf"


# Views


@app.route("/", methods=["GET"])
def index_get():
    demo = "DEMO" in os.environ and os.environ["DEMO"] == "1"
    priv_urls = None
    if "PRIVACY_URLS" in os.environ:
        priv_urls = os.environ["PRIVACY_URLS"].split()

    max_upload = None
    if "MAX_UPLOAD_DISPLAY" in os.environ:
        max_upload = os.environ["MAX_UPLOAD_DISPLAY"]
    return render_template(
        "index.html",
        demo=demo,
        max_upload=max_upload,
        num_jobs=q.count,
        priv_urls=priv_urls,
    )


@app.route("/", methods=["POST"])
def index_post():
    # check if the post request has the file part
    if "pdf" not in request.files:
        abort(400)

    file = request.files["pdf"]

    # if user does not select file, browser also
    # submit an empty part without filename
    if file.filename == "":
        abort(400)

    if not (file and allow_pdf(file.filename)):
        abort(400)

    lang = request.form.get("lang")

    # limit to some languages for now
    if not lang in ("de", "es", "en", "fr", "it"):
        abort(400)

    experimental = bool(request.form.get("experimental", False))
    tables = bool(request.form.get("tables", False))
    fast_mode = bool(request.form.get("fast", False))
    check_ocr = bool(request.form.get("check_ocr", True))  # not in UI / expert mode
    in_browser = bool(request.form.get("in_browser", False))
    parsr_config = request.form.get("parsr_config", None) # not in UI / expert mode
    parsr_adjust_cleaner_config = request.form.get("parsr_adjust_cleaner_config", None) # not in UI / expert mode

    if parsr_config is not None:
        parsr_config = json.loads(parsr_config)
    if parsr_adjust_cleaner_config is not None:
        parsr_adjust_cleaner_config = json.loads(parsr_adjust_cleaner_config)

    flair_lang, tess_lang = params_to_lang_model(lang, fast_mode)

    if not check_ocr:
        tess_lang = None

    job_id = shortuuid.ShortUUID().random(length=22)
    filename = job_id + secure_filename(file.filename)[:200]

    fn = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(fn)

    q.enqueue(
        do_the_job,
        filename=filename,
        lang=lang,
        flair_lang=flair_lang,
        tess_lang=tess_lang,
        tables=tables,
        experimental=experimental,
        job_timeout=JOB_TIMEOUT,
        job_id=job_id,
        fast_mode=fast_mode,
        parsr_config=parsr_config,
        parsr_adjust_cleaner_config=parsr_adjust_cleaner_config,
    )

    Path(app.config["UPLOAD_FOLDER"] + "/" + job_id + ".log").write_text("")

    # simpler than checking for accept header
    if in_browser:
        return redirect(url_for("result", job_id=job_id))
    return {"id": job_id}


def persists_results(filename, text, tables):
    Path(app.config["UPLOAD_FOLDER"] + "/" + filename + ".txt").write_text(text)

    with ZipFile(
        app.config["UPLOAD_FOLDER"] + "/" + filename + "_tables.zip", "w"
    ) as zipObj2:
        if tables is not None:
            for i, t in enumerate(tables):

                Path(
                    app.config["UPLOAD_FOLDER"] + "/" + filename + f"_table_{i}.csv"
                ).write_text(t)

                zipObj2.write(
                    app.config["UPLOAD_FOLDER"] + "/" + filename + f"_table_{i}.csv"
                )


@app.route("/update/<job_id>", methods=["GET"])
def get_log(job_id):
    j = q.fetch_job(job_id)

    if j is None:
        abort(400)

    log = Path(app.config["UPLOAD_FOLDER"] + "/" + job_id + ".log").read_text()

    if j.is_finished:
        persists_results(j.kwargs["filename"], *j.result)

        return {
            "log": log,
            "text": j.result[0],
            "tables": j.result[1],
            "filename": j.kwargs["filename"],
        }
    elif j.is_failed:
        return {"log": log, "failed": True}
    else:
        pos = j.get_position()

        if pos is None:
            return {"log": log, "running": True}

        return {"log": log, "position": pos}


@app.route("/files/<filename>", methods=["GET"])
def dl_file(filename):
    """
    If you use nginx, override this endoint: https://pd3f.com/docs/pd3f/prod/
    """
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], filename, as_attachment=True
    )


@app.route("/result/<job_id>/", methods=["GET"])
def result(job_id):
    j = q.fetch_job(job_id)
    if j is None:
        abort(400)

    poll_interval = (
        os.environ["POLL_INTERVAL"] if "POLL_INTERVAL" in os.environ else 500
    )

    return render_template(
        "result.html", job_id=job_id, **j.kwargs, poll_interval=poll_interval
    )


# worker tasks


def params_to_lang_model(lang, fast_mode):
    """
    Maps params to model names for Flair and tesseract.
    https://github.com/flairNLP/flair/blob/master/resources/docs/embeddings/FLAIR_EMBEDDINGS.md
    multi-v0-fast: English, German, French, Italian, Dutch, Polish
    """
    flair_lang = lang
    if fast_mode:
        if lang in ("de", "fr", "it"):
            # no fast for model for de / fr / it
            flair_lang = "multi-v0-fast"
        else:
            # for en and es fast exits
            flair_lang += "-fast"

    tesseract_lang = None

    if lang == "de":
        tesseract_lang = "deu"
    elif lang == "en":
        tesseract_lang = "eng"
    elif lang == "es":
        tesseract_lang = "spa"
    elif lang == "fr":
        tesseract_lang = "fra"
    elif lang == "it":
        tesseract_lang = "ita"

    return flair_lang, tesseract_lang


def do_ocr_via_folder(filename, lang):
    """
    This is blocking the worker, but who cares. The OCR will take all CPUs anyhow.
    """
    logging.info("setting up ocr")
    fn_p = Path("/uploads/" + filename)
    new_p = Path("/to-ocr/" + fn_p.stem + f".{lang}" + fn_p.suffix)
    finished_p_success = new_p.with_suffix(".pdf.done")
    finished_p_error = new_p.with_suffix(".pdf.failed")
    finished_p_log = new_p.with_suffix(".pdf.log")
    new_p.parent.mkdir(exist_ok=True)
    shutil.copy2(fn_p, new_p)

    while True:
        # file gets deleted when processing is finished
        if not new_p.is_file():
            if finished_p_success.is_file():
                # success
                shutil.copy2(finished_p_success, fn_p)
                logging.info("ocr finished successfully")
                return True
            if finished_p_error.is_file():
                finished_p_error.unlink()
                logging.info(finished_p_log.read_text())
                logging.info("ocr failed, aborting. sorry :/")
                return False

        time.sleep(1)


def do_the_job(
    filename,
    tables,
    experimental,
    flair_lang,
    tess_lang,
    parsr_config,
    parsr_adjust_cleaner_config,
    **kwargs,
):
    """
    kwargs to persist input config
    """
    job = get_current_job()
    job_id = job.id

    logging.basicConfig(filename=f"/uploads/{job_id}.log", level=logging.INFO)

    if tess_lang is not None:
        if not do_ocr_via_folder(filename, tess_lang):
            clear_in_future(job_id)
            raise ValueError("could not OCR pdf")

    # not using `fast` mode because it has to be validated more
    text, tables = extract(
        "/uploads/" + filename,
        tables=tables,
        experimental=experimental,
        force_gpu=False,
        lang=flair_lang,
        parsr_location="parsr:3001",
        parsr_config=parsr_config or {},
        parsr_adjust_cleaner_config=parsr_adjust_cleaner_config or [],
    )

    clear_in_future(job_id)

    return text, tables


def delete_all_files_for_job(job_id):
    for f in Path("/uploads/").glob(job_id + "*"):
        f.unlink()

    for f in Path("/to-ocr/").glob(job_id + "*"):
        f.unlink()


def clear_in_future(job_id):
    """
    Delete successfull tasks in some time, e.g., 24 hours.
    """
    scheduler.enqueue_in(
        timedelta(hours=int(os.environ["KEEP_RESULTS_HOURS"])),
        delete_all_files_for_job,
        job_id,
    )


@app.cli.command()
def retry_failed():
    registry = q.failed_job_registry

    # This is how to get jobs from FailedJobRegistry
    for job_id in registry.get_job_ids():
        registry.requeue(job_id)  # Puts job back in its original queue

    assert len(registry) == 0  # Registry will be empty when job is requeued


@app.cli.command()
def delete_failed():
    registry = q.failed_job_registry

    for job_id in registry.get_job_ids():
        # delete all files
        delete_all_files_for_job(job_id)
        # delete job
        registry.remove(job_id)

    assert len(registry) == 0  # Registry will be empty when all are deleted
