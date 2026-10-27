# pd3f 1.0 design

Record of 2026-10-27: how pd3f 1.0 is built and the measurements behind its choices.

## Starting point

pd3f 0.x consisted of:

- a Flask app with an RQ worker and Redis,
- a Parsr container (6 GB, amd64 only) that found words, lines, paragraphs and tables,
- an OCR container that polled a shared folder and ran OCRmyPDF on scans,
- `pd3f-core` (PyPI package `pd3f`), which post-processed Parsr's JSON: it rejoined hyphenated words, joined lines into paragraphs and separated headers, footers and footnotes,
- `dehyphen`, which decided those joins with Flair's character language models, run with torch.

Parsr is unmaintained; its README recommends LiteParse (run-llama, Apache-2.0, Rust on PDFium, Python binding `liteparse`).

pd3f 1.0 is one repository, one Python package and one Docker image, native on amd64 and arm64:

| 0.x | 1.0 |
|---|---|
| Parsr container and its JSON, `parsr_*` parameters | LiteParse in-process |
| Redis, RQ, rq-dashboard | a process pool; each job is a directory |
| OCR container polling a folder | OCRmyPDF as a library, on the pages that need it |
| torch | numpy: dehyphen 0.6 reads Flair's checkpoints and runs the LSTM itself |
| repository `pd3f-core` | merged into this repository |
| options `fast`, `experimental` | `scorer`: `none`, `flair`, `flair-fast`; what `experimental` switched on is the default |
| HTTP API `POST /`, `GET /update/<id>` | `/jobs` |

dehyphen stays a package of its own: it is useful without pd3f.

## Choosing the parser

Sample: 14 German statements on draft laws (10 digital, 4 scanned), 80 pages, CPU on macOS arm64.
Reference for line-final hyphens: `pdftotext -raw`, expected rendering by rule (a conjunction after the hyphen → `Ein- und`, uppercase or a digit on either side → `EU-Staaten`, else join).

| | 0.x: Parsr + pd3f-core | LiteParse + pd3f-core | LiteParse alone | Docling |
|---|---:|---:|---:|---:|
| line-final hyphens rendered wrong (of 376) | 9 | 7 | 7 | 7 |
| … of them compounds or suspended hyphens destroyed (of 7) | 0 | 0 | 7 | 6 |
| paragraphs split mid-sentence (estimate) | 11 | 3 | 50 | 14 |
| parsing, seconds per page | 1.9 (emulated amd64) | 0.01 | 0.01 | 5.0 |

"LiteParse + pd3f-core" fed pd3f-core through an adapter from LiteParse's output to Parsr's JSON.
The split estimate counts paragraphs that start lowercase.

- LiteParse loses nothing against Parsr on hyphens and parses two orders of magnitude faster.
- Docling and plain LiteParse join every hyphen. Compounds are rare (7 of 376), but joining them destroys information (`EUStaaten`, `Einund`).
- LiteParse's blocks are weak paragraphs: alone it splits paragraphs mid-sentence and merges others. It marks no headers or footers, and its 5 "tables" in the sample were letterheads or contact footers.
- One PDF has a broken ToUnicode map: LiteParse, pdftotext and Docling return `�` for 68 % of its characters, against 0 % in the other 13.
- Flair runs without torch: a numpy LSTM reading Flair's checkpoints gives the same perplexities as torch (relative difference ≤ 4·10⁻⁶) at the same speed. torch is 554 MB installed.

## Modules

```
pd3f/
  model.py    Document, Page, Block, Line, Word: boxes, fonts, text
  parse.py    LiteParse → model
  ocr.py      which pages need OCR, OCRmyPDF
  layout.py   running headers and footers, footnotes, paragraphs
  decide.py   decisions: layout, rules, document vocabulary, scorer, default; the decision log
  output.py   text, Markdown, CSV, the decision log
  cli.py      the command line tool
  web/        Flask app, one page of HTML, CSS and JavaScript
```

The model is pd3f's own; nothing after `parse.py` knows LiteParse.

## Pipeline

