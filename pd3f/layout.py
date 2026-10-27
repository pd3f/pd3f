"""Paragraphs, running headers and footers, page numbers and footnotes, from the lines of a document."""

import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# a line ending like this ends a sentence or announces what follows, maybe with a closing quote
# or bracket and a footnote mark
SENTENCE_END = re.compile(r"[.:;!?][\"“”'’»«)\]]*\d{0,3}$")
# a table of contents entry: a dot leader and a page number
TOC_ENTRY = re.compile(r"(\.\s?){4,}\d+$")
HEADERS_FOOTERS = ("separate", "drop", "keep")
LIST_MARK = re.compile(r"^([a-z]{1,3}|[ivx]+|\d+)[.)]$")
# how alike, as `SequenceMatcher` measures it, a line must be to a running header or footer to
# be a copy of it in which OCR misread a few letters
ALIKE = 0.9
# a page number, such as "- 3 -", "Seite 3 von 9", "3/9" or "S. 3", as `normalize` writes it
PAGE_NUMBER = re.compile(r"^((seiten?|page|pagina|s) )?#( (von|of|sur|de|di))?( #)?$")


@dataclass
class Paragraph:
    """`kind`: body, heading, list_item, table, footnote, header or footer."""

    kind: str
    lines: list
    # right edge of the blocks the lines are in
    right: float
    level: int | None = None
    rows: list | None = None

    @property
    def text(self):
        return " ".join(line.text for line in self.lines)


@dataclass
class Layout:
    # in reading order, footnotes where they are on the page
    body: list[Paragraph]
    # where full body lines end
    right: float
    pages: int
    headers: list[Paragraph] = field(default_factory=list)
    footers: list[Paragraph] = field(default_factory=list)
    # copies of a running header or footer: texts as they appear, one list per repeated line
    copies: list[list] = field(default_factory=list)


def font_size(line):
    sizes = Counter()
    for w in line.words:
        sizes[w.font.size] += len(w.text)
    return sizes.most_common(1)[0][0]


def space_width(line):
    gaps = [b.box.x - a.box.right for a, b in zip(line.words, line.words[1:])]
    return sum(gaps) / len(gaps) if gaps else 0.25 * font_size(line)


def fits(a, b, right):
    """Whether the first word of `b` would have fit at the end of `a`: then the break is intended."""
    return right - a.box.right - space_width(a) >= b.words[0].box.width


def bold(line):
    return all(w.font.bold for w in line.words)


class Stats:
    """What a body line looks like in this document."""

    def __init__(self, document):
        sizes = Counter()
        for page in document.pages:
            for line in page.lines:
                sizes[font_size(line)] += len(line.text)
        self.size = sizes.most_common(1)[0][0] if sizes else 0
        # OCR layers size each line by its height: sizes jitter, and only spacing counts
        common = sum(count for _, count in sizes.most_common(2))
        self.steady = common >= 0.9 * sum(sizes.values())
        advances = []
        for page in document.pages:
            for block in page.blocks:
                for a, b in zip(block.lines, block.lines[1:]):
                    if font_size(a) == self.size and font_size(b) == self.size:
                        advance = (b.box.bottom - a.box.bottom) / self.size
                        if 0 < advance < 3:
                            advances.append(advance)
        # bottom to bottom, in font sizes: superscripts raise the top of a line, not its bottom
        self.advance = statistics.median(advances) if advances else 1.2
        # where full body lines end: the 90th percentile of their right edges
        rights = sorted(
            line.box.right
            for page in document.pages
            for line in page.lines
            if font_size(line) == self.size
        )
        self.right = rights[int(0.9 * (len(rights) - 1))] if rights else 0

    def advance_of(self, a, b):
        return (b.box.bottom - a.box.bottom) / max(font_size(a), font_size(b))


def normalize(text):
    """The words of a line, numbers as #: OCR varies the case, accents and punctuation of the
    copies of a running header or footer."""
    letters = unicodedata.normalize("NFKD", text.casefold())
    letters = "".join(c for c in letters if not unicodedata.combining(c))
    words = re.findall(r"[^\W\d_]+|\d+", letters)
    if not words:
        # a rule or a line of unmapped glyphs
        return " ".join(text.split())
    return " ".join("#" if w[0].isdigit() else w for w in words)


