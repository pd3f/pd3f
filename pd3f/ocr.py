"""OCR with OCRmyPDF and Tesseract for the pages that have no usable text."""

import unicodedata
from contextvars import ContextVar

import ocrmypdf
from ocrmypdf.builtin_plugins.tesseract_ocr import TesseractOcrEngine
from ocrmypdf.pluginspec import OrientationConfidence
from PIL import Image

# Tesseract's code for each language pd3f has a name for; others are passed as `ocr_lang`
TESSERACT = {"de": "deu", "en": "eng", "es": "spa", "fr": "fra", "it": "ita"}
OCR_MODES = ("auto", "force", "skip")
# how sure Tesseract must be of a page's orientation to turn it: in scans of 150 dpi and more it
# was right from 5 on; below, it turned upright pages up to 11, so OCRmyPDF's default holds
TURN_CONFIDENCE = 5
TURN_CONFIDENCE_LOW_DPI = 14
LOW_DPI = 150


def garbled(char):
    """A glyph the PDF's font maps to no character, a private one or a control code."""
    return char == "�" or unicodedata.category(char) in ("Co", "Cc", "Cn")


def needs_ocr(page, threshold=0.1):
    text = "".join(w.text for line in page.lines for w in line.words)
    return not text or sum(map(garbled, text)) / len(text) > threshold


def pages_to_ocr(document, mode):
    """0-based numbers of the pages to OCR: in `auto` mode those without usable text."""
    if mode not in OCR_MODES:
        raise ValueError(
            f"unknown OCR mode {mode}, choose one of {', '.join(OCR_MODES)}"
        )
    if mode == "skip":
        return []
    return [
        i for i, page in enumerate(document.pages) if mode == "force" or needs_ocr(page)
    ]


def tesseract_language(lang, ocr_lang=None):
    if ocr_lang:
        return ocr_lang
    if lang not in TESSERACT:
        raise ValueError(f"no Tesseract language known for {lang}, set ocr_lang")
    return TESSERACT[lang]


# where the progress of the `ocr` call running in this thread goes
PROGRESS = ContextVar("progress", default=None)


class Progress:
    """OCRmyPDF's progress bar protocol: passes each step on, counted in pages where it can."""

    def __init__(self, *, total=None, desc=None, unit=None, disable=False, **kwargs):
        self.report = None if disable else PROGRESS.get()
        self.step, self.done = desc, 0
        self.total = total if unit == "page" else None
        if self.report:
            self.report(self.step, 0 if self.total else None, self.total)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, n=1, *, completed=None):
        done = completed if completed is not None else self.done + n
        if self.report and self.total and int(done) > int(self.done):
            self.report(self.step, int(done), self.total)
        self.done = done


@ocrmypdf.hookimpl
def get_progressbar_class():
    return Progress


class Tesseract(TesseractOcrEngine):
    """Tesseract, with no confidence in the orientation of a low resolution page below
    `TURN_CONFIDENCE_LOW_DPI`."""

    @staticmethod
    def get_orientation(input_file, options):
        found = TesseractOcrEngine.get_orientation(input_file, options)
        with Image.open(input_file) as preview:
            dpi = min(preview.info["dpi"])
        if dpi < LOW_DPI and found.confidence < TURN_CONFIDENCE_LOW_DPI:
            return OrientationConfidence(found.angle, 0.0)
        return found


@ocrmypdf.hookimpl
def get_ocr_engine(options):
    return Tesseract()


def ocr(path, output, pages, language, progress=None):
    """Write `path` to `output` with the 0-based `pages` OCRed; their old text is replaced.
    Pages are straightened and turned upright first. `progress(step, done, total)` follows
    OCRmyPDF's steps; `done` and `total` count pages or are None."""
    token = PROGRESS.set(progress)
    try:
        ocrmypdf.ocr(
            path,
            output,
            language=language,
            pages=",".join(str(i + 1) for i in pages),
            mode="force",
            rotate_pages=True,
            rotate_pages_threshold=TURN_CONFIDENCE,
            deskew=True,
            clean=True,
            # PDF/A sends the pages kept as they are through Ghostscript, which drops
            # the text of ligatures in some versions
            output_type="pdf",
            progress_bar=progress is not None,
            plugins=[__name__],
        )
    finally:
        PROGRESS.reset(token)
