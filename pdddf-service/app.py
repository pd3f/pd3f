import os
from pathlib import Path
from zipfile import ZipFile

import redis
from flask import (
    Flask,
    abort,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from rq import Queue
from werkzeug.utils import secure_filename

from text import do_the_job

app = Flask(__name__)

app.config["UPLOAD_FOLDER"] = "/uploads"


r = redis.from_url("redis://redis:6379")
q = Queue(connection=r)


def allow_pdf(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in "pdf"


@app.route("/", methods=["GET"])
def index_get():
    return render_template("index.html")


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
    experimental = bool(request.form.get("experimental", False))
    tables = bool(request.form.get("tables", False))

    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

    job = q.enqueue(
        do_the_job,
        filename=filename,
        lang=lang,
        tables=tables,
        experimental=experimental,
        job_timeout=-1,
    )

    Path(app.config["UPLOAD_FOLDER"] + "/" + job.id + ".log").write_text("")

    return redirect(url_for("result", job_id=job.id))


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
        persists_results(job_id + j.kwargs["filename"], *j.result)
        return {"log": log, "text": j.result[0], "tables": j.result[1]}
    else:
        pos = j.get_position()

        if pos is None:
            pos = -1

        return {"position": pos, "log": log}


@app.route("/files/<filename>", methods=["GET"])
def dl_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/result/<job_id>/", methods=["GET"])
def result(job_id):
    j = q.fetch_job(job_id)
    if j is None:
        abort(400)
    return render_template("result.html", job_id=job_id, **j.kwargs)
