import pytest
from helpers import LEFT, block, document, line, lines

from pd3f.layout import (
    PAGE_NUMBER,
    SENTENCE_END,
    TOC_ENTRY,
    Stats,
    is_continuation,
    kind_of,
    layout,
    normalize,
    running_lines,
    starts_paragraph,
)
from pd3f.model import Block

RIGHT = 472.0
BODY = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do"


# a sentence for each page
PAGE_TEXTS = (
    BODY,
    "Ut enim ad minim veniam quis nostrud exercitation ullamco laboris",
    "Duis aute irure dolor in reprehenderit in voluptate velit esse",
    "Excepteur sint occaecat cupidatat non proident sunt in culpa qui",
    "Officia deserunt mollit anim id est laborum sed ut perspiciatis",
    "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit",
)


def body(n=10, y=100.0, page=0):
    """Full lines; each page's differ, so they are no running header."""
    return block([PAGE_TEXTS[page]] * n, y=y, right=RIGHT, page=page)


STATS = Stats(document([body()]))


def pair(a, b, advance=1.2, bold=False):
    """Lines `a` and `b` in one block, below a full line that sets the block's right edge."""
    first, second = line(a, 112.0, bold=bold), line(b, 112.0 + advance * 10)
    blk = Block("paragraph", [line(BODY, 100.0, right=RIGHT), first, second])
    return first, second, blk


def splits(a, b, advance=1.2, bold=False, stats=STATS):
    first, second, blk = pair(a, b, advance, bold)
    return starts_paragraph(first, second, blk, blk, stats, stats.advance)


def test_stats():
    assert (STATS.size, STATS.steady) == (10.0, True)
    assert (STATS.right, STATS.advance) == pytest.approx((RIGHT, 1.2))


def test_ocr_layers_have_unsteady_sizes():
    jitter = [line(BODY, 100.0 + 12 * i, size=9.0 + 0.2 * i) for i in range(8)]
    assert not Stats(document([Block("paragraph", jitter)])).steady


def test_patterns():
    assert SENTENCE_END.search("gewählt.18")
    assert SENTENCE_END.search('umgesetzt."')
    assert not SENTENCE_END.search("Mohrenstr")
    assert TOC_ENTRY.search("Einleitung ........ 2")
    assert TOC_ENTRY.search("1. Regelungsort.......... 4")
    assert not TOC_ENTRY.search("siehe S. 4")
    for number in (
        "3",
        "- 3 -",
        "Seite 3 von 9",
        "3/9",
        "page 3 of 9",
        "S. 3",
        "Página 3",
    ):
        assert PAGE_NUMBER.match(normalize(number)), number
    assert not PAGE_NUMBER.match(normalize("Kapitel 3"))


def test_ocr_variants_of_a_line_read_alike():
    assert normalize("Berlin, 2. März 2016") == normalize("Berlin, 2. Marz 2016")
    assert normalize("Handelskammertag e.V.") == normalize("Handelskammertag. e.V, _ .")
    assert normalize("Breite Straße 29") == "breite strasse #"
    assert normalize("���") != normalize("��") != normalize("__")


def test_lines_in_a_block_stay_together():
    assert not splits("Mohrenstr. 37", "10117 Berlin")
    assert not splits("Das ist das Ende.", "weiter in Kleinschrift")


def test_a_sentence_ending_early_ends_the_paragraph():
    assert splits("Das ist das Ende.", "Neuer Absatz")


def test_extra_space_parts_paragraphs_without_ocr_jitter():
    # 1.25 and 1.5 times the usual advance of 1.2
    assert splits("Mohrenstr. 37", "10117 Berlin", advance=1.5)
    jittery = Stats(document([body()]))
    jittery.steady = False
    assert not splits("Mohrenstr. 37", "10117 Berlin", advance=1.5, stats=jittery)
    assert splits("Mohrenstr. 37", "10117 Berlin", advance=1.8, stats=jittery)


def test_toc_entries_and_bold_lines_end_paragraphs():
    assert splits("Einleitung ........ 2", "Hauptteil ........ 5")
    assert splits("Allgemeines", "Der Entwurf", bold=True)


def across(a, b, advance=1.2, x=LEFT, full=False):
    """Whether line `b` in the next block continues the paragraph of line `a`."""
    last = line(a, 112.0, right=RIGHT if full else None)
    a_block = Block("paragraph", [line(BODY, 100.0, right=RIGHT), last])
    b_line = line(b, 112.0 + advance * 10, x=x)
    return is_continuation(last, b_line, a_block, STATS, STATS.advance)


