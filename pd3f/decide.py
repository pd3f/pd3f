"""The decisions that change the text, each settled by the first layer that can: layout, rule,
the document's vocabulary, a scorer, or a fixed default. Every decision is recorded.
"""

import string
from collections import Counter
from dataclasses import dataclass, field
from itertools import chain, islice

from dehyphen import FlairScorer, count_words
from dehyphen.dehyphen import hyphen_of, is_dash, normalize

from .layout import LIST_MARK, SENTENCE_END, fits

# what each joint between two lines renders, given the hyphen the first line ends with
JOINTS = {
    "paragraph": lambda h: h + "\n\n",
    "newline": lambda h: h + "\n",
    "space": lambda h: h + " ",
    "glue": lambda h: h,
    "join": lambda h: "",
}

# flair model per language, `flair-fast` uses the faster models; see dehyphen's MODELS
FLAIR = {
    "flair": {"de": "de", "en": "en", "es": "es", "fr": "fr", "it": "it"},
    "flair-fast": {
        "de": "multi-v0-fast",
        "en": "en-fast",
        "es": "es-fast",
        "fr": "multi-v0-fast",
        "it": "multi-v0-fast",
    },
}
SCORERS = ("none", *FLAIR)

# after a line-final hyphen, these words leave the hyphen standing alone: "Bundes- und Landesrecht"
CONJUNCTIONS = {
    "und",
    "oder",
    "bzw.",
    "sowie",
    "bis",
    "noch",
    "als",
    "wie",
    "and",
    "or",
    "nor",
}
CONJUNCTIONS |= {"et", "ou", "y", "o", "e", "u", "ed", "od"}


def scorer_for(name, lang, cache=None):
    """`None` for `none`, which decides by fixed defaults."""
    if name == "none":
        return None
    if name not in FLAIR:
        raise ValueError(f"unknown scorer {name}, choose one of {', '.join(SCORERS)}")
    if lang not in FLAIR[name]:
        raise ValueError(f"no {name} model for language {lang}")
    model = FLAIR[name][lang]
    if model.endswith("-fast"):
        return FlairScorer(lang=model.removesuffix("-fast"), fast=True, cache=cache)
    return FlairScorer(lang=model, cache=cache)


@dataclass
class Decision:
    """`kind`: line (a line end inside a paragraph), page (a paragraph cut by a page break) or copy
    (which copy of a repeated header or footer stays). `texts` shows each option in place."""

    kind: str
    # 1-based, unlike `Line.page`
    page: int
    options: list[str]
    texts: list[str]
    chosen: int
    layer: str
    margin: float | None = None
    # offsets in the text output, set when it is written
    start: int | None = None
    end: int | None = None


@dataclass
class Joint:
    """Where two lines meet; renders as one of `JOINTS`."""

    hyphen: str
    option: str
    decision: Decision | None = None

    @property
    def text(self):
        return JOINTS[self.option](self.hyphen)


@dataclass
class Mark:
    """A decision that left the text as it is, at the end of the word before."""

    decision: Decision
    text = ""


@dataclass
class Text:
    """A paragraph as words, spaces and joints, and the layout lines it came from."""

    kind: str
    tokens: list
    lines: list
    level: int | None = None
    rows: list | None = None


@dataclass
class Result:
    body: list[Text]
    headers: list[Text]
    footers: list[Text]
    decisions: list[Decision]
    pages: int
    # the text shows where pages end
    page_breaks: bool = False
    # 1-based numbers of the pages whose text comes from OCR
    ocr_pages: list[int] = field(default_factory=list)


def words_of(line):
    return [w.text for w in line.words]


def context(lines, idx, n=2):
    """The `n` words before the last word of line `idx` and after the first word of the next line."""
    back = chain.from_iterable(reversed(words_of(lines[i])) for i in range(idx, -1, -1))
    ahead = chain.from_iterable(words_of(lines[i]) for i in range(idx + 1, len(lines)))
    before = list(islice(back, 1, n + 1))[::-1]
    return " ".join(before), " ".join(islice(ahead, 1, n + 1))


