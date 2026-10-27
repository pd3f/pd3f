"""Reconstruct the continuous text of PDFs."""

import tempfile
from importlib.metadata import version
from pathlib import Path

from ocrmypdf.exceptions import ExitCodeException

from . import decide, layout, parse
from . import ocr as ocr_
from .decide import SCORERS
from .layout import HEADERS_FOOTERS
from .ocr import OCR_MODES

__version__ = version("pd3f")

__all__ = ["ERRORS", "HEADERS_FOOTERS", "OCR_MODES", "SCORERS", "extract"]

# what a broken PDF or an unsuitable option makes `extract` raise
ERRORS = (ValueError, OSError, ExitCodeException)


def extract(
    path,
    lang="de",
    scorer="none",
    headers_footers="separate",
    footnotes_last=True,
    page_breaks=False,
    ocr="auto",
    ocr_lang=None,
    ocr_output=None,
    progress=decide.quiet,
):
    """The decided document of the PDF at `path`; see `output` for text, Markdown and the log.

    `scorer`: one of `SCORERS`; `headers_footers`: one of `HEADERS_FOOTERS`;
    `page_breaks`: keep each page's text apart, ending pages with a form feed;
    `ocr`: one of `OCR_MODES`, with Tesseract's language `ocr_lang` if `lang` has none;
    `ocr_output`: where to keep the OCRed PDF;
    `progress(step, done, total)`: called as the steps advance, `done` and `total` count pages
    or are None.
    """
    scorer = decide.scorer_for(scorer, lang)
    progress("Parsing", None, None)
    document = parse.parse(path)
    pages = ocr_.pages_to_ocr(document, ocr)
    if pages:
        language = ocr_.tesseract_language(lang, ocr_lang)
        with tempfile.TemporaryDirectory() as tmp:
            output = ocr_output or Path(tmp) / "ocr.pdf"
            ocr_.ocr(path, output, pages, language, progress)
            progress("Parsing", None, None)
            document = parse.parse(output)
    progress("Layout", None, None)
    lay = layout.layout(document, headers_footers)
    # with headers and footers in place, a paragraph never runs on across a page break
    merge = headers_footers != "keep" and not page_breaks
    footnotes_last = footnotes_last and not page_breaks
    result = decide.decide(lay, scorer, footnotes_last, merge, page_breaks, progress)
    result.ocr_pages = [i + 1 for i in pages]
    return result