def test_continuation_in_the_next_block():
    assert across(BODY, "weiter geht es", full=True)
    assert across(BODY, "Weiter geht es", full=True)
    assert across("Mohrenstr. 37", "klein weiter")
    assert not across(BODY + ".", "weiter geht es", full=True)
    # a salutation
    assert not across("Sehr geehrte Damen und Herren,", "wir danken")
    assert not across(BODY, "weiter", advance=2.0, full=True)
    assert not across(BODY, "weiter", x=30.0, full=True)
    assert not across("kurz", "Weiter")


def page_with_running(n):
    return [
        Block("chrome", [line("Musterverband Stellungnahme", 30.0, page=n)]),
        body(5, page=n),
        Block("chrome", [line(f"- {n + 1} -", 800.0, page=n)]),
    ]


def test_running_lines():
    doc = document(page_with_running(0), page_with_running(1))
    kinds, copies = running_lines(doc)
    headers = [doc.pages[i].blocks[0].lines[0] for i in (0, 1)]
    numbers = [doc.pages[i].blocks[2].lines[0] for i in (0, 1)]
    assert [kinds[id(h)] for h in headers] == ["header", "header"]
    assert [kinds[id(n)] for n in numbers] == ["page_number", "page_number"]
    assert copies == [headers]


def bottom_lines(*texts):
    """A page per text, with the text in a small font at its bottom."""
    pages = [
        [body(5, page=n), Block("paragraph", [line(t, 780.0, size=8.0, page=n)])]
        for n, t in enumerate(texts)
    ]
    kinds, _ = running_lines(document(*pages))
    return [kinds.get(id(p[1].lines[0])) for p in pages]


def test_numbers_in_running_lines_stay_or_go_up_with_the_page():
    pages = ("Seite 1 von 3", "Seite 2 von 3", "Seite 3 von 3")
    assert bottom_lines(*pages) == ["page_number"] * 3
    assert bottom_lines("Stand 2018", "Stand 2018") == ["footer"] * 2
    assert (
        bottom_lines("5 Ebd., S. 3.", "9 Ebd., S. 7.", "12 Ebd., S. 8.") == [None] * 3
    )


def test_running_lines_as_ocr_misread_them():
    footers = (
        "Recht und Informatik e.V.",
        "Recht und Informatik eM",
        "Recht und lnformatik e.V.",
    )
    assert bottom_lines(*footers) == ["footer"] * 3
    # a copy with a number the others lack stays in the text
    assert bottom_lines(*footers, "Recht und Informatik 6.V.") == ["footer"] * 3 + [
        None
    ]
    phones = ["Tel 421 792 6293"] * 3 + ["Tel 421 792 8293"]
    assert bottom_lines(*phones) == ["footer"] * 4
    headings = ("Zu Punkt 4:", "Zu Punkt 5:", "Zu Punkt 9:")
    assert bottom_lines(*headings) == [None] * 3
    citations = (
        "15 Vgl. Wickern, StPO, 26. Aufl. 2010, § 185 Rn. 9 ff.",
        "Rn. 11; Wickern, StPO, 26. Aufl. 2010, § 185 Rn. 13.",
        "30 Vgl. Wickern, StPO, 26. Aufl. 2010, § 189 GVG Rn. 9.",
    )
    assert bottom_lines(*citations) == [None] * 3
    assert bottom_lines("Anlage A", "Anlage B", "Anlage C") == [None] * 3


def test_running_lines_repeat_on_half_the_pages_or_three():
    letterhead = ["Musterstraße 1", "Musterstraße 1", "ohne", "ohne", "ohne", "ohne"]
    assert bottom_lines(*letterhead)[:2] == [None, None]
    assert bottom_lines(*letterhead[:4])[:2] == ["footer", "footer"]


def test_headers_footers_modes():
    doc = document(page_with_running(0), page_with_running(1))
    separate = layout(doc)
    assert [p.kind for p in separate.headers] == ["header", "header"]
    assert all("Musterverband" not in p.text for p in separate.body)
    assert all(p.text != "- 1 -" for p in separate.body)
    assert separate.pages == 2
    dropped = layout(doc, "drop")
    assert dropped.headers == [] and dropped.copies == []
    assert [p.text for p in dropped.body] == [p.text for p in separate.body]
    kept = layout(doc, "keep")
    assert kept.headers == []
    assert "Musterverband Stellungnahme" in [p.text for p in kept.body]
    with pytest.raises(ValueError, match="unknown headers_footers dorp"):
        layout(doc, "dorp")