def running_lines(document, band=0.2):
    """Lines repeated at the same height on other pages, as OCR read them: `header`, `footer` or
    `page_number`, by `id`; and the copies of each repeated header or footer line."""
    candidates = []
    for i, page in enumerate(document.pages):
        for block in page.blocks:
            for line in block.lines:
                top = line.box.bottom < band * page.height
                bottom = line.box.y > (1 - band) * page.height
                if block.kind == "chrome" or top or bottom:
                    candidates.append((i, line, normalize(line.text)))
    groups = copies_at_height(candidates)
    # on half of the pages or three: two footnotes alike, such as "5 Ebd." and "9 Ebd.", may sit
    # at the same height
    needed = max(2, min(3, math.ceil(len(document.pages) / 2)))
    result = {}
    copies = []
    for group in groups:
        key = Counter(key for _, _, key in group).most_common(1)[0][0]
        # a line alike to the copies, but with a number none of them has, is another line
        misread = {id(line) for _, line, _ in unpaged(group)}
        group = [c for c in group if c[2] == key or id(c[1]) not in misread]
        # in a quarter of the copies OCR may have misread the numbers
        pages = len({i for i, _, _ in group})
        if pages < needed or len(unpaged(group)) > len(group) // 4:
            continue
        number = PAGE_NUMBER.match(key) is not None
        lines = [line for _, line, _ in sorted(group, key=lambda c: c[0])]
        if not number:
            copies.append(lines)
        for line in lines:
            page = document.pages[line.page]
            kind = "header" if line.box.y < page.height / 2 else "footer"
            result[id(line)] = "page_number" if number else kind
    return result, copies


def copies_at_height(candidates):
    """The `(page, line, key)` candidates grouped with those alike at the same height on other
    pages, directly or through others."""
    parent = list(range(len(candidates)))

    def root(a):
        while parent[a] != a:
            a = parent[a] = parent[parent[a]]
        return a

    order = sorted(range(len(candidates)), key=lambda a: candidates[a][1].box.y)
    tallest = max((line.box.height for _, line, _ in candidates), default=0)
    for n, a in enumerate(order):
        i, line, key = candidates[a]
        for b in reversed(order[:n]):
            j, other, other_key = candidates[b]
            if line.box.y - other.box.y > tallest:
                break
            near = line.box.y - other.box.y <= max(line.box.height, other.box.height)
            if j != i and near and alike(key, other_key):
                parent[root(a)] = root(b)
    groups = defaultdict(list)
    for a, candidate in enumerate(candidates):
        groups[root(a)].append(candidate)
    return list(groups.values())


def alike(key, other):
    """The same `normalize`d text, or text with words in which OCR misread a few letters; rules
    and lines of unmapped glyphs are alike without being copies."""
    if key == other:
        return True
    if not re.search(r"[^\W_]", key):
        return False
    m = SequenceMatcher(None, key, other)
    return (
        m.real_quick_ratio() >= ALIKE
        and m.quick_ratio() >= ALIKE
        and m.ratio() >= ALIKE
    )


def unpaged(candidates):
    """The `(page, line, key)` candidates with a number that no other one has as it is or counted
    up with the page, as the copies of a running header or footer would; unlike footnotes alike
    such as "5 Ebd., S. 3." and "9 Ebd., S. 7."."""
    numbers = [
        (i, {int(n) for n in re.findall(r"\d+", line.text)})
        for i, line, _ in candidates
    ]
    same = Counter(n for _, found in numbers for n in found)
    stepped = Counter(n - i for i, found in numbers for n in found)
    return [
        candidate
        for candidate, (i, found) in zip(candidates, numbers)
        if any(max(same[n], stepped[n - i]) < 2 for n in found)
    ]


