import json
import re
import threading
import time

import pytest
from axe_playwright_python.sync_playwright import Axe
from helpers import DATA
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from pd3f.web import create_app, jobs

LETTER = DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf"
OTHER = DATA / "00020_08112014_Stellungnahme_RAK_Koeln_RefE_Bekaempfung_Korruption.pdf"


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("jobs")


@pytest.fixture(scope="module")
def url(root):
    app = create_app(jobs_dir=root, workers=1)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def violations(page):
    results = Axe().run(page)
    return results.generate_report() if results.violations_count else ""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_upload_and_result_pass_axe(browser, url, scheme):
    context = browser.new_context(
        color_scheme=scheme,
        locale="fr-FR",
        permissions=["clipboard-read", "clipboard-write"],
    )
    page = context.new_page()
    page.goto(url)
    expect(page.get_by_label("Language", exact=True)).to_have_value("fr")
    page.get_by_text("Advanced").click()
    assert violations(page) == ""

    page.get_by_label("Language", exact=True).select_option("de")
    page.set_input_files("#pdf", [LETTER, OTHER])
    page.get_by_role("button", name="Extract text").click()
    expect(page.locator("#result")).to_be_visible(timeout=60_000)
    expect(page.locator("#result-title")).to_be_focused()
    expect(page.get_by_role("status")).to_have_text(f"{LETTER.name}: done.")
    expect(page.locator("#jobs li")).to_have_count(2)
    expect(page.locator("#pdf-view")).to_have_attribute(
        "src", re.compile(r"^/jobs/[\w-]{22}/input\.pdf$")
    )
    marks = page.locator("#text mark")
    assert marks.count() > 0
    # every uncertain decision is in a mark, overlapping ones in a shared one
    summary = page.locator("#summary").text_content()
    count = int(re.search(r"(\d+) of them uncertain", summary)[1])
    shown = [m.get_attribute("data-options").count("chosen: ") for m in marks.all()]
    assert sum(shown) == count
    marks.first.focus()
    assert "chosen: " in marks.first.get_attribute("data-options")
    assert violations(page) == ""

    page.get_by_label("Mark uncertain decisions").uncheck()
    expect(marks).to_have_count(0)
    page.get_by_label("Mark uncertain decisions").check()
    assert marks.count() > 0
    page.get_by_role("button", name="Copy text").click()
    expect(page.get_by_role("status")).to_have_text("The text is copied.")
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied == LETTER.with_suffix(".txt").read_text()

    page.get_by_role("button", name="Delete this job").click()
    expect(page.get_by_role("status")).to_have_text("The job is deleted.")
    expect(page.locator("#jobs li")).to_have_count(1)
    assert violations(page) == ""
    context.close()


DROP = """names => {
    const files = new DataTransfer();
    for (const name of names) files.items.add(new File(["%PDF-1.4"], name));
    return files;
}"""


def test_dropped_pdfs_are_chosen(browser, url):
    page = browser.new_page()
    page.goto(url)
    files = page.evaluate_handle(DROP, ["a.pdf", "notes.txt", "B.PDF"])
    page.dispatch_event("#upload", "drop", {"dataTransfer": files})
    expect(page.get_by_role("status")).to_have_text("2 PDFs chosen.")
    chosen = page.eval_on_selector("#pdf", "input => [...input.files].map(f => f.name)")
    assert chosen == ["a.pdf", "B.PDF"]
    files = page.evaluate_handle(DROP, ["notes.txt"])
    page.dispatch_event("#upload", "drop", {"dataTransfer": files})
    expect(page.get_by_role("status")).to_have_text(
        "None of the dropped files is a PDF."
    )
    page.close()


