"""Synthetic documents: words half as wide per character as the font is large."""

import shutil
import subprocess
from pathlib import Path

import pytest

from pd3f.model import Block, Box, Document, Font, Line, Page, Word, union

LEFT = 72.0


def line(text, y=100.0, x=LEFT, size=10.0, page=0, right=None, bold=False):
    """A line of `text`; with `right`, justified to end there."""
    widths = [0.5 * size * len(t) for t in text.split()]
    gap = 0.25 * size
    if right is not None and len(widths) > 1:
        gap = (right - x - sum(widths)) / (len(widths) - 1)
    words, at = [], x
    for t, width in zip(text.split(), widths):
        words.append(Word(t, Box(at, y, width, size), Font("Serif", size, bold)))
        at += width + gap
    return Line(words, union(w.box for w in words), page)


def lines(texts, y=100.0, advance=1.2, size=10.0, **kwargs):
    """Lines one below the other, `advance` font sizes apart."""
    return [
        line(t, y + i * advance * size, size=size, **kwargs)
        for i, t in enumerate(texts)
    ]


def block(texts, kind="paragraph", **kwargs):
    return Block(kind, lines(texts, **kwargs))


def document(*pages, width=595.0, height=842.0):
    """One page per list of blocks."""
    return Document([Page(width, height, list(blocks)) for blocks in pages])


def rendered(text):
    """A decided paragraph as text."""
    return "".join(t if isinstance(t, str) else t.text for t in text.tokens)


DATA = Path(__file__).parent / "data"
# real PDFs with their text as pd3f extracts it, checked by hand
GOLDEN = sorted(DATA.glob("*.pdf"))


def ocr_tools():
    if not all(map(shutil.which, ("tesseract", "unpaper"))):
        return False
    langs = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, check=True
    )
    return "deu" in langs.stdout.split()


needs_ocr_tools = pytest.mark.skipif(
    not ocr_tools(), reason="needs Tesseract with deu and unpaper"
)