def test_footnotes():
    doc = document(
        [
            body(5),
            block(["1 Vgl. Muster, S. 1."], y=700.0, size=8.0),
            block(["2 Ebd."], y=720.0, size=8.0),
        ]
    )
    paragraphs = layout(doc).body
    assert [p.kind for p in paragraphs] == ["body", "footnote", "footnote"]
    assert paragraphs[2].text == "2 Ebd."


def test_numbered_lines_after_a_colon_are_no_footnotes():
    doc = document(
        [
            block([BODY, "wie folgt:"], right=RIGHT),
            block(["1 Erstens.", "2 Zweitens."], y=130.0, size=8.0),
        ]
    )
    assert "footnote" not in [p.kind for p in layout(doc).body]


def test_letterhead_footer_on_one_page():
    doc = document(
        [body(5), block(["Musterstraße 1 · 12345 Berlin"], y=800.0, size=8.0)]
    )
    result = layout(doc)
    assert [p.text for p in result.footers] == ["Musterstraße 1 · 12345 Berlin"]
    assert all("Musterstraße" not in p.text for p in result.body)


def test_headings():
    doc = document(
        [
            Block("heading", lines(["Einleitung"]), level=2),
            block(["Größer gesetzt"], y=130.0, size=12.0),
            body(3, y=160.0),
        ]
    )
    paragraphs = layout(doc).body
    assert [(p.kind, p.level) for p in paragraphs] == [
        ("heading", 2),
        ("heading", None),
        ("body", None),
    ]
    assert paragraphs[2].right == pytest.approx(RIGHT)


def test_ocr_jitter_makes_no_headings():
    jittery = Stats(document([body()]))
    jittery.steady = False
    heading = Block("paragraph", [line("Allgemeines", size=11.0)])
    assert kind_of(heading.lines, [heading], 10.0, STATS) == "heading"
    assert kind_of(heading.lines, [heading], 10.0, jittery) == "body"
    title = Block("paragraph", [line("Stellungnahme", size=14.0)])
    assert kind_of(title.lines, [title], 10.0, jittery) == "heading"


def test_a_document_bound_into_another_keeps_its_text():
    # two pages in a larger font, then one of another document
    pages = [
        [block([PAGE_TEXTS[n]] * 20, size=12.0, right=RIGHT, page=n)] for n in (0, 1)
    ]
    pages.append(
        [
            block(["1 Einleitung"], size=9.0, page=2),
            block([PAGE_TEXTS[2]] * 5, y=130.0, size=9.0, right=RIGHT, page=2),
            block([PAGE_TEXTS[3]], y=780.0, size=9.0, right=RIGHT, page=2),
        ]
    )
    result = layout(document(*pages))
    assert [p.kind for p in result.body if p.lines[0].page == 2] == ["body"] * 3
    assert result.footers == []


def test_a_table_stays_one_paragraph():
    rows = [["Jahr", "Fälle"], ["2018", "12"], ["2019", "17"]]
    texts = [" ".join(row) for row in rows]
    table = Block("table", lines(texts), rows=rows)
    table.lines[0] = line(texts[0], bold=True)
    paragraphs = layout(document([table, body(3, y=200.0)])).body
    assert [(p.kind, p.rows) for p in paragraphs] == [("table", rows), ("body", None)]


def test_lines_liteparse_takes_for_a_heading_go_on():
    taken = Block(
        "heading", [line("Die Regelung verstößt gegen", right=RIGHT)], level=2
    )
    rest = block(["den Grundsatz der Verhältnismäßigkeit."], y=112.0)
    paragraphs = layout(document([taken, rest])).body
    assert [(p.kind, p.level) for p in paragraphs] == [("body", None)]


def test_a_heading_set_apart_ends_before_the_text():
    heading = Block("heading", [line("Einleitung", bold=True)], level=2)
    text = block(["die Regelung verstößt gegen den Grundsatz."], y=112.0)
    paragraphs = layout(document([heading, text])).body
    assert [(p.kind, p.text) for p in paragraphs] == [
        ("heading", "Einleitung"),
        ("body", "die Regelung verstößt gegen den Grundsatz."),
    ]


def test_a_page_set_wider_keeps_its_paragraphs():
    pages = [[body(page=n)] for n in (0, 1)]
    wide = {"advance": 1.8, "right": RIGHT, "page": 2}
    first = lines([PAGE_TEXTS[2]] * 6, **wide)
    second = lines([PAGE_TEXTS[3]] * 3, y=220.0, **wide)
    on = block(["weiter " + PAGE_TEXTS[4]], y=274.0, **wide)
    pages.append([Block("paragraph", first + second), on])
    result = layout(document(*pages))
    assert [len(p.lines) for p in result.body if p.lines[0].page == 2] == [6, 4]