def test_a_running_job_shows_its_step(browser, url):
    page = browser.new_page()
    job = re.compile(r"/jobs/A{22}$")
    status = {"state": "running", "filename": "a.pdf", "step": "OCR", "done": 2}
    page.route(job, lambda route: route.fulfill(json=status | {"total": 5}))
    page.goto(f"{url}#{'A' * 22}")
    expect(page.get_by_role("status")).to_have_text("a.pdf: OCR, page 2 of 5…")
    status.update(step="Layout", done=None)
    page.unroute(job)
    page.route(job, lambda route: route.fulfill(json=status | {"total": None}))
    expect(page.get_by_role("status")).to_have_text("a.pdf: Layout…")
    page.unroute(job)
    expect(page.get_by_role("status")).to_have_text(
        "This job does not exist (any more)."
    )
    page.close()


def answer(**kwargs):
    return lambda route: route.fulfill(**kwargs)


def test_a_job_chosen_later_stays_shown(browser, url):
    page = browser.new_page()
    for name in ("A", "B"):
        status = {"state": "done", "filename": f"{name}.pdf", "pages": 1}
        status |= {"ocr_pages": [], "tables": 0, "decisions": 0}
        job = name * 22
        page.route(re.compile(f"/jobs/{job}$"), answer(json=status))
        page.route(re.compile(f"/jobs/{job}/decisions.json$"), answer(json=[]))
    held = []
    page.route(re.compile(r"/jobs/A{22}/text.txt$"), lambda route: held.append(route))
    page.route(re.compile(r"/jobs/B{22}/text.txt$"), answer(body="Text B"))
    with page.expect_request(re.compile(r"/jobs/A{22}/text.txt$")):
        page.goto(f"{url}#{'A' * 22}")
    page.evaluate(f"location.hash = '{'B' * 22}'")
    expect(page.locator("#text")).to_have_text("Text B")
    with page.expect_response(re.compile(r"/jobs/A{22}/text.txt$")):
        held[0].fulfill(body="Text A")
    # give the answer for A time to arrive in the page
    page.wait_for_timeout(500)
    expect(page.locator("#text")).to_have_text("Text B")
    expect(page.locator("#summary")).to_contain_text("B.pdf")
    page.close()


def done_job(root, job_id, text, decisions):
    """A finished job with the given text and uncertain decisions."""
    job = root / job_id
    job.mkdir()
    (job / "input.pdf").write_bytes(LETTER.read_bytes())
    (job / "text.txt").write_text(text)
    for d in decisions:
        d["uncertain"] = True
    (job / "decisions.json").write_text(json.dumps(decisions))
    jobs.write_status(
        job,
        state="done",
        created=time.time(),
        filename="brief.pdf",
        pages=1,
        ocr_pages=[],
        tables=0,
        decisions=len(decisions),
        uncertain=len(decisions),
    )
    return job_id


def test_overlapping_uncertain_decisions_share_a_mark(browser, url, root):
    job_id = done_job(
        root,
        "A" * 22,
        "Mit freundlichen Grüßen Vorstand Max\n",
        [
            {"texts": ["a\nb", "a b"], "chosen": 1, "start": 17, "end": 32},
            {"texts": ["b\nc", "b c"], "chosen": 1, "start": 24, "end": 36},
        ],
    )
    page = browser.new_page()
    page.goto(f"{url}#{job_id}")
    marks = page.locator("#text mark")
    expect(marks).to_have_text(["Grüßen Vorstand Max"])
    assert marks.first.get_attribute("data-options").count("chosen: ") == 2


def test_marks_count_characters_beyond_the_basic_plane(browser, url, root):
    text = "Für 𝑥 und 𝑦 gilt\n"
    start, end = text.index("und"), text.index("𝑦") + 1
    decision = {"texts": ["und\n𝑦", "und 𝑦"], "chosen": 1, "start": start, "end": end}
    job_id = done_job(root, "C" * 22, text, [decision])
    page = browser.new_page()
    page.goto(f"{url}#{job_id}")
    expect(page.locator("#text mark")).to_have_text(["und 𝑦"])
    expect(page.locator("#text")).to_have_text(text.strip())
