"""LiteParse's output turned into pd3f's model; nothing after this module knows LiteParse."""

import sys

from liteparse import LiteParse
from liteparse.types import ParseError

from .model import Block, Box, Document, Font, Line, Page, Word, union


def parse(path):
    parser = LiteParse(
        ocr_enabled=False,
        extract_blocks=True,
        extract_text_metadata=True,
        emit_word_boxes=True,
        # LiteParse parses only the first 1000 pages unless told otherwise
        max_pages=sys.maxsize,
        quiet=True,
    )
    try:
        result = parser.parse(str(path))
    except ParseError as e:
        raise ValueError(f"cannot read {path}: {e}") from e
    finally:
        parser.close()
    return Document([to_page(p, i) for i, p in enumerate(result.pages)])


def to_page(page, index):
    items = [t for t in page.text_items if t.text.strip()]
    blocks = [b for b in page.blocks or [] if b.bbox is not None]
    claimed = [[] for _ in blocks]
    chrome = []
    for item in items:
        i = next((i for i, b in enumerate(blocks) if contains(b.bbox, item)), None)
        (chrome if i is None else claimed[i]).append(item)

    result = Page(page.width, page.height)
    for b, its in zip(blocks, claimed):
        if its:
            result.blocks.append(
                Block(b.kind, lines_of(its, index), b.level, rows_of(b))
            )
    # LiteParse leaves running headers, footers and page numbers outside its blocks; each goes
    # after the last block that starts above it
    for c in [Block("chrome", g) for g in groups(lines_of(chrome, index))]:
        above = [i for i, b in enumerate(result.blocks) if b.box.y < c.box.y]
        result.blocks.insert(above[-1] + 1 if above else 0, c)
    return result


def contains(bbox, item, tolerance=1.0):
    cx, cy = item.x + item.width / 2, item.y + item.height / 2
    return (
        bbox.x - tolerance <= cx <= bbox.x + bbox.width + tolerance
        and bbox.y - tolerance <= cy <= bbox.y + bbox.height + tolerance
    )


def rows_of(block):
    if block.kind != "table":
        return None
    rows = ([block.header] if block.header else []) + (block.rows or [])
    return [[cell.text for cell in row] for row in rows]


def font_of(item, word):
    """The size is the word's height: an item's font height is that of its first glyph, so a
    footnote mark at its start would set the size of all its words."""
    name = item.font_name or ""
    bold = (item.font_weight or 400) >= 600 or "bold" in name.lower()
    return Font(name, round(word.height, 1), bold)


def lines_of(items, page):
    """Items on one baseline make one line: justified text comes as several items."""
    lines = []
    for group in same_line(items):
        boxes = [
            Word(w.text, Box(w.x, w.y, w.width, w.height), font_of(item, w))
            for item in group
            for w in item.words
            if w.text.strip()
        ]
        words = merge_touching(sorted(boxes, key=lambda w: w.box.x))
        if words:
            lines.append(Line(words, union(w.box for w in words), page))
    return lines


def same_line(items):
    """Group items whose vertical centers lie within half a line height."""
    lines = []
    for item in sorted(items, key=lambda t: (t.y + t.height / 2, t.x)):
        center = item.y + item.height / 2
        if lines:
            last = lines[-1][-1]
            if abs(center - (last.y + last.height / 2)) < 0.5 * max(
                item.height, last.height
            ):
                lines[-1].append(item)
                continue
        lines.append([item])
    return lines


def merge_touching(words, gap=0.1):
    """LiteParse gives punctuation its own box: glue boxes that touch into one word."""
    merged = []
    for w in words:
        if merged and w.box.x - merged[-1].box.right < gap * w.box.height:
            m = merged[-1]
            # the font of the longer part, so a footnote mark does not change the word's font
            font = m.font if len(m.text) >= len(w.text) else w.font
            merged[-1] = Word(m.text + w.text, m.box.union(w.box), font)
        else:
            merged.append(w)
    return merged


def groups(lines, gap=1.5):
    """Lines closer than `gap` line heights to the one above, as one group each."""
    result = []
    for line in sorted(lines, key=lambda l: (l.box.y, l.box.x)):
        if result:
            prev = result[-1][-1]
            if line.box.y - prev.box.bottom < gap * prev.box.height:
                result[-1].append(line)
                continue
        result.append([line])
    return result
