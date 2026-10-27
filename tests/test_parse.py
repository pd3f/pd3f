from types import SimpleNamespace

import pikepdf
from helpers import DATA, line

from pd3f.parse import groups, parse, rows_of


def test_a_real_pdf():
    doc = parse(DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf")
    assert len(doc.pages) == 3
    first = doc.pages[0]
    assert (round(first.width), round(first.height)) == (595, 842)
    words = [w for line in first.lines for w in line.words]
    assert words[0].text == "Bundesministerium"
    assert words[0].font.size == 11.0 and not words[0].font.bold
    assert {b.kind for p in doc.pages for b in p.blocks} == {"paragraph", "list_item"}


def test_every_page_of_a_long_pdf(tmp_path):
    letter = pikepdf.open(DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf")
    long = pikepdf.new()
    for _ in range(1000):
        long.add_blank_page()
    long.pages.append(letter.pages[2])
    long.save(tmp_path / "long.pdf")
    doc = parse(tmp_path / "long.pdf")
    assert len(doc.pages) == 1001 and doc.pages[-1].lines


def test_lines_outside_blocks_are_chrome():
    doc = parse(DATA / "00001_112018_FU_Berlin_Richtlinie_2017_1371.pdf")
    second = doc.pages[1]
    [number] = [b for b in second.blocks if b.kind == "chrome"]
    assert number.lines[0].text == "2"
    # after the last block that starts above it
    assert second.blocks[-1] is number


def test_chrome_lines_close_together_form_one_block():
    lines = [line("Kopf", 30.0), line("zeile", 41.0), line("Seite 2", 800.0)]
    assert [[l.text for l in g] for g in groups(lines)] == [
        ["Kopf", "zeile"],
        ["Seite 2"],
    ]


def test_table_rows():
    cell = SimpleNamespace
    table = SimpleNamespace(
        kind="table",
        header=[cell(text="Name"), cell(text="Wert")],
        rows=[[cell(text="a"), cell(text="1")]],
    )
    assert rows_of(table) == [["Name", "Wert"], ["a", "1"]]
    assert rows_of(SimpleNamespace(kind="table", header=None, rows=None)) == []
    assert rows_of(SimpleNamespace(kind="paragraph")) is None
