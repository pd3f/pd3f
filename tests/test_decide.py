from collections import Counter

import pytest
from dehyphen import count_words
from helpers import line, lines, rendered

from pd3f import decide as decide_module
from pd3f import output
from pd3f.decide import Decider, Joint, Mark, decide, scorer_for
from pd3f.layout import Layout, Paragraph

RIGHT = 472.0
FULL = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed"


class Scorer:
    """Scores texts by `best`: the texts containing it score 1, the others 2."""

    def __init__(self, best):
        self.best = best
        self.asked = []

    def score(self, texts):
        self.asked.append(texts)
        return [1.0 if self.best in t else 2.0 for t in texts]


class Fixed:
    """Scores each text as `scores` says."""

    def __init__(self, scores):
        self.scores = scores

    def score(self, texts):
        return [self.scores[t] for t in texts]


def decider(words=(), scorer=None):
    counts = count_words([[[w] for w in words]]) if words else Counter()
    return Decider(scorer, counts, RIGHT)


def hyphen(stem, next_word, words=(), scorer=None, h="-"):
    d = decider(words, scorer).hyphen(
        "line", 0, stem, h, next_word, "", "", ["space", "glue", "join"]
    )
    return d.options[d.chosen], d.layer


def test_hyphen_layers():
    assert hyphen("Wort", "weiter", h="—") == ("glue", "rule")
    assert hyphen("Landes", "recht", words=["Landesrecht"]) == ("join", "vocabulary")
    assert hyphen("E", "Mail", words=["E-Mail"]) == ("glue", "vocabulary")
    assert hyphen("Bundes", "und") == ("space", "rule")
    assert hyphen("Max", "Planck") == ("glue", "rule")
    assert hyphen("EU", "weit") == ("glue", "rule")
    assert hyphen("2017", "er") == ("glue", "rule")
    assert hyphen("ABC", "DEF") == ("join", "default")
    assert hyphen("Rechts", "staat") == ("join", "default")


def test_hyphen_scorer():
    scorer = Scorer("Rechts-staat")
    d = decider(scorer=scorer).hyphen(
        "line", 0, "Rechts", "-", "staat", "der", "gilt", ["space", "glue", "join"]
    )
    assert (d.options[d.chosen], d.layer, d.margin) == ("glue", "scorer", 1.0)
    assert scorer.asked == [
        ["der Rechts- staat gilt", "der Rechts-staat gilt", "der Rechtsstaat gilt"]
    ]


def paragraph(texts, kind="body", scorer=None, right=None, **kwargs):
    ls = lines(texts, **kwargs)
    right = right or max(line.box.right for line in ls)
    d = decider(scorer=scorer)
    return rendered(d.paragraph(Paragraph(kind, ls, right))), d.decisions


def settled(decisions):
    return [(d.layer, d.options[d.chosen]) for d in decisions]


def test_intended_line_breaks():
    text, decisions = paragraph(["Mohrenstr. 37", "10117 Berlin"], right=RIGHT)
    assert text == "Mohrenstr. 37\n10117 Berlin"
    assert settled(decisions) == [("layout", "newline")]
    address = ["Herrn Dr. Max Mustermann", "Musterstraße 1", "12345 Berlin"]
    text, decisions = paragraph(address)
    assert text == "\n".join(address)
    # a short line in a listing of short lines, then a line ending early
    assert settled(decisions) == [("layout", "newline")] * 2
    assert paragraph(["Unser Zeichen: Mg/Ze", "Tel.: 030"])[0] == (
        "Unser Zeichen: Mg/Ze\nTel.: 030"
    )


def test_headings_are_one_line():
    text, decisions = paragraph(["Einleitung in", "das Thema"], kind="heading")
    assert (text, settled(decisions)) == (
        "Einleitung in das Thema",
        [("rule", "space")],
    )