class Decider:
    def __init__(self, scorer, words, right):
        self.scorer = scorer
        self.words = words
        # right edge of the text column
        self.right = right
        self.decisions = []

    def record(self, kind, page, options, texts, chosen, layer, margin=None):
        d = Decision(
            kind, page + 1, options, texts, options.index(chosen), layer, margin
        )
        self.decisions.append(d)
        return d

    def ask(self, texts, options=None):
        """The most plausible option and the margin to the second, or `None` without a scorer;
        text `i` stands for option `options[i]`, by default `i`."""
        if self.scorer is None or min(map(len, texts)) < 2:
            return None
        best = {}
        for option, score in zip(
            options or range(len(texts)), self.scorer.score(texts)
        ):
            best[option] = min(score, best.get(option, score))
        first, second = sorted(best, key=best.__getitem__)[:2]
        return first, (best[second] - best[first]) / best[first]

    def hyphen(self, kind, page, stem, h, next_word, before, after, options):
        """Settle a line end after a hyphen, among `options` (a subset of paragraph, space, glue, join)."""
        texts = {
            "paragraph": f"{stem}{h}\n\n{next_word}",
            "space": f"{stem}{h} {next_word}",
            "glue": f"{stem}{h}{next_word}",
            "join": f"{stem}{next_word}",
        }
        shown = [texts[o] for o in options]
        if is_dash(stem + h):
            # a dash ending a word joins the next word without a space
            return self.record(kind, page, options, shown, "glue", "rule")
        kept, joined = (bool(self.words[normalize(texts[o])]) for o in ("glue", "join"))
        if kept != joined:
            chosen = "glue" if kept else "join"
            return self.record(kind, page, options, shown, chosen, "vocabulary")
        if next_word in CONJUNCTIONS:
            # "Bundes- und Landesrecht"
            return self.record(kind, page, options, shown, "space", "rule")
        if (
            next_word[0].isupper() or stem[-1].isupper() or stem[-1].isdigit()
        ) and not (stem.isupper() and next_word.isupper()):
            # hyphenation goes on in lowercase: an uppercase start or an acronym keeps the hyphen
            return self.record(kind, page, options, shown, "glue", "rule")
        answer = self.ask([f"{before} {t} {after}".strip() for t in shown])
        if answer is None:
            return self.record(kind, page, options, shown, "join", "default")
        best, margin = answer
        return self.record(kind, page, options, shown, options[best], "scorer", margin)

    def line_end(self, lines, i, right, one_line=False, listing=False):
        """The joint between line `i` and the next one of a paragraph; with `one_line`, never a
        new line, in a `listing` of short lines a new line."""
        a, b = lines[i], lines[i + 1]
        last, first = a.words[-1].text, b.words[0].text
        h = hyphen_of(last) or ""
        stem = last[: -len(h)] if h else last
        line_a, line_b = " ".join(words_of(a)), " ".join(words_of(b))
        texts = [f"{line_a}\n{line_b}", f"{line_a} {line_b}"]
        options = ["newline", "space"]
        if not one_line and fits(a, b, right):
            # the line ends early, hyphen or not
            d = self.record("line", a.page, options, texts, "newline", "layout")
            return Joint(h, "newline", d)
        if h:
            before, after = context(lines, i)
            hyphen_options = ["space", "glue", "join"]
            d = self.hyphen(
                "line", a.page, stem, h, first, before, after, hyphen_options
            )
            return Joint(h, d.options[d.chosen], d)
        if one_line:
            d = self.record("line", a.page, options, texts, "space", "rule")
        elif listing and len(a.words) <= 5:
            d = self.record("line", a.page, options, texts, "newline", "layout")
        elif first.endswith(":") and any(w.text.endswith(":") for w in a.words):
            # fields such as "Tel.: …" and "Fax: …" stand on lines of their own
            d = self.record("line", a.page, options, texts, "newline", "rule")
        elif len(a.words) > 5 or last[-1] in string.punctuation:
            d = self.record("line", a.page, options, texts, "space", "rule")
        elif (
            answer := self.ask(
                [line_a, line_b, f"{line_a} {line_b}"], ["newline", "newline", "space"]
            )
        ) is not None:
            # as in pd3f 0.5: a new line when either line alone is more plausible than both joined
            chosen, margin = answer
            d = self.record("line", a.page, options, texts, chosen, "scorer", margin)
        else:
            d = self.record("line", a.page, options, texts, "space", "default")
        return Joint("", d.options[d.chosen], d)

    def page_break(self, a, b):
        """The joint between the last line `a` of a page and the first line `b` of the next,
        each in a paragraph of its own: a `Mark` keeps the paragraphs apart."""
        last, first = a.words[-1].text, b.words[0].text
        h = hyphen_of(last) or ""
        if h:
            # a hyphen at the end of a page goes on on the next one
            before, after = " ".join(words_of(a)[-3:-1]), " ".join(words_of(b)[1:3])
            options = ["space", "glue", "join"]
            d = self.hyphen(
                "page", a.page, last[: -len(h)], h, first, before, after, options
            )
            return Joint(h, d.options[d.chosen], d)
        line_a, line_b = " ".join(words_of(a)), " ".join(words_of(b))
        options = ["paragraph", "space"]
        texts = [f"{line_a}\n\n{line_b}", f"{line_a} {line_b}"]
        if fits(a, b, self.right):
            d = self.record("page", a.page, options, texts, "paragraph", "layout")
        elif SENTENCE_END.search(last) and first[0].isupper():
            d = self.record("page", a.page, options, texts, "paragraph", "rule")
        elif not SENTENCE_END.search(last) and not LIST_MARK.match(first):
            # a full line that does not end a sentence goes on
            d = self.record("page", a.page, options, texts, "space", "rule")
        elif (answer := self.ask(texts)) is not None:
            best, margin = answer
            d = self.record(
                "page", a.page, options, texts, options[best], "scorer", margin
            )
        else:
            d = self.record("page", a.page, options, texts, "paragraph", "default")
        return Joint("", "space", d) if d.chosen else Mark(d)

    def copies(self, copies):
        """Of each repeated header or footer line, the copy to keep: the `id`s of the others, and
        the decision on each kept copy that differs from the others, by its `id`."""
        dropped, decided = set(), {}
        for lines in copies:
            texts = [line.text for line in lines]
            if len(set(texts)) == 1:
                dropped |= {id(line) for line in lines[1:]}
                continue
            options = [str(i) for i in range(len(lines))]
            common, count = Counter(texts).most_common(1)[0]
            if 2 * count > len(texts):
                # OCR misread the others
                keep, layer, margin = texts.index(common), "rule", None
            elif (answer := self.ask(texts)) is None:
                keep, layer, margin = 0, "default", None
            else:
                (keep, margin), layer = answer, "scorer"
            page = lines[0].page
            d = self.record("copy", page, options, texts, str(keep), layer, margin)
            decided[id(lines[keep])] = d
            dropped |= {id(line) for i, line in enumerate(lines) if i != keep}
        return dropped, decided

    def paragraph(self, p):
        """Words, spaces and joints of a layout paragraph."""
        if p.kind == "table":
            rows = [[*spaced(words_of(line)), "\n"] for line in p.lines]
            return Text(
                p.kind, list(chain.from_iterable(rows))[:-1], list(p.lines), rows=p.rows
            )
        right = p.right
        # most lines end before the next word would have to wrap, as in an address
        early = [fits(a, b, right) for a, b in zip(p.lines, p.lines[1:])]
        listing = len(early) > 1 and 2 * sum(early) >= len(early)
        tokens = []
        for i, line in enumerate(p.lines):
            words = words_of(line)
            if i + 1 < len(p.lines):
                # a heading is one line of text
                heading = p.kind == "heading"
                joint = self.line_end(p.lines, i, right, heading, listing)
                if joint.hyphen:
                    words[-1] = words[-1][: -len(hyphen_of(words[-1]))]
                tokens += [*spaced(words), joint]
            else:
                tokens += spaced(words)
        return Text(p.kind, tokens, list(p.lines), p.level, p.rows)