def is_continuation(a, b, block_a, stats, spacing):
    """Whether `b` in another block continues the paragraph of `a`; `spacing`: the page's."""
    advance = stats.advance_of(a, b)
    if not 0 < advance < 1.5 * spacing:
        return False
    last, first = a.words[-1].text, b.words[0].text
    if b.box.x < block_a.box.x - 3 * stats.size:
        return False
    if SENTENCE_END.search(last):
        return False
    # a heading in bold or a larger font
    if bold(a) != bold(b) or (stats.steady and font_size(a) > 1.05 * font_size(b)):
        return False
    full = a.box.right > stats.right - 2 * stats.size
    # LiteParse splits paragraphs mid-sentence, often at a lowercase continuation; a short line
    # ending with a comma is a salutation
    if first[0].islower() and not LIST_MARK.match(first) and (full or last[-1] != ","):
        return True
    # a full line that does not end a sentence goes on in the next line
    return full and abs(b.box.x - a.box.x) < stats.size


def line_advance(page, running, stats):
    """The document's line spacing, unless under a tenth of the page's lines have it, as on
    pages set wider or narrower; then the median spacing of the page's lines."""
    advances = [
        stats.advance_of(a, b)
        for block in page.blocks
        for a, b in zip(block.lines, block.lines[1:])
        if id(a) not in running and id(b) not in running
    ]
    advances = [advance for advance in advances if 0 < advance < 3]
    near = sum(
        abs(advance - stats.advance) <= 0.05 * stats.advance for advance in advances
    )
    if near >= 0.1 * len(advances):
        return stats.advance
    return statistics.median(advances)


def starts_paragraph(a, b, block_a, block_b, stats, spacing):
    if TOC_ENTRY.search(a.text):
        return True
    if block_a is not block_b:
        return not is_continuation(a, b, block_a, stats, spacing)
    advance = stats.advance_of(a, b) / spacing
    if not 0.6 < advance < 1.4:
        return True
    early = fits(a, b, block_a.box.right)
    # without OCR jitter, any extra space between lines parts paragraphs
    if stats.steady and advance > 1.15:
        return True
    if early and SENTENCE_END.search(a.words[-1].text) and b.words[0].text[0].isupper():
        return True
    return bold(a) != bold(b)


def kind_of(lines, blocks, size, stats):
    """`blocks`: the block of each line, `size`: the page's text size. LiteParse takes lines that
    go on in the next block for headings and tables."""
    first = blocks[0]
    if first.kind == "list_item":
        return first.kind
    if first.kind == "table" and all(b is first for b in blocks):
        return first.kind
    # set apart from the body: larger than about 99 % of the body lines, which OCR sizes by the
    # height of each line
    larger = font_size(lines[0]) >= (1.05 if stats.steady else 1.3) * size
    apart = larger or all(map(bold, lines))
    if first.kind == "heading" and (apart or all(b.kind == "heading" for b in blocks)):
        return first.kind
    short = len(lines) <= 2 and not re.search(r"[.,;]$", lines[-1].words[-1].text)
    return "heading" if short and apart else "body"


def text_size(page, running, stats):
    """The document's text size, unless under a tenth of the page's characters have it, as on
    the pages of another document bound into it; then the median size of the page's."""
    sizes = [
        font_size(line)
        for line in page.lines
        if id(line) not in running
        for _ in line.text
    ]
    near = sum(abs(size - stats.size) <= 0.05 * stats.size for size in sizes)
    if near >= 0.1 * len(sizes):
        return stats.size
    return statistics.median(sizes)


def page_paragraphs(page, running, stats):
    flow = [
        (line, b) for b in page.blocks for line in b.lines if id(line) not in running
    ]
    size = text_size(page, running, stats)
    spacing = line_advance(page, running, stats)
    paragraphs = []
    for i, (line, block) in enumerate(flow):
        last, last_block = flow[i - 1] if i else (None, None)
        # the rows of a table stay together
        row = block is last_block and block.kind == "table"
        if i and (
            row or not starts_paragraph(last, line, last_block, block, stats, spacing)
        ):
            paragraphs[-1].append((line, block))
        else:
            paragraphs.append([(line, block)])
    result = []
    for paragraph in paragraphs:
        lines, blocks = [line for line, _ in paragraph], [b for _, b in paragraph]
        kind = kind_of(lines, blocks, size, stats)
        level = blocks[0].level if kind == "heading" else None
        rows = blocks[0].rows if kind == "table" else None
        right = max(b.box.right for b in blocks)
        result.append(Paragraph(kind, lines, right, level, rows))
    return mark_footnotes(result, size)