def test_flowing_lines():
    text, [d] = paragraph([FULL, "weiter im Text"])
    assert text == FULL + " weiter im Text"
    assert (d.kind, d.layer, d.options[d.chosen]) == ("line", "rule", "space")
    text, [d] = paragraph(["Mit freundlichen Grüßen", "Vorstand"])
    assert (text, d.layer) == ("Mit freundlichen Grüßen Vorstand", "default")
    joined = Scorer("Grüßen Vorstand")
    text, [d] = paragraph(["Mit freundlichen Grüßen", "Vorstand"], scorer=joined)
    assert (text, d.layer) == ("Mit freundlichen Grüßen Vorstand", "scorer")
    text, [d] = paragraph(
        ["Mit freundlichen Grüßen", "Vorstand"], scorer=Scorer("Grüßen")
    )
    assert (text, d.layer) == ("Mit freundlichen Grüßen\nVorstand", "scorer")


def test_a_line_end_margin_is_to_the_other_option():
    a, b = "Mit freundlichen Grüßen", "Vorstand"
    scorer = Fixed({a: 1.0, b: 1.0, f"{a} {b}": 3.0})
    text, [d] = paragraph([a, b], scorer=scorer)
    assert (text, d.margin) == (f"{a}\n{b}", 2.0)


def test_hyphen_inside_a_paragraph():
    ls = [line(FULL + " Rechts-", 100.0, right=RIGHT), line("staat gilt", 112.0)]
    d = decider()
    text = d.paragraph(Paragraph("body", ls, RIGHT))
    assert rendered(text) == FULL + " Rechtsstaat gilt"
    assert [(x.kind, x.layer) for x in d.decisions] == [("line", "default")]


def two_pages(last, first, kind="body", footnote=False):
    """A paragraph on page 1 ending with line `last`, one on page 2 starting with `first`."""
    one = Paragraph(
        "body", [line(FULL, 100.0, right=RIGHT), line(last, 112.0, right=RIGHT)], RIGHT
    )
    two = Paragraph(kind, [line(first, 100.0, page=1)], RIGHT)
    body = [one, two]
    if footnote:
        body.insert(1, Paragraph("footnote", [line("1 Ebd.", 700.0, size=8.0)], RIGHT))
    return Layout(body, RIGHT, 2)


def page_break(last, first, kind="body"):
    """The paragraphs and the page break decisions of `two_pages`."""
    result = decide(two_pages(last, first, kind))
    breaks = [d for d in result.decisions if d.kind == "page"]
    return result.body, [(d.page, d.layer, d.options[d.chosen]) for d in breaks]


def test_page_breaks():
    body, breaks = page_break(FULL, "weiter geht es.")
    assert len(body) == 1 and rendered(body[0]).endswith(f"{FULL} weiter geht es.")
    assert breaks == [(1, "rule", "space")]
    body, breaks = page_break(FULL + ".", "Neuer Absatz.")
    assert isinstance(body[0].tokens[-1], Mark)
    assert (len(body), breaks) == (2, [(1, "rule", "paragraph")])
    assert page_break("Ende", "Neuer Absatz.")[1] == [(1, "layout", "paragraph")]
    assert page_break(FULL + ".", "weiter klein.")[1] == [(1, "default", "paragraph")]
    body, breaks = page_break(FULL + ".", "Überschrift", kind="heading")
    assert (len(body), breaks) == (2, [])


def test_hyphen_across_pages():
    layout = two_pages(FULL + " Rechts-", "staat gilt.")
    [text] = decide(layout).body
    assert rendered(text).endswith("sed Rechtsstaat gilt.")


def test_footnotes_go_last_and_paragraphs_merge_across_them():
    result = decide(two_pages(FULL, "weiter geht es.", footnote=True))
    assert [t.kind for t in result.body] == ["body", "footnote"]
    in_place = decide(
        two_pages(FULL, "weiter geht es.", footnote=True), footnotes_last=False
    )
    assert [t.kind for t in in_place.body] == ["body", "footnote", "body"]


