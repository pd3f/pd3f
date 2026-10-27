import re
import shutil
import subprocess

import pytest
from helpers import DATA, GOLDEN, needs_ocr_tools
from PIL import Image

from pd3f import extract, ocr, output

LETTER = DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf"


@pytest.mark.parametrize("pdf", GOLDEN, ids=lambda p: p.name[:5])
def test_golden(pdf):
    result = extract(pdf)
    assert result.ocr_pages == []
    assert output.text(result) == pdf.with_suffix(".txt").read_text()


@pytest.fixture
def copy_as_ocr(monkeypatch):
    """OCR that copies the PDF, recording its arguments."""
    calls = []

    def fake(path, out, pages, language, progress):
        calls.append((pages, language))
        progress("OCR", 0, len(pages))
        shutil.copy(path, out)

    monkeypatch.setattr(ocr, "ocr", fake)
    return calls


def test_ocr_reparses_the_ocred_pdf(copy_as_ocr, tmp_path):
    result = extract(LETTER, ocr="force", ocr_output=tmp_path / "ocr.pdf")
    assert copy_as_ocr == [([0, 1, 2], "deu")]
    assert result.ocr_pages == [1, 2, 3]
    assert (tmp_path / "ocr.pdf").exists()
    assert output.text(result) == LETTER.with_suffix(".txt").read_text()


def test_progress(copy_as_ocr):
    steps = []
    extract(
        LETTER,
        ocr="force",
        progress=lambda step, done, total: steps.append((step, done, total)),
    )
    assert steps == [
        ("Parsing", None, None),
        ("OCR", 0, 3),
        ("Parsing", None, None),
        ("Layout", None, None),
        ("Text", 1, 3),
        ("Text", 2, 3),
        ("Text", 3, 3),
    ]


def test_ocr_language(copy_as_ocr):
    with pytest.raises(ValueError, match="no Tesseract language known for ru"):
        extract(LETTER, lang="ru", ocr="force")
    extract(LETTER, lang="ru", ocr="force", ocr_lang="rus")
    assert copy_as_ocr == [([0, 1, 2], "rus")]


def test_unreadable_pdfs(tmp_path):
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(LETTER.read_bytes()[:20000])
    with pytest.raises(ValueError, match=f"cannot read {truncated}"):
        extract(truncated)
    with pytest.raises(FileNotFoundError):
        extract(tmp_path / "missing.pdf")


def test_page_breaks_keep_pages_apart():
    pages = output.text(extract(LETTER, page_breaks=True)).split("\f")
    assert len(pages) == 4 and pages[-1] == ""
    assert all(p.endswith("\n") for p in pages[:-1])


def test_headers_and_footers():
    pdf = DATA / "00001_112018_FU_Berlin_Richtlinie_2017_1371.pdf"
    numbers = {}
    for mode in ("separate", "drop", "keep"):
        text = output.text(extract(pdf, headers_footers=mode))
        numbers[mode] = re.findall(r"^\d+$", text, re.MULTILINE)
    # page numbers are no running text; footnotes like "6 RefE S. 1." stay
    assert numbers == {
        "separate": [],
        "drop": [],
        "keep": [str(n) for n in range(2, 17)],
    }
    assert "6 RefE S. 1." in text


@needs_ocr_tools
def test_real_ocr(tmp_path):
    result = extract(LETTER, ocr="force", ocr_output=tmp_path / "ocr.pdf")
    assert result.ocr_pages == [1, 2, 3]
    assert "Bundessteuerberaterkammer" in output.text(result)


@needs_ocr_tools
def test_an_upside_down_scan_is_turned(tmp_path):
    # Tesseract is sure of this page's orientation to about 11, below OCRmyPDF's default of 14
    page = tmp_path / "page.png"
    subprocess.run(
        ["gs", "-q", "-dBATCH", "-dNOPAUSE", "-dFirstPage=3", "-dLastPage=3"]
        + ["-sDEVICE=pnggray", "-r200", "-o", str(page), str(LETTER)],
        check=True,
    )
    scan = tmp_path / "scan.pdf"
    Image.open(page).rotate(180).save(scan, resolution=200)
    result = extract(scan)
    assert result.ocr_pages == [1]
    assert "Bundessteuerberaterkammer" in output.text(result)


def test_flair_scorer():
    result = extract(LETTER, scorer="flair-fast")
    layers = {d.layer for d in result.decisions}
    assert "scorer" in layers and "default" not in layers