def is_number(word):
    return re.match(r"^(\d+|\*+)[.)]?$", word.text) is not None


def small(p, size):
    return font_size(p.lines[0]) < 0.95 * size


def starts_footnote(p, size):
    """A number followed by text in a small font, or a number smaller than the text after it;
    a number alone is a page number."""
    words = [w for line in p.lines for w in line.words][:2]
    if len(words) < 2 or not is_number(words[0]):
        return False
    return small(p, size) or words[0].font.size < 0.8 * words[1].font.size


def mark_footnotes(paragraphs, size):
    """The paragraphs at the end of a page that are footnotes: in a smaller font than the body or
    with a smaller mark, from the first one starting with a number."""
    start = len(paragraphs)
    while start > 0 and (
        small(paragraphs[start - 1], size)
        or starts_footnote(paragraphs[start - 1], size)
    ):
        start -= 1
    while start < len(paragraphs) and not starts_footnote(paragraphs[start], size):
        start += 1
    if start == len(paragraphs):
        return paragraphs
    # a paragraph ending with a colon announces what follows, which is no footnote
    if start > 0 and paragraphs[start - 1].lines[-1].words[-1].text.endswith(":"):
        return paragraphs
    footnotes = []
    for p in paragraphs[start:]:
        for i, line in enumerate(p.lines):
            words = line.words
            # a paragraph starting with a number, or a line starting with a smaller one
            new = (
                len(words) > 1
                and is_number(words[0])
                and (i == 0 or words[0].font.size < 0.8 * words[1].font.size)
            )
            if new or not footnotes:
                footnotes.append(Paragraph("footnote", [line], p.right))
            else:
                footnotes[-1].lines.append(line)
                footnotes[-1].right = max(footnotes[-1].right, p.right)
    return paragraphs[:start] + footnotes


def page_footer(paragraphs, page, stats, running, band=0.2):
    """Mark the last paragraphs of a page as its footer when they are at the bottom in a smaller
    font, like a letterhead's address on the first page only."""
    size = text_size(page, running, stats)
    end = len(paragraphs)
    while end > 0:
        p = paragraphs[end - 1]
        if p.kind == "footnote" or not small(p, size):
            break
        if p.lines[0].box.y < (1 - band) * page.height:
            break
        end -= 1
    for p in paragraphs[end:]:
        running |= {id(line): "footer" for line in p.lines}
    return paragraphs[:end]


def group_running(document, running, kind):
    """The header or footer lines of each page, as one paragraph per page."""
    result = []
    for page in document.pages:
        lines = [line for line in page.lines if running.get(id(line)) == kind]
        if lines:
            right = max(line.box.right for line in lines)
            result.append(Paragraph(kind, lines, right))
    return result


def layout(document, headers_footers="separate"):
    """`headers_footers`: `separate` them from the body, `drop` them or `keep` them in place."""
    if headers_footers not in HEADERS_FOOTERS:
        choices = ", ".join(HEADERS_FOOTERS)
        raise ValueError(
            f"unknown headers_footers {headers_footers}, choose one of {choices}"
        )
    stats = Stats(document)
    if headers_footers == "keep":
        body = [p for page in document.pages for p in page_paragraphs(page, {}, stats)]
        return Layout(body, stats.right, len(document.pages))
    running, copies = running_lines(document)
    body = []
    for page in document.pages:
        paragraphs = page_paragraphs(page, running, stats)
        body += page_footer(paragraphs, page, stats, running)
    if headers_footers == "drop":
        return Layout(body, stats.right, len(document.pages))
    return Layout(
        body,
        stats.right,
        len(document.pages),
        group_running(document, running, "header"),
        group_running(document, running, "footer"),
        copies,
    )