1. **Parse.** LiteParse, with its own OCR off, reads words with their boxes and fonts. Text items on one baseline become a line; touching boxes merge into one word. LiteParse's blocks are kept as hints. Lines outside every block become `chrome` blocks, candidates for headers and footers.
2. **OCR.** A page needs OCR when it has no text, or when more than a tenth of its glyphs map to no character (U+FFFD, private use, control or unassigned code points). OCRmyPDF renders those pages as images with its text on them and leaves the others as they are. It straightens, cleans and turns the pages upright first (see [Turning pages upright](#turning-pages-upright)). The output type is plain PDF, because PDF/A sends the untouched pages through Ghostscript, which drops the text of ligatures in some versions. The OCRed PDF is parsed again.
3. **Running headers and footers**, see [below](#running-headers-and-footers).
4. **Paragraphs.** See [below](#paragraphs-and-headings).
5. **Footnotes.** At the end of a page, the paragraphs below the page's text size (under 0.95 of it), or with a number smaller than the text after it, from the first one starting with a number; not after a paragraph ending with a colon. They go to the end of the text unless kept in place. On a page that does not end with footnotes, the paragraphs below the page's text size in its bottom fifth become that page's footer, such as a letterhead's address on the first page only. On a page ending with footnotes, such a line, for example a copyright notice, stays with the last footnote.
6. **Decisions**, see [below](#decisions).
7. **Output.** Text, Markdown with headings, lists and tables, a CSV per table, the OCRed PDF, the decision log.

## Running headers and footers

- **Candidates:** lines in the top or bottom fifth of a page, and lines outside LiteParse's blocks.
- **Key:** each line's words without case, accents or punctuation, numbers as `#`. `Berlin, 2. März 2016` and OCR's `Berlin, 2. Marz 2016` both become `berlin # marz #`.
- **Copies:** candidates on other pages at the same height, within the taller line's height. Their keys must be equal or, if they contain letters, alike to 0.9 by `difflib.SequenceMatcher`. Copies of copies belong to the same group.
- **Numbers:** each number of a copy occurs in another copy as it is, or counted up with the page as page numbers are. A copy with a number none of the others has, under a key other than the group's most common one, is another line: `Recht und Informatik 6.V.` stays in the text. Up to a quarter of the remaining copies may have such a number, where OCR misread it. Beyond that, the group is no running line: footnotes alike (`5 Ebd., S. 3.` and `9 Ebd., S. 7.`) and citations sharing most of their words keep their place.
- **Repetition:** on half of the pages, at least two and at most three.
- **Page numbers:** groups whose key reads like `#` (`- 3 -`), `# #` (`3/9`), `seite # von #` or `s #`. They are removed unless kept in place.
- **The copy that stays** in `separate` mode is the text more than half of the copies share. Otherwise the scorer picks it, and without a scorer the first copy stays. Copies that read the same need no decision.

Compared with exact keys and a strict number check, on 109 scanned and 14 benchmark PDFs plus the test PDFs, 229 more lines are recognized. They are OCR variants of letterheads, dates and addresses. 2 fewer are recognized: a name at the foot of two pages of one PDF.
In the benchmark, this rejoined a paragraph split by a letterhead and brought the paragraph count from 764 to 758.
In noisy scans, a copy OCR misread beyond that stays in the text, for example a letterhead whose phone number came out four different ways.

## Paragraphs and headings

- **Text size and line spacing** come from the document: the font size of most characters, and the median distance from the bottom of one line to the next, in font sizes. A page keeps them unless under a tenth of its characters or lines are within 5 % of them. Then the page's median holds, as on a document bound into another or a page set wider.
- **OCR jitter:** OCR layers size each line by its height. A document whose two most common sizes cover under 90 % of its characters jitters.
- **A table of contents entry** ends its paragraph.
- **Within a LiteParse block** a paragraph ends at spacing outside 0.6 to 1.4 times the page's, at a sentence that ends early before an uppercase start, and at a change to or from bold. Without jitter, any spacing above 1.15 times the page's counts too.
- **Across blocks** a line continues the paragraph when the spacing stays under 1.5 times the page's, the line does not start far left of the block before, and the line before does not end a sentence. Bold must not change, and without jitter the line before must not be larger. The line must also either start lowercase but not with a list mark such as `a)` (and not after a short line ending with a comma, a salutation), or follow a full line at the same indent.
- **Headings:** a paragraph of at most two lines, not ending with `.`, `,` or `;`, that is bold or larger than the page's text size: from 1.05 times without jitter, from 1.3 with it. On 109 scans, 0.9 % of the lines of six words or more in the middle of a page are 1.3 times their page's text size or more, 12 % more than 1.05.
- **LiteParse's kinds:** a paragraph starting in a list item is a list item. A table keeps its kind while the paragraph stays in it; a heading while the paragraph stays in headings, or when it is set apart as above.

On 109 scanned and 150 digital PDFs, the page's spacing instead of the document's brought the paragraphs from 13883 to 13226. Those starting lowercase fell from 2071 to 1686, and the words split by a hyphen across two paragraphs from 283 to 157.
A page with mixed spacing, where most lines are set closer than the body, splits the body's paragraphs more often. Text in a slightly smaller font at the foot of a page, such as a quote, can be taken for that page's footer.

## Turning pages upright

Tesseract's orientation detection (OSD) with OCRmyPDF's default threshold of 14 left an upside-down benchmark page unturned (confidence 11.3).
Measured on pages rendered at several resolutions:

- At 150 and 300 dpi the detected orientation was right from confidence 5 on, apart from one landscape page.
- At about 100 dpi, OSD reads upright pages as upside down. With threshold 5 it turned 38 of 114 upright pages, with 10 it turned 2, and from 12 on none.
- 4 of 545 scans in the corpus are below 150 dpi.

pd3f turns a page from confidence 5 when its OSD preview has 150 dpi or more, and from 14 below. The preview is the image OCRmyPDF renders at `min(300, the page's dpi)`.
An upside-down 96-ppi page with confidence 9.3 therefore stays as it is.

## Decisions

| decision | options | settled before the scorer by |
|---|---|---|
| hyphen at the end of a line or page | join; keep the hyphen; hyphen and space (`Ein- und`) | layout: within a page, a line that ends early keeps the hyphen and the new line; rule: a dash glues; vocabulary: the spelling the document uses elsewhere; rule: a conjunction after it; rule: an uppercase start, or an acronym or digit before it, keeps the hyphen, unless both words are in capitals |
| line end without hyphen | new line; continue | rule: a heading is one line; layout: the next word would have fit; layout: a line of up to five words in a paragraph of three or more lines, at least half of which end early, as in an address; rule: `Tel.: …` fields stay on their lines; rule: a line of more than five words or ending in punctuation continues |
| paragraph cut by a page break | keep apart; join | layout: the last line ends short; rule: a sentence end before an uppercase start keeps apart; rule: a full line that does not end a sentence goes on, unless the next one starts with a list mark |
| copy of a running line | which copy stays | rule: the text more than half of the copies share |

What remains goes to the scorer, an object with `score(texts) -> list[float]` such as dehyphen's `FlairScorer`, lower being more plausible.
Without a scorer (`none`) the default holds: join, continue, keep apart, the first copy.
A paragraph cut by a page break is decided only when headers and footers are out of the text, footnotes go to the end and page breaks are not kept; otherwise the parts stay apart.
The margin of a scorer's decision is `(second - best) / best`, between the best scores of two different options.
A decision is uncertain when the default made it, or when the scorer's margin is below 0.05. That threshold is provisional: there are no hand-checked decisions to set it from.

Benchmark, same sample as above, with OCR skipped:

| | 0.x | `none` | `flair-fast` | `flair` |
|---|---:|---:|---:|---:|
| line-final hyphens rendered wrong (of 376) | 9 | 0 | 0 | 1 |
| paragraphs | 510 | 756 | 756 | 756 |
| … starting lowercase: list items, after a salutation, other | 17, 6, 17 | 35, 9, 17 | 35, 9, 17 | 35, 9, 17 |
| seconds per page after parsing | 2.1 | 0.02 | 0.65 | 4.0 |

- The reference pairs one more line end: the page number `-1-` before a letterhead line, which is no hyphen. It is left out.
- `flair` keeps the hyphen in `Nichtweiter-geltung`. The document spells `Weitergeltung` but never the compound, so no rule settles it.
- Of the 17 other lowercase starts with `none`, 3 split a sentence of the body, 2 of them in the PDF with the broken ToUnicode map. The rest are OCR noise and letterhead lines.
- 0.x splits fewer paragraphs at list items such as `a)`.

With `none`, the 1845 decisions in the sample were settled by rule (1073), vocabulary (225), layout (72) and default (475). The defaults joined 244 hyphens (3 of them at a page break), continued 224 line ends, kept 1 page break apart and kept 6 first copies.

The default scorer is `none`. The rules and the vocabulary leave nothing for a scorer to improve on the hyphens of the sample. The Flair scorers stay for the line ends of short lines that neither the layout nor a rule settles, such as some addresses and lists; `none` continues them.

Two layers the earlier plan considered are not built, since no hyphen errors remain for them to fix: a word list per language, and a scorer on a small LLM.

## Web app

- Flask in one gunicorn worker. Extractions run in a `ProcessPoolExecutor` with `PD3F_WORKERS` processes.
- Each job is a directory with `input.pdf`, `status.json` and the outputs. `status.json` is replaced in one step, so a reader never sees half of it.
- At startup, jobs still queued or running are marked failed, with a message to upload again. Nothing retries silently.
- A worker process that dies, killed for lack of memory say, fails its job and the queued ones; the next upload gets a new pool.
- Jobs older than `PD3F_JOB_TTL` hours are deleted when a new one is created; each job can also be deleted on its own.
- One page of plain HTML, CSS and JavaScript, with no framework and no build step. The language defaults to the first of the browser's languages that pd3f offers. Progress is announced in an `aria-live` region. The text stands beside the PDF, and uncertain decisions are marked, overlapping ones in one mark; each mark is focusable and shows the options.
- Playwright tests check the page with axe-core in light and dark mode.
- No authentication: meant for localhost or behind a reverse proxy.

## Release

1. dehyphen 0.6.0, with the numpy runtime and without torch.
2. pd3f 1.0.0 on PyPI, where the name carried pd3f-core until then (last 0.5.0). It gets a fresh lock file once dehyphen 0.6.0 is published.
3. The Docker image `pd3f/pd3f` 1.0.0 (0.x reached 0.6.0), built for amd64 and arm64 by `push_image.sh`.
4. The repository `pd3f-core` archived; it keeps its history.

## Open questions

- A hand-checked set of line end, page break and copy decisions, to set the uncertainty threshold and compare the scorers beyond hyphens.
- Languages beyond the five: each needs a Flair model and Tesseract data.
