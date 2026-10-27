import multiprocessing
import os
import signal
import threading
import time
from concurrent.futures import Future

import pytest
from helpers import DATA

from pd3f import output
from pd3f.web import create_app, jobs

LETTER = DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf"
JOB_ID = "A" * 22
OPTIONS = {
    "lang": "de",
    "scorer": "none",
    "headers_footers": "separate",
    "footnotes_last": True,
    "page_breaks": False,
    "ocr": "skip",
    "ocr_lang": "",
}


@pytest.fixture
def root(tmp_path):
    return tmp_path / "jobs"


@pytest.fixture
def client(root):
    return create_app(jobs_dir=root, workers=1).test_client()


def upload(client, pdf=LETTER, **form):
    with open(pdf, "rb") as f:
        return client.post("/jobs", data={"pdf": (f, pdf.name), **form})


def finished(client, job_id, timeout=60):
    """The status of the job once its worker is done with it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").get_json()
        if status["state"] in ("done", "failed"):
            return status
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} still {status['state']}")


def test_index(client):
    page = client.get("/").get_data(as_text=True)
    assert "<option>flair-fast</option>" in page and "1.0.0" in page


def test_a_job_from_upload_to_deletion(client, root):
    response = upload(client, page_breaks="on", footnotes_in_place="on")
    assert response.status_code == 202
    job_id = response.get_json()["id"]
    assert response.get_json()["url"] == f"/jobs/{job_id}"
    status = finished(client, job_id)
    assert status | {"created": 0, "started": 0, "finished": 0} == {
        "state": "done",
        "created": 0,
        "started": 0,
        "finished": 0,
        "filename": LETTER.name,
        "options": {
            "lang": "de",
            "scorer": "none",
            "headers_footers": "separate",
            "footnotes_last": False,
            "page_breaks": True,
            "ocr": "auto",
            "ocr_lang": "",
        },
        "pages": 3,
        "ocr_pages": [],
        "tables": 0,
        "decisions": status["decisions"],
        "uncertain": status["uncertain"],
    }
    assert status["decisions"] > status["uncertain"] > 0
    text = client.get(f"/jobs/{job_id}/text.txt").get_data(as_text=True)
    assert text.count("\f") == 3
    assert (
        len(client.get(f"/jobs/{job_id}/decisions.json").get_json())
        == (status["decisions"])
    )
    markdown = client.get(f"/jobs/{job_id}/text.md?download=1")
    assert markdown.headers["Content-Disposition"] == "attachment; filename=text.md"
    pdf = client.get(f"/jobs/{job_id}/input.pdf")
    assert (pdf.mimetype, pdf.get_data()) == ("application/pdf", LETTER.read_bytes())
    assert pdf.headers["X-Content-Type-Options"] == "nosniff"
    for name in ("status.json", "ocr.pdf", "tables/1.csv", "../x"):
        assert client.get(f"/jobs/{job_id}/{name}").status_code == 404
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert not (root / job_id).exists()


def test_a_failed_job(client, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing")
    status = finished(client, upload(client, broken).get_json()["id"])
    assert status["state"] == "failed"
    assert status["error"].startswith("cannot read")


@pytest.mark.parametrize(
    ("form", "error"),
    [
        ({"lang": "xx"}, "lang must be one of de, en, es, fr, it"),
        ({"scorer": "gpt"}, "scorer must be one of none, flair, flair-fast"),
        ({"headers_footers": "x"}, "headers_footers must be one of"),
        ({"ocr": "always"}, "ocr must be one of auto, force, skip"),
        ({"ocr_lang": "rus;ls"}, "ocr_lang must be Tesseract language codes"),
    ],
)
def test_invalid_options(client, root, form, error):
    response = upload(client, **form)
    assert response.status_code == 400
    assert response.get_json()["error"].startswith(error)
    assert list(root.iterdir()) == []


def test_upload_needs_a_pdf(client):
    response = client.post("/jobs", data={})
    assert (response.status_code, response.get_json()) == (
        400,
        {"error": "upload a PDF as `pdf`"},
    )


def test_uploads_have_a_limit(root, monkeypatch, tmp_path):
    monkeypatch.setenv("PD3F_MAX_MB", "1")
    client = create_app(jobs_dir=root, workers=1).test_client()
    big = tmp_path / "big.pdf"
    big.write_bytes(b"0" * (2 << 20))
    response = upload(client, big)
    assert response.status_code == 413
    assert "error" in response.get_json()


def job(root, job_id=JOB_ID, **status):
    path = root / job_id
    path.mkdir(parents=True)
    jobs.write_status(path, **status)
    return path


def test_unknown_and_running_jobs(client, root):
    assert client.get("/jobs/nope").status_code == 404
    assert client.get(f"/jobs/{'B' * 22}").status_code == 404
    job(root, state="running", created=time.time())
    response = client.delete(f"/jobs/{JOB_ID}")
    assert response.status_code == 409
    assert response.get_json()["error"].startswith("the job is running")


def test_every_error_comes_as_json(client, root, monkeypatch):
    response = client.put("/jobs")
    assert (response.status_code, response.is_json) == (405, True)
    job(root, state="done", created=time.time())

    def broken(job):
        raise RuntimeError("broken")

    monkeypatch.setattr(jobs, "read_status", broken)
    response = client.get(f"/jobs/{JOB_ID}")
    assert (response.status_code, response.is_json) == (500, True)


def test_a_restart_fails_unfinished_jobs(root):
    for i, state in enumerate(("queued", "running", "done")):
        job(root, str(i) * 22, state=state, created=0)
    jobs.interrupt(root)
    states = [jobs.read_status(root / (str(i) * 22))["state"] for i in range(3)]
    assert states == ["failed", "failed", "done"]
    assert jobs.read_status(root / ("0" * 22))["error"].startswith("interrupted")


def test_old_jobs_expire(root):
    now = time.time()
    old_done = job(root, "a" * 22, state="done", created=now - 7200)
    old_running = job(root, "b" * 22, state="running", created=now - 7200)
    new_done = job(root, "c" * 22, state="done", created=now)
    old_upload = root / ("d" * 22)
    old_upload.mkdir()
    os.utime(old_upload, (now - 7200, now - 7200))
    new_upload = root / ("e" * 22)
    new_upload.mkdir()
    jobs.expire(root, 3600)
    assert sorted(p.name[0] for p in root.iterdir()) == ["b", "c", "e"]
    assert not old_done.exists() and old_running.exists() and new_done.exists()


def test_a_crashed_worker_fails_its_job(root, caplog):
    path = job(root, state="running", created=0)
    ok = Future()
    ok.set_result(None)
    jobs.crashed(path, ok)
    assert jobs.read_status(path)["state"] == "running"
    crash = Future()
    crash.set_exception(RuntimeError("boom"))
    jobs.crashed(path, crash)
    status = jobs.read_status(path)
    assert (status["state"], status["error"]) == ("failed", "pd3f crashed on this PDF")
    assert "boom" in caplog.text
    (path / "status.json").unlink()
    jobs.crashed(path, crash)
    assert not (path / "status.json").exists()


def test_one_request_at_a_time_removes_jobs(client, root, monkeypatch):
    job(root, state="done", created=time.time())
    deleted = threading.Event()

    def expire(jobs_dir, ttl):
        def delete():
            if client.delete(f"/jobs/{JOB_ID}").status_code == 204:
                deleted.set()

        threading.Thread(target=delete).start()
        assert not deleted.wait(0.3)

    monkeypatch.setattr(jobs, "expire", expire)
    assert upload(client).status_code == 202
    assert deleted.wait(5)


def test_a_killed_worker_does_not_stop_later_jobs(client):
    before = set(multiprocessing.active_children())
    first = upload(client).get_json()["id"]
    # the worker is still starting, so it dies before it is done with the PDF
    for worker in set(multiprocessing.active_children()) - before:
        os.kill(worker.pid, signal.SIGKILL)
    status = finished(client, first)
    assert (status["state"], status["error"]) == (
        "failed",
        "a worker process ended before this PDF was done, for example for lack of memory",
    )
    second = upload(client)
    assert second.status_code == 202
    assert finished(client, second.get_json()["id"])["state"] == "done"


def test_a_deleted_job_is_not_run(root):
    path = root / JOB_ID
    path.mkdir(parents=True)
    jobs.run(path)
    assert list(path.iterdir()) == []


def test_tables_are_written_and_served(client, root, monkeypatch):
    monkeypatch.setattr(output, "tables", lambda result: ["a,b\r\n"])
    path = job(root, state="queued", created=time.time(), options=OPTIONS)
    (path / "input.pdf").write_bytes(LETTER.read_bytes())
    jobs.run(path)
    assert jobs.read_status(path)["tables"] == 1
    assert client.get(f"/jobs/{JOB_ID}/tables/1.csv").get_data() == b"a,b\r\n"


def test_a_running_job_shows_its_step(root):
    path = job(root, state="running", created=0)
    jobs.progress(path, jobs.read_status(path), "OCR", 2, 5)
    jobs.progress(path, jobs.read_status(path), "Layout", None, None)
    status = jobs.read_status(path)
    assert (status["step"], status["done"], status["total"]) == ("Layout", None, None)


def test_a_job_failing_in_place(root):
    path = job(root, state="queued", created=0, options=OPTIONS)
    (path / "input.pdf").write_bytes(b"%PDF-1.4 nothing")
    jobs.run(path)
    status = jobs.read_status(path)
    assert (status["state"], status["error"][:11]) == ("failed", "cannot read")


def test_a_relative_jobs_directory_serves_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = create_app(jobs_dir="jobs", workers=1).test_client()
    job(tmp_path / "jobs", state="done", created=time.time())
    (tmp_path / "jobs" / JOB_ID / "text.txt").write_text("Text")
    assert client.get(f"/jobs/{JOB_ID}/text.txt").data == b"Text"
