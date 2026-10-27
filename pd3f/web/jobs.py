"""Jobs as directories: the uploaded PDF, `status.json` and the outputs once done."""

import json
import logging
import os
import shutil
import time
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from pathlib import Path

from .. import ERRORS, extract, output

log = logging.getLogger(__name__)


def write_status(job, **status):
    """Replace `status.json` in one step, so a reader never sees half of it."""
    tmp = job / "status.json.tmp"
    tmp.write_text(json.dumps(status, ensure_ascii=False))
    os.replace(tmp, job / "status.json")


def read_status(job):
    return json.loads((job / "status.json").read_text())


def run(job):
    """Extract the job's PDF, in a worker process."""
    if not (job / "status.json").exists():
        # deleted while it was queued
        return
    status = read_status(job) | {"state": "running", "started": time.time()}
    write_status(job, **status)
    options = status["options"]
    try:
        result = extract(
            job / "input.pdf",
            options["lang"],
            options["scorer"],
            options["headers_footers"],
            options["footnotes_last"],
            options["page_breaks"],
            options["ocr"],
            options["ocr_lang"] or None,
            job / "ocr.pdf",
            partial(progress, job, status),
        )
        (job / "text.txt").write_text(output.text(result))
        (job / "text.md").write_text(output.text(result, markdown=True))
        decisions = output.decisions(result)
        (job / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False))
        tables = output.tables(result)
        for i, table in enumerate(tables, 1):
            (job / "tables").mkdir(exist_ok=True)
            (job / "tables" / f"{i}.csv").write_text(table)
        done = {
            "state": "done",
            "finished": time.time(),
            "pages": result.pages,
            "ocr_pages": result.ocr_pages,
            "tables": len(tables),
            "decisions": len(decisions),
            "uncertain": sum(d["uncertain"] for d in decisions),
        }
        write_status(job, **(status | done))
    except ERRORS as e:
        fail(job, str(e))


def progress(job, status, step, done, total):
    write_status(job, **(status | {"step": step, "done": done, "total": total}))


def fail(job, error):
    status = read_status(job)
    write_status(
        job, **(status | {"state": "failed", "finished": time.time(), "error": error})
    )


def crashed(job, future):
    """Mark the job failed if its worker raised an unexpected error or died."""
    error = future.exception()
    if error is None or not (job / "status.json").exists():
        return
    log.error("job %s crashed", job.name, exc_info=error)
    if isinstance(error, BrokenProcessPool):
        # a dying worker fails the queued jobs too, so this PDF need not be the cause
        fail(
            job,
            "a worker process ended before this PDF was done, for example for lack of memory",
        )
    else:
        fail(job, "pd3f crashed on this PDF")


def interrupt(jobs):
    """Mark the jobs a restart cut off as failed."""
    for job in Path(jobs).iterdir():
        if (job / "status.json").exists():
            status = read_status(job)
            if status["state"] in ("queued", "running"):
                error = "interrupted by a restart of the server, please upload again"
                write_status(job, **(status | {"state": "failed", "error": error}))


def expire(jobs, ttl):
    """Remove the jobs created more than `ttl` seconds ago that no worker is busy with."""
    now = time.time()
    for job in Path(jobs).iterdir():
        if (job / "status.json").exists():
            status = read_status(job)
            created, running = status["created"], status["state"] == "running"
        else:
            # an upload cut off before its status was written
            created, running = job.stat().st_mtime, False
        if not running and now - created > ttl:
            shutil.rmtree(job)