def test_progress_follows_the_pages():
    steps = []
    layout = two_pages(FULL, "weiter geht es.", footnote=True)
    decide(layout, progress=lambda *step: steps.append(step))
    assert steps == [("Text", 1, 2), ("Text", 2, 2)]


def test_without_merging_pages():
    result = decide(two_pages(FULL, "weiter geht es."), merge_pages=False)
    assert len(result.body) == 2
    assert [d.kind for d in result.decisions] == ["line"]


def test_one_copy_of_a_running_header_stays():
    a, b = line("Verband 2018", 30.0), line("Verband 2O18", 30.0, page=1)
    headers = [Paragraph("header", [a], RIGHT), Paragraph("header", [b], RIGHT)]
    layout = Layout([], RIGHT, 2, headers, [], [[a, b]])
    result = decide(layout)
    assert [rendered(t) for t in result.headers] == ["Verband 2018"]
    assert [(d.kind, d.layer, d.texts) for d in result.decisions] == [
        ("copy", "default", ["Verband 2018", "Verband 2O18"])
    ]
    result = decide(layout, Scorer("2O18"))
    assert [rendered(t) for t in result.headers] == ["Verband 2O18"]


def test_identical_copies_need_no_decision():
    a, b = line("Verband 2018", 30.0), line("Verband 2018", 30.0, page=1)
    headers = [Paragraph("header", [a], RIGHT), Paragraph("header", [b], RIGHT)]
    result = decide(Layout([], RIGHT, 2, headers, [], [[a, b]]))
    assert ([rendered(t) for t in result.headers], result.decisions) == (
        ["Verband 2018"],
        [],
    )


def test_a_copy_decision_marks_the_kept_copy():
    a, b = line("Verband 2018", 30.0), line("Verband 2O18", 30.0, page=1)
    headers = [Paragraph("header", [a], RIGHT), Paragraph("header", [b], RIGHT)]
    result = decide(Layout([], RIGHT, 2, headers, [], [[a, b]]))
    text = output.text(result)
    [d] = result.decisions
    assert text[d.start : d.end] == "2018"


def test_the_copy_most_copies_share_stays():
    texts = ["Verband eM", "Verband e.V.", "Verband e.V."]
    lines = [line(t, 30.0, page=n) for n, t in enumerate(texts)]
    headers = [Paragraph("header", [a], RIGHT) for a in lines]
    result = decide(Layout([], RIGHT, 3, headers, [], [lines]), Scorer("eM"))
    assert [rendered(t) for t in result.headers] == ["Verband e.V."]
    assert [(d.kind, d.layer, d.chosen) for d in result.decisions] == [
        ("copy", "rule", 1)
    ]


def test_scorers(monkeypatch):
    made = []
    monkeypatch.setattr(
        decide_module, "FlairScorer", lambda **kwargs: made.append(kwargs)
    )
    assert scorer_for("none", "xx") is None
    scorer_for("flair", "de")
    scorer_for("flair-fast", "fr")
    assert made == [
        {"lang": "de", "cache": None},
        {"lang": "multi-v0", "fast": True, "cache": None},
    ]
    with pytest.raises(ValueError, match="unknown scorer"):
        scorer_for("gpt", "de")
    with pytest.raises(ValueError, match="no flair model for language xx"):
        scorer_for("flair", "xx")


def test_joints_render():
    assert [Joint("-", o).text for o in ("paragraph", "newline", "space")] == [
        "-\n\n",
        "-\n",
        "- ",
    ]
    assert (Joint("-", "glue").text, Joint("-", "join").text) == ("-", "")


def test_page_break_scorer():
    scorer = Scorer(". weiter")
    result = decide(two_pages(FULL + ".", "weiter klein."), scorer)
    [d] = [d for d in result.decisions if d.kind == "page"]
    assert (d.layer, d.options[d.chosen], len(result.body)) == ("scorer", "space", 1)