def spaced(words):
    return list(chain.from_iterable((w, " ") for w in words))[:-1]


def quiet(step, done, total):
    """Progress that goes nowhere."""


def decide(
    layout,
    scorer=None,
    footnotes_last=True,
    merge_pages=True,
    page_breaks=False,
    progress=quiet,
):
    """Turn the layout into text; `merge_pages` rejoins paragraphs cut by a page break.
    `progress("Text", page, pages)` follows the pages."""
    paragraphs = [
        [[w.text for w in line.words] for line in p.lines] for p in layout.body
    ]
    decider = Decider(scorer, count_words(paragraphs), layout.right)
    dropped, decided = decider.copies(layout.copies)
    marks = {key: [Mark(d)] for key, d in decided.items()}
    body, page = [], None
    for p in layout.body:
        if p.lines[0].page != page:
            page = p.lines[0].page
            progress("Text", page + 1, layout.pages)
        body.append(decider.paragraph(p))
    if footnotes_last:
        body = [t for t in body if t.kind != "footnote"] + [
            t for t in body if t.kind == "footnote"
        ]
    if merge_pages:
        body = merge_page_breaks(body, decider)

    def running(paragraphs):
        texts = []
        for p in paragraphs:
            lines = [line for line in p.lines if id(line) not in dropped]
            if lines:
                # a kept copy that differs from the others carries its decision at its end
                tokens = list(
                    chain.from_iterable(
                        [*spaced(words_of(l)), *marks.get(id(l), []), "\n"]
                        for l in lines
                    )
                )
                texts.append(Text(p.kind, tokens[:-1], lines))
        return texts

    return Result(
        body,
        running(layout.headers),
        running(layout.footers),
        decider.decisions,
        layout.pages,
        page_breaks,
    )


def merge_page_breaks(body, decider):
    """Join the last paragraph of a page with the first of the next where the decider says so."""
    result = []
    for t in body:
        prev = result[-1] if result else None
        if (
            prev
            and prev.kind in ("body", "list_item")
            and t.kind == "body"
            and t.lines[0].page == prev.lines[-1].page + 1
        ):
            joint = decider.page_break(prev.lines[-1], t.lines[0])
            if isinstance(joint, Joint):
                if joint.hyphen:
                    prev.tokens[-1] = prev.tokens[-1][
                        : -len(hyphen_of(prev.tokens[-1]))
                    ]
                prev.tokens += [joint, *t.tokens]
                prev.lines += t.lines
                continue
            prev.tokens.append(joint)
        result.append(t)
    return result
