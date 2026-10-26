import io
import threading
import time
import zipfile

import fakeredis
import pytest
from rq import Queue, SimpleWorker
from rq.registry import ScheduledJobRegistry
from rq.results import Result


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("RQ_REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("KEEP_RESULTS_HOURS", "24")
    import app

    (tmp_path / "uploads").mkdir()
    monkeypatch.setattr(app, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(app, "TO_OCR", tmp_path / "to-ocr")
    monkeypatch.setattr(
        app, "q", Queue(connection=fakeredis.FakeRedis(), is_async=False)
    )
    monkeypatch.setattr(app, "extract", lambda *a, **kw: ("the text", ["a,b\n"]))
    return app


def post(app, **form):
    pdf = (io.BytesIO(b"%PDF-1.4"), "Some File.PDF")
    data = {"pdf": pdf, "lang": "de", **form}
    return app.app.test_client().post("/", data=data)


def test_allow_pdf(app):
    assert app.allow_pdf("a.PDF")
    assert not app.allow_pdf("a.p")
    assert not app.allow_pdf("pdf")


def test_params_to_lang_model(app):
    assert app.params_to_lang_model("de", False) == ("de", "deu")
    assert app.params_to_lang_model("de", True) == ("multi-v0-fast", "deu")
    assert app.params_to_lang_model("en", True) == ("en-fast", "eng")


@pytest.mark.parametrize(
    "form",
    [
        {"lang": "ru"},
        {"fast": "maybe"},
        {"pdf": (io.BytesIO(b"text"), "a.txt")},
        {"parsr_config": "{"},
    ],
)
def test_reject_invalid_input(app, form):
    assert post(app, **form).status_code == 400


def test_job_lifecycle(app):
    response = post(app, fast="false", tables="1", check_ocr="0")
    job_id = response.json["id"]
    job = app.q.fetch_job(job_id)

    assert job.kwargs["fast_mode"] is False
    assert job.kwargs["tables"] is True
    assert job.kwargs["tess_lang"] is None
    assert job.kwargs["filename"] == f"{job_id}Some_File.PDF"
    # job and result never expire, `delete_job_and_files` removes them
    assert app.q.connection.ttl(job.key) == -1
    assert app.q.connection.ttl(Result.get_key(job_id)) == -1

    # the worker writes the files, before any client asks for the result
    filename = job.kwargs["filename"]
    assert (app.UPLOADS / f"{filename}.txt").read_text() == "the text"
    with zipfile.ZipFile(app.UPLOADS / f"{filename}_tables.zip") as z:
        assert z.namelist() == [f"{filename}_table_0.csv"]

    update = app.app.test_client().get(f"/update/{job_id}").json
    assert update["text"] == "the text"
    assert update["tables"] == ["a,b\n"]

    run_scheduled_deletion(app, job_id)


def run_scheduled_deletion(app, job_id):
    """Run the deletion scheduled for `job_id`, check that job and files are gone."""
    registry = ScheduledJobRegistry(queue=app.q)
    deletion = app.q.fetch_job(registry.get_job_ids()[0])
    assert deletion.func_name == "app.delete_job_and_files"
    assert deletion.args == (job_id,)
    deletion.func(*deletion.args)

    assert app.app.test_client().get(f"/update/{job_id}").status_code == 400
    assert not app.q.connection.exists(Result.get_key(job_id))
    assert list(app.UPLOADS.iterdir()) == []


def failed_job(app, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("Parsr failed")

    monkeypatch.setattr(app, "extract", fail)
    monkeypatch.setattr(app, "q", Queue(connection=app.q.connection))
    job_id = post(app, check_ocr="0").json["id"]
    SimpleWorker([app.q], connection=app.q.connection).work(burst=True)
    return job_id


def test_failed_job(app, monkeypatch):
    job_id = failed_job(app, monkeypatch)
    update = app.app.test_client().get(f"/update/{job_id}").json
    assert update["failed"] is True
    assert "ValueError: Parsr failed" in update["log"]

    run_scheduled_deletion(app, job_id)


def test_failed_ocr(app, monkeypatch):
    monkeypatch.setattr(app, "q", Queue(connection=app.q.connection))
    ocr_worker = fake_ocr_worker(app, "failed")
    job_id = post(app).json["id"]
    SimpleWorker([app.q], connection=app.q.connection).work(burst=True)
    ocr_worker.join()

    update = app.app.test_client().get(f"/update/{job_id}").json
    assert update["failed"] is True
    assert "tesseract crashed" in update["log"]

    run_scheduled_deletion(app, job_id)
    assert list(app.TO_OCR.iterdir()) == []


def test_queued_job(app, monkeypatch):
    monkeypatch.setattr(app, "q", Queue(connection=app.q.connection))
    job_id = post(app, check_ocr="0").json["id"]
    update = app.app.test_client().get(f"/update/{job_id}").json
    assert update == {"log": "", "position": 0}


def test_delete_failed(app, monkeypatch):
    job_id = failed_job(app, monkeypatch)
    result = app.app.test_cli_runner().invoke(args=["delete-failed"])

    assert result.exit_code == 0, result.output
    assert app.q.fetch_job(job_id) is None
    assert list(app.UPLOADS.iterdir()) == []


def test_retry_failed(app, monkeypatch):
    job_id = failed_job(app, monkeypatch)
    result = app.app.test_cli_runner().invoke(args=["retry-failed"])

    assert result.exit_code == 0, result.output
    assert app.q.fetch_job(job_id).is_queued


def test_redirect_in_browser(app):
    response = post(app, in_browser="1", check_ocr="0")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/result/")


def test_unknown_job(app):
    assert app.app.test_client().get("/update/unknown").status_code == 400


def fake_ocr_worker(app, outcome):
    """Act like pd3f-ocr: wait for the PDF, write the result, remove the input."""

    def run():
        while not (pdfs := list(app.TO_OCR.glob("*.pdf"))):
            time.sleep(0.01)
        pdf = pdfs[0]
        if outcome == "done":
            pdf.with_suffix(".pdf.done").write_text("ocrd")
        else:
            pdf.with_suffix(".pdf.log").write_text("tesseract crashed")
            pdf.rename(pdf.with_suffix(".pdf.failed"))
        pdf.unlink(missing_ok=True)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


@pytest.mark.parametrize("filename", ["job1doc.pdf", "job1doc.PDF"])
@pytest.mark.parametrize("outcome", ["done", "failed"])
def test_ocr_via_folder(app, outcome, filename):
    (app.UPLOADS / filename).write_text("scan")
    worker = fake_ocr_worker(app, outcome)

    assert app.do_ocr_via_folder(filename, "deu") is (outcome == "done")
    worker.join()

    expected = "ocrd" if outcome == "done" else "scan"
    assert (app.UPLOADS / filename).read_text() == expected
    assert not (app.TO_OCR / "job1doc.deu.pdf.failed").exists()


def test_ocr_input_never_half_written(app, monkeypatch):
    (app.UPLOADS / "job1doc.pdf").write_text("scan")
    copy2 = app.shutil.copy2
    visible_after_copy = []

    def copy_and_look(src, dst):
        copy2(src, dst)
        visible_after_copy.extend(app.TO_OCR.glob("*.pdf"))

    monkeypatch.setattr(app.shutil, "copy2", copy_and_look)
    worker = fake_ocr_worker(app, "done")
    assert app.do_ocr_via_folder("job1doc.pdf", "deu")
    worker.join()
    # pd3f-ocr globs for *.pdf, so the copy must only appear under that name complete
    assert visible_after_copy == []


def test_parsr_config_passed_to_extract(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        app, "extract", lambda *a, **kw: calls.append(kw) or ("text", None)
    )
    post(
        app,
        check_ocr="0",
        parsr_adjust_cleaner_config='[["reading-order-detection", {"a": 1}]]',
    )
    assert calls[0]["parsr_adjust_cleaner_config"] == [
        ["reading-order-detection", {"a": 1}]
    ]
    assert calls[0]["parsr_config"] == {}


def test_delete_job_and_files(app):
    app.TO_OCR.mkdir()
    for path in (app.UPLOADS / "job1a.pdf", app.UPLOADS / "job2.pdf"):
        path.write_text("")
    (app.TO_OCR / "job1a.deu.pdf.log").write_text("")

    app.delete_job_and_files("job1")

    assert [p.name for p in app.UPLOADS.iterdir()] == ["job2.pdf"]
    assert list(app.TO_OCR.iterdir()) == []


def test_pages(app):
    client = app.app.test_client()
    assert b'name="lang"' in client.get("/").data

    job_id = post(app, check_ocr="0").json["id"]
    assert job_id.encode() in client.get(f"/result/{job_id}/").data
