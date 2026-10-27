"""Text, Markdown, CSV and the decision log from a decided document."""

import csv
import io
import re
from dataclasses import asdict

# a scorer's decision counts as uncertain below this margin between the best and the second option
UNCERTAIN = 0.05
BULLET = re.compile(r"^[•▪◦·‣∙●○■□–—*-]$")


def uncertain(d):
    return d.layer == "default" or (d.layer == "scorer" and d.margin < UNCERTAIN)


def render(tokens, out, offset, record):
    """Append the tokens' text to `out`; with `record`, set the offsets of their decisions,
    which span the word before a joint and the word after it."""
    pending = []
    word_start = None
    for token in tokens:
        if isinstance(token, str):
            if token.strip():
                word_start = offset
                for d in pending:
                    d.end = offset + len(token)
                pending = []
            out.append(token)
            offset += len(token)
            continue
        d = token.decision
        if record and d is not None:
            d.start = word_start if word_start is not None else offset
            d.end = offset
            pending.append(d)
        out.append(token.text)
        offset += len(token.text)
    return offset


def pages_of(result):
    """The paragraphs in the order of the text: headers first and footers last, either of the
    whole document or, with page breaks, of each page."""
    groups = (result.headers, result.body, result.footers)
    if not result.page_breaks:
        return [[t for group in groups for t in group]]
    pages = [[] for _ in range(result.pages)]
    for group in groups:
        for t in group:
            pages[t.lines[0].page].append(t)
    return pages


def text(result, markdown=False):
    """The paragraphs separated by empty lines; with page breaks, each page ends with a form feed
    like pdftotext's. The plain text sets the offsets in the decision log."""
    out, offset = [], 0
    end = "\n\f" if result.page_breaks else "\n"
    for page in pages_of(result):
        for i, t in enumerate(page):
            if i:
                out.append("\n\n")
                offset += 2
            if not markdown:
                offset = render(t.tokens, out, offset, record=True)
            elif t.kind == "table" and t.rows:
                out.append(markdown_table(t.rows))
            else:
                prefix, tokens = markdown_prefix(t)
                out.append(prefix)
                render(tokens, out, 0, record=False)
        out.append(end)
        offset += len(end)
    return "".join(out)


def markdown_prefix(t):
    if t.kind == "heading":
        return "#" * min(t.level or 2, 6) + " ", t.tokens
    if t.kind == "list_item" and t.tokens and BULLET.match(t.tokens[0]):
        # Markdown's marker replaces the bullet and the space after it
        return "- ", t.tokens[2:]
    return "", t.tokens


def markdown_table(rows):
    width = max(len(r) for r in rows)
    cells = [
        [c.replace("|", "\\|").replace("\n", " ") for c in r] + [""] * (width - len(r))
        for r in rows
    ]
    lines = ["| " + " | ".join(r) + " |" for r in cells]
    lines.insert(1, "|" + " --- |" * width)
    return "\n".join(lines)


def tables(result):
    """Each table as CSV."""
    result_csv = []
    for t in result.body:
        if t.kind == "table" and t.rows:
            f = io.StringIO()
            csv.writer(f).writerows(t.rows)
            result_csv.append(f.getvalue())
    return result_csv


def decisions(result):
    """The decision log, in the order the decisions were made, with offsets into `text`."""
    # writing the plain text sets the offsets
    text(result)
    return [asdict(d) | {"uncertain": uncertain(d)} for d in result.decisions]
