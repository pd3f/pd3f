from helpers import line

from pd3f import output
from pd3f.decide import Decision, decide
from pd3f.layout import Layout, Paragraph

RIGHT = 472.0
FULL = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed"


def body(*texts, page=0, y=100.0, kind="body", **kwargs):
    ls = [
        line(t, y + 12 * i, page=page, right=RIGHT if i < len(texts) - 1 else None)
        for i, t in enumerate(texts)
    ]
    return Paragraph(kind, ls, RIGHT, **kwargs)


def result_of(*paragraphs, pages=1, headers=(), footers=(), **kwargs):
    layout = Layout(list(paragraphs), RIGHT, pages, list(headers), list(footers))
    return decide(layout, **kwargs)


def test_offsets_span_the_words_around_a_decision():
    result = result_of(
        body(FULL + " Rechts-", "staat gilt."),
        body("Mit freundlichen Grüßen", "Vorstand", y=300.0),
    )
    text = output.text(result)
    assert text == f"{FULL} Rechtsstaat gilt.\n\nMit freundlichen Grüßen Vorstand\n"
    spans = [text[d.start : d.end] for d in result.decisions]
    assert spans == ["Rechtsstaat", "Grüßen Vorstand"]


def test_a_kept_paragraph_break_marks_the_word_before():
    result = result_of(body(FULL, FULL + "."), body("weiter klein.", page=1), pages=2)
    text = output.text(result)
    [d] = [d for d in result.decisions if d.kind == "page"]
    assert text[d.start : d.end] == "sed."
    assert text.endswith("sed.\n\nweiter klein.\n")


def test_headers_first_footers_last_or_by_page():
    header = [body("Verband", y=30.0), body("Verband", y=30.0, page=1)]
    footer = [body("Seite eins", y=800.0), body("Seite zwei", y=800.0, page=1)]
    paragraphs = (body("Erste Seite."), body("Zweite Seite.", page=1))
    result = result_of(
        *paragraphs, pages=2, headers=[header[0]], footers=footer, merge_pages=False
    )
    assert output.text(result) == (
        "Verband\n\nErste Seite.\n\nZweite Seite.\n\nSeite eins\n\nSeite zwei\n"
    )
    result = result_of(
        *paragraphs,
        pages=2,
        headers=header,
        footers=footer,
        merge_pages=False,
        page_breaks=True,
    )
    assert output.text(result) == (
        "Verband\n\nErste Seite.\n\nSeite eins\n\f"
        "Verband\n\nZweite Seite.\n\nSeite zwei\n\f"
    )


def test_offsets_with_page_breaks():
    result = result_of(
        body("Erste Seite."),
        body("Mit freundlichen Grüßen", "Vorstand", page=1),
        pages=2,
        merge_pages=False,
        page_breaks=True,
    )
    text = output.text(result)
    [d] = result.decisions
    assert text[d.start : d.end] == "Grüßen Vorstand"


def test_markdown():
    table = Paragraph(
        "table",
        [line("a b|c", 300.0), line("1", 312.0)],
        RIGHT,
        rows=[["a", "b|c"], ["1"]],
    )
    result = result_of(
        body("Einleitung", kind="heading", level=1),
        body("Ohne Ebene", kind="heading", y=130.0),
        body("• Erster Punkt", kind="list_item", y=160.0),
        body("- Zweiter Punkt", kind="list_item", y=190.0),
        table,
    )
    assert output.text(result, markdown=True) == (
        "# Einleitung\n\n## Ohne Ebene\n\n- Erster Punkt\n\n- Zweiter Punkt\n\n"
        "| a | b\\|c |\n| --- | --- |\n| 1 |  |\n"
    )
    assert output.text(result).endswith("- Zweiter Punkt\n\na b|c\n1\n")
    assert output.tables(result) == ["a,b|c\r\n1\r\n"]


def decision(layer, margin=None):
    return Decision("line", 1, ["newline", "space"], ["a\nb", "a b"], 1, layer, margin)


def test_uncertain_decisions():
    assert output.uncertain(decision("default"))
    assert output.uncertain(decision("scorer", 0.01))
    assert not output.uncertain(decision("scorer", 0.5))
    assert not output.uncertain(decision("rule"))


def test_decision_log():
    result = result_of(body("Mit freundlichen Grüßen", "Vorstand"))
    assert output.decisions(result) == [
        {
            "kind": "line",
            "page": 1,
            "options": ["newline", "space"],
            "texts": [
                "Mit freundlichen Grüßen\nVorstand",
                "Mit freundlichen Grüßen Vorstand",
            ],
            "chosen": 1,
            "layer": "default",
            "margin": None,
            "start": 17,
            "end": 32,
            "uncertain": True,
        }
    ]
