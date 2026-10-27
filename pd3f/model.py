"""pd3f's representation of a parsed PDF: pages of blocks of lines of words, with boxes and fonts.

Coordinates are PDF points with the origin at the top left of the page.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self):
        return self.x + self.width

    @property
    def bottom(self):
        return self.y + self.height

    def union(self, other):
        x, y = min(self.x, other.x), min(self.y, other.y)
        right, bottom = max(self.right, other.right), max(self.bottom, other.bottom)
        return Box(x, y, right - x, bottom - y)


def union(boxes):
    boxes = iter(boxes)
    result = next(boxes)
    for b in boxes:
        result = result.union(b)
    return result


@dataclass(frozen=True)
class Font:
    name: str
    size: float
    bold: bool = False


@dataclass
class Word:
    text: str
    box: Box
    font: Font


@dataclass
class Line:
    words: list[Word]
    box: Box
    # 0-based index of the page
    page: int

    @property
    def text(self):
        return " ".join(w.text for w in self.words)


@dataclass
class Block:
    """Lines LiteParse grouped, a hint for paragraphs.

    `kind`: heading, paragraph, list_item, code, table, figure; `chrome` for the lines
    outside every block, which LiteParse takes for running headers, footers and page numbers.
    """

    kind: str
    lines: list[Line]
    level: int | None = None
    # table cells, row by row
    rows: list[list[str]] | None = None

    @property
    def box(self):
        return union(line.box for line in self.lines)


@dataclass
class Page:
    width: float
    height: float
    # in reading order
    blocks: list[Block] = field(default_factory=list)

    @property
    def lines(self):
        return [line for b in self.blocks for line in b.lines]


@dataclass
class Document:
    pages: list[Page]
