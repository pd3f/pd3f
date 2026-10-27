import ocrmypdf
import pytest
from helpers import document, line
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine
from ocrmypdf.pluginspec import OrientationConfidence
from PIL import Image

from pd3f import ocr
from pd3f.model import Block


def page_of(text):
    return [Block("paragraph", [line(text)])] if text else []


def test_garbled():
    assert all(map(ocr.garbled, ["�", "", "\x01"]))
    assert not any(map(ocr.garbled, "aÄ1 ."))


def test_pages_to_ocr():
    doc = document(page_of("Text"), page_of(""), page_of("��� x"))
    assert ocr.pages_to_ocr(doc, "auto") == [1, 2]
    assert ocr.pages_to_ocr(doc, "force") == [0, 1, 2]
    assert ocr.pages_to_ocr(doc, "skip") == []
    with pytest.raises(ValueError, match="unknown OCR mode always"):
        ocr.pages_to_ocr(doc, "always")


def test_a_few_garbled_glyphs_need_no_ocr():
    assert not ocr.needs_ocr(document(page_of("Fußnote� im Text")).pages[0])


def test_tesseract_language():
    assert ocr.tesseract_language("de") == "deu"
    assert ocr.tesseract_language("ru", "rus") == "rus"
    with pytest.raises(ValueError, match="no Tesseract language known for ru"):
        ocr.tesseract_language("ru")


def fake_ocrmypdf(calls):
    """OCRmyPDF as far as the plugin sees it: scanning and OCR count pages, then a percentage."""

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        bar = ocr.get_progressbar_class()
        disable = not kwargs["progress_bar"]
        with bar(total=2, desc="OCR", unit="page", disable=disable) as pages:
            pages.update(0.5)
            pages.update(0.5)
            pages.update(completed=2.0)
        with bar(total=100, desc="Linearizing", unit="%", disable=disable) as percent:
            percent.update(50)

    return run


def test_ocr_replaces_the_text_of_the_given_pages(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ocrmypdf, "ocr", fake_ocrmypdf(calls))
    ocr.ocr(tmp_path / "in.pdf", tmp_path / "out.pdf", [0, 2], "deu")
    [(args, kwargs)] = calls
    assert args == (tmp_path / "in.pdf", tmp_path / "out.pdf")
    assert kwargs == {
        "language": "deu",
        "pages": "1,3",
        "mode": "force",
        "rotate_pages": True,
        "rotate_pages_threshold": 5,
        "deskew": True,
        "clean": True,
        "output_type": "pdf",
        "progress_bar": False,
        "plugins": ["pd3f.ocr"],
    }


def test_ocr_reports_its_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(ocrmypdf, "ocr", fake_ocrmypdf([]))
    steps = []
    ocr.ocr(
        tmp_path / "in.pdf",
        tmp_path / "out.pdf",
        [0],
        "deu",
        lambda *step: steps.append(step),
    )
    assert steps == [
        ("OCR", 0, 2),
        ("OCR", 1, 2),
        ("OCR", 2, 2),
        ("Linearizing", None, None),
    ]
    assert ocr.PROGRESS.get() is None


def test_the_progress_ends_with_the_ocr(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise ocrmypdf.exceptions.ExitCodeException("broken")

    monkeypatch.setattr(ocrmypdf, "ocr", broken)
    with pytest.raises(ocrmypdf.exceptions.ExitCodeException):
        ocr.ocr(tmp_path / "in.pdf", tmp_path / "out.pdf", [0], "deu", print)
    assert ocr.PROGRESS.get() is None


@pytest.mark.parametrize(
    ("dpi", "confidence", "trusted"),
    [(300, 9.3, 9.3), (150, 5.2, 5.2), (96, 9.3, 0.0), (96, 14.5, 14.5)],
)
def test_low_resolution_orientations_need_more_confidence(
    monkeypatch, tmp_path, dpi, confidence, trusted
):
    preview = tmp_path / "preview.jpg"
    Image.new("L", (50, 50), 255).save(preview, dpi=(dpi, dpi))
    found = OrientationConfidence(180, confidence)
    monkeypatch.setattr(TesseractOcrEngine, "get_orientation", lambda *args: found)
    engine = ocr.get_ocr_engine(None)
    assert engine.get_orientation(preview, None) == OrientationConfidence(180, trusted)
