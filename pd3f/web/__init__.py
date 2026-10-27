"""The web app: upload a PDF, follow its job, read and download the results.

Settings come from the environment: `PD3F_JOBS` (directory of the jobs), `PD3F_WORKERS`
(parallel extractions, default 2), `PD3F_JOB_TTL` (hours a job is kept, default 24) and
`PD3F_MAX_MB` (largest upload, default 100).
"""

import multiprocessing
import os
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .. import HEADERS_FOOTERS, OCR_MODES, SCORERS, __version__
from . import jobs

LANGS = ("de", "en", "es", "fr", "it")
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{22}$")
FILE = re.compile(
    r"^(input\.pdf|text\.txt|text\.md|decisions\.json|ocr\.pdf|tables/\d+\.csv)$"
)
TESSERACT_LANG = re.compile(r"^[a-z_]{3,}(\+[a-z_]{3,})*$")


def create_app(jobs_dir=None, workers=None):
    app = Flask(__name__)
    # absolute: Flask serves files from relative directories under the package, not the cwd
    root = Path(jobs_dir or os.environ.get("PD3F_JOBS", "jobs")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ttl = float(os.environ.get("PD3F_JOB_TTL", "24")) * 3600
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("PD3F_MAX_MB", "100")) << 20
    jobs.interrupt(root)
    new_pool = partial(
        ProcessPoolExecutor,
        workers or int(os.environ.get("PD3F_WORKERS", "2")),
        mp_context=multiprocessing.get_context("spawn"),
    )
    pool = new_pool()
    replacing = threading.Lock()
    # one request at a time removes jobs, so none trips over a job another one removes
    removing = threading.Lock()

    def submit(job):
        nonlocal pool
        with replacing:
            try:
                future = pool.submit(jobs.run, job)
            except BrokenProcessPool:
                # a worker that died, killed for lack of memory say, takes its pool with it
                pool = new_pool()
                future = pool.submit(jobs.run, job)
        future.add_done_callback(partial(jobs.crashed, job))

    def job_dir(job_id):
        if not JOB_ID.match(job_id) or not (root / job_id / "status.json").exists():
            abort(404)
        return root / job_id

    def choice(name, choices, default):
        value = request.form.get(name, default)
        if value not in choices:
            abort(400, f"{name} must be one of {', '.join(choices)}")
        return value

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            version=__version__,
            langs=LANGS,
            scorers=SCORERS,
            ocr_modes=OCR_MODES,
            headers_footers=HEADERS_FOOTERS,
        )

    @app.post("/jobs")
    def create():
        with removing:
            jobs.expire(root, ttl)
        pdf = request.files.get("pdf")
        if pdf is None or not pdf.filename:
            abort(400, "upload a PDF as `pdf`")
        ocr_lang = request.form.get("ocr_lang", "").strip()
        if ocr_lang and not TESSERACT_LANG.match(ocr_lang):
            abort(
                400, "ocr_lang must be Tesseract language codes such as rus or deu+eng"
            )
        options = {
            "lang": choice("lang", LANGS, "de"),
            "scorer": choice("scorer", SCORERS, "none"),
            "headers_footers": choice("headers_footers", HEADERS_FOOTERS, "separate"),
            "footnotes_last": request.form.get("footnotes_in_place") is None,
            "page_breaks": request.form.get("page_breaks") is not None,
            "ocr": choice("ocr", OCR_MODES, "auto"),
            "ocr_lang": ocr_lang,
        }
        job_id = secrets.token_urlsafe(16)
        job = root / job_id
        job.mkdir()
        pdf.save(job / "input.pdf")
        jobs.write_status(
            job,
            state="queued",
            created=time.time(),
            filename=pdf.filename,
            options=options,
        )
        submit(job)
        return jsonify(id=job_id, url=f"/jobs/{job_id}"), 202

    @app.get("/jobs/<job_id>")
    def status(job_id):
        return jsonify(jobs.read_status(job_dir(job_id)))

    @app.get("/jobs/<job_id>/<path:name>")
    def download(job_id, name):
        job = job_dir(job_id)
        if not FILE.match(name):
            abort(404)
        return send_from_directory(
            job, name, as_attachment=request.args.get("download") == "1"
        )

    @app.delete("/jobs/<job_id>")
    def delete(job_id):
        with removing:
            job = job_dir(job_id)
            if jobs.read_status(job)["state"] == "running":
                abort(409, "the job is running, delete it when it is done")
            shutil.rmtree(job)
        return "", 204

    @app.after_request
    def no_sniffing(response):
        # an uploaded file is shown as what its name says, never as a page
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(HTTPException)
    def error(e):
        return jsonify(error=e.description), e.code

    return app
