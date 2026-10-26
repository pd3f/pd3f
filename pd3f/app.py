import json
import logging
import os
import shutil
import time
from datetime import timedelta
from pathlib import Path
from zipfile import ZipFile

import redis
import shortuuid
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from rq import Queue, get_current_job
from werkzeug.utils import secure_filename

from pd3f import extract

logger = logging.getLogger(__name__)

UPLOADS = Path("/uploads")
TO_OCR = Path("/to-ocr")

# -1 disables the timeout
JOB_TIMEOUT = int(os.environ.get("JOB_TIMEOUT", "-1"))

if "SENTRY_URL" in os.environ:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration

    sentry_sdk.init(dsn=os.environ["SENTRY_URL"], integrations=[FlaskIntegration()])


app = Flask(__name__)

q = Queue(connection=redis.from_url(os.environ["RQ_REDIS_URL"]))


def allow_pdf(filename):
    return filename.lower().endswith(".pdf")


def form_flag(name, default):
    """Read a boolean form field: 1/true/on/yes or 0/false/off/no."""
    value = request.form.get(name)
    if value is None:
        return default
    if value.lower() in ("1", "true", "on", "yes"):
        return True
    if value.lower() in ("", "0", "false", "off", "no"):
        return False
    abort(400, f"invalid value for {name}: {value}")


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
    if lang not in ("de", "es", "en", "fr", "it"):
        abort(400)

    experimental = form_flag("experimental", False)
    tables = form_flag("tables", False)
    fast_mode = form_flag("fast", False)
    check_ocr = form_flag("check_ocr", True)  # not in UI / expert mode
    in_browser = form_flag("in_browser", False)
    parsr_config = request.form.get("parsr_config")  # not in UI / expert mode
    parsr_adjust_cleaner_config = request.form.get(
        "parsr_adjust_cleaner_config"
    )  # not in UI / expert mode

    if parsr_config is not None:
        parsr_config = json.loads(parsr_config)
    if parsr_adjust_cleaner_config is not None:
        parsr_adjust_cleaner_config = json.loads(parsr_adjust_cleaner_config)

    flair_lang, tess_lang = params_to_lang_model(lang, fast_mode)

    if not check_ocr:
        tess_lang = None

    job_id = shortuuid.ShortUUID().random(length=22)
    filename = job_id + secure_filename(file.filename)[:200]

    file.save(UPLOADS / filename)
    # before enqueueing, so a fast worker's first lines don't get truncated
    (UPLOADS / f"{job_id}.log").write_text("")

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

    # simpler than checking for accept header
    if in_browser:
        return redirect(url_for("result", job_id=job_id))
    return {"id": job_id}


def persists_results(filename, text, tables):
    (UPLOADS / f"{filename}.txt").write_text(text)

    with ZipFile(UPLOADS / f"{filename}_tables.zip", "w") as zip_file:
        for i, t in enumerate(tables or []):
            csv_path = UPLOADS / f"{filename}_table_{i}.csv"
            csv_path.write_text(t)
            zip_file.write(csv_path, arcname=csv_path.name)


@app.route("/update/<job_id>", methods=["GET"])
def get_log(job_id):
    j = q.fetch_job(job_id)

    if j is None:
        abort(400)

    log = (UPLOADS / f"{job_id}.log").read_text()

    if j.is_finished:
        text, tables = j.return_value()
        persists_results(j.kwargs["filename"], text, tables)

        return {
            "log": log,
            "text": text,
            "tables": tables,
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
    return send_from_directory(UPLOADS, filename, as_attachment=True)


@app.route("/result/<job_id>/", methods=["GET"])
def result(job_id):
    j = q.fetch_job(job_id)
    if j is None:
        abort(400)

    poll_interval = os.environ.get("POLL_INTERVAL", "500")

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
    logger.info("setting up ocr")
    fn_p = UPLOADS / filename
    # pd3f-ocr only picks up lowercase .pdf files
    new_p = TO_OCR / f"{fn_p.stem}.{lang}.pdf"
    finished_p_success = new_p.with_suffix(".pdf.done")
    finished_p_error = new_p.with_suffix(".pdf.failed")
    finished_p_log = new_p.with_suffix(".pdf.log")
    new_p.parent.mkdir(exist_ok=True)
    # copy under another name first, pd3f-ocr would pick up a half-written .pdf
    part_p = new_p.with_name(f"{new_p.name}.part")
    shutil.copy2(fn_p, part_p)
    part_p.replace(new_p)

    while True:
        # file gets deleted when processing is finished
        if not new_p.is_file():
            if finished_p_success.is_file():
                # success
                shutil.copy2(finished_p_success, fn_p)
                logger.info("ocr finished successfully")
                return True
            if finished_p_error.is_file():
                finished_p_error.unlink()
                logger.info(finished_p_log.read_text())
                logger.info("ocr failed, aborting. sorry :/")
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

    # the worker logs the exception of a failed job here, too; `force` replaces
    # the handler of the previous job if the worker does not fork
    logging.basicConfig(
        filename=UPLOADS / f"{job_id}.log", level=logging.INFO, force=True
    )

    if tess_lang is not None and not do_ocr_via_folder(filename, tess_lang):
        clear_in_future(job_id)
        raise ValueError("could not OCR pdf")

    # not using `fast` mode because it has to be validated more
    text, tables = extract(
        UPLOADS / filename,
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
    for f in UPLOADS.glob(job_id + "*"):
        f.unlink()

    for f in TO_OCR.glob(job_id + "*"):
        f.unlink()


def clear_in_future(job_id):
    """
    Delete successfull tasks in some time, e.g., 24 hours.
    """
    q.enqueue_in(
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
