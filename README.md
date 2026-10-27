# pd3f

pd3f extracts the continuous text of a PDF.
It rebuilds paragraphs from lines, rejoins words hyphenated at the end of a line, moves running headers and footers out of the text, collects footnotes, and runs OCR on pages without usable text.
It was made for German letters and official documents and also handles English, Spanish, French and Italian.

Each line end inside a paragraph, each paragraph cut by a page break and each choice between differing copies of a running header or footer is recorded with what settled it.
The uncertain ones can be checked in the web app or in the log.

pd3f is a Python library, a command line tool and a small web app.

## What it does

- **Paragraphs.** Lines are joined into paragraphs by their spacing, their fonts, where they end and the text blocks the parser finds. Headings, list items and tables stay apart.
- **Hyphens.** A hyphen at the end of a line is removed (`Rechts-` / `staat` → `Rechtsstaat`). It stays where the next line starts with a conjunction or uppercase (unless both words are in capitals), or where an acronym or a digit precedes it (`EU-Staaten`, `Bundes- und Landesrecht`). If the document uses one spelling elsewhere, that spelling wins. Within a page, a line that ends early keeps its hyphen and its line break.
- **Headers and footers.** Lines repeated at the top or bottom of the pages are moved out of the running text (`separate`, one copy at the start and the end, or with `--page-breaks` on the page of that copy), removed (`drop`) or left where they are (`keep`). Small print at the foot of a single page, such as a letterhead's address, counts as that page's footer. Page numbers are removed unless kept in place.
- **Footnotes** go to the end of the text, or stay on their page.
- **OCR.** Pages without a text layer, or with more than a tenth of their glyphs mapped to no character, go through [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) and Tesseract. Pages are straightened and turned upright first; in scans below 150 dpi only where Tesseract is sure of the orientation.
- **Output.** Plain text, Markdown with headings, lists and tables, each table as CSV, the OCRed PDF, and the decision log as JSON.

PDFs are parsed with [LiteParse](https://github.com/run-llama/liteparse) (PDFium).

## Installation

```bash
pip install pd3f          # library and command line tool
pip install "pd3f[web]"   # with the web app
```

pd3f needs Python 3.11 or later.
OCR also needs Tesseract with the data of the document's language and unpaper on the system, e.g. `apt install tesseract-ocr tesseract-ocr-deu unpaper`. Without Ghostscript, OCRmyPDF warns about each JPEG image it leaves as it is; the output is the same.
PDFs that have text need none of them.

The Docker image contains all of this and runs the web app:

```bash
docker run -p 127.0.0.1:8000:8000 -v pd3f:/data pd3f/pd3f
```

Then open <http://localhost:8000>.
Its Tesseract has the data for de, en, es, fr and it; for OCR in another language, build an image on it that adds that language's package, such as `tesseract-ocr-rus`.
The web app has no authentication; keep it on localhost or put a reverse proxy with access control in front.

## Command line

```bash
pd3f letter.pdf > letter.txt
pd3f letter.pdf --scorer flair --out letter/   # text.txt, text.md, decisions.json; tables/*.csv and ocr.pdf if any
```

| option | default | |
|---|---|---|
| `--lang` | `de` | language of the text: `de`, `en`, `es`, `fr`, `it`; other ISO 639-1 codes need `--ocr-lang` for OCR and work only with `--scorer none` |
| `--scorer` | `none` | what decides uncertain cases, see [Scorers](#scorers) |
| `--headers-footers` | `separate` | `separate`, `drop` or `keep`; with `keep`, paragraphs cut by a page break stay apart |
| `--footnotes-in-place` | off | keep footnotes at the end of their page; a paragraph cut by a page break stays apart there |
| `--page-breaks` | off | keep each page's text apart and end it with a form feed; paragraphs and footnotes stay on their page |
| `--ocr` | `auto` | `auto`: pages without usable text; `force`: every page; `skip`: none |
| `--ocr-lang` | | Tesseract language, such as `rus` or `deu+eng` |
| `--out` | | write the outputs into this new or empty directory instead of the text to stdout |

## Python

```python
from pd3f import extract, output

result = extract("letter.pdf", lang="de", scorer="flair")
text = output.text(result)
markdown = output.text(result, markdown=True)
tables = output.tables(result)  # one CSV string per table
log = output.decisions(result)  # one dict per decision, with offsets into `text`
```

`extract` takes the options of the command line as keyword arguments (`headers_footers`, `footnotes_last=False` for `--footnotes-in-place`, `page_breaks`, `ocr`, `ocr_lang`, `ocr_output`) and a `progress(step, done, total)` callback.
A broken PDF or an unsuitable option raises one of `pd3f.ERRORS`.

## Web app

Upload one or more PDFs, follow a job's steps, read the text next to the PDF with the uncertain decisions marked, copy it or download the outputs.
Jobs are directories on the server; those older than `PD3F_JOB_TTL` are deleted when the next one is uploaded. The browser remembers its own jobs.

Without Docker:

```bash
PD3F_JOBS=/var/lib/pd3f gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 8 "pd3f.web:create_app()"
```

Run a single gunicorn worker and scale with `PD3F_WORKERS`: each worker would start its own extraction processes and, on start, mark the jobs of the others as interrupted.

| variable | default | |
|---|---|---|
| `PD3F_JOBS` | `jobs` (Docker: `/data/jobs`) | directory of the jobs |
| `PD3F_WORKERS` | `2` | PDFs extracted at the same time |
| `PD3F_JOB_TTL` | `24` | hours a job is kept |
| `PD3F_MAX_MB` | `100` | largest upload in MB |
| `FLAIR_CACHE_ROOT` | `~/.flair` (Docker: `/data/flair`) | where the scorers' models are downloaded to |

### HTTP API

```bash
curl -F pdf=@letter.pdf -F lang=de http://localhost:8000/jobs
# {"id": "…", "url": "/jobs/…"}
curl http://localhost:8000/jobs/<id>              # until "state" is "done" or "failed"
curl http://localhost:8000/jobs/<id>/text.txt
```

| route | |
|---|---|
| `POST /jobs` | multipart form: `pdf` and the options `lang` (`de`, `en`, `es`, `fr` or `it`), `scorer`, `headers_footers`, `ocr`, `ocr_lang`; `footnotes_in_place` and `page_breaks` switch on when present. Answers 202. |
| `GET /jobs/<id>` | status: `state` (`queued`, `running`, `done`, `failed`); while running `step` with `done` of `total` pages where they are known; when done `pages`, `ocr_pages`, `tables`, `decisions`, `uncertain`; when failed `error` |
| `GET /jobs/<id>/<file>` | `input.pdf`, `text.txt`, `text.md`, `decisions.json`, `ocr.pdf`, `tables/<n>.csv`; with `?download=1` as an attachment |
| `DELETE /jobs/<id>` | deletes the job and its files; 409 while it runs |

Errors come as `{"error": "…"}` with their HTTP status, such as 400, 404, 409 or 413.

## Scorers

Most decisions are settled by the layout, by fixed rules, or by the spelling the document uses elsewhere.
What remains goes to the scorer:

| scorer | decides by | |
|---|---|---|
| `none` | fixed defaults: join the hyphen, continue the line, keep paragraphs on different pages apart, keep the first copy | instant |
| `flair` | [Flair](https://github.com/flairNLP/flair)'s forward and backward character language models for the language, via [dehyphen](https://github.com/pd3f/dehyphen), run with numpy | seconds per page; downloads its two models on first use, 73 MB each for German |
| `flair-fast` | Flair's smaller models; a multilingual pair for German, French and Italian | several times faster; 21 MB per model for the multilingual pair |

## Decision log

`decisions.json` lists every decision in the order it was made:

```json
{"kind": "line", "page": 1, "options": ["newline", "space"],
 "texts": ["Abt. Steuerrecht und\nRechnungslegung", "Abt. Steuerrecht und Rechnungslegung"],
 "chosen": 1, "layer": "default", "margin": null, "start": 162, "end": 181, "uncertain": true}
```

- `kind`: `line` (a line end inside a paragraph), `page` (a paragraph cut by a page break) or `copy` (which copy of a running header or footer stays, where the copies differ).
- `texts`: each option as it would read; `chosen` is an index into `options` and `texts`.
- `layer`: what settled it: `layout`, `rule`, `vocabulary`, `scorer` or `default`.
- `margin`: for the scorer, how far the best option is ahead of the second, relative to its score.
- `start`, `end`: the span in `text.txt`, in Unicode code points like Python's string indices, from the word before the decision to the word after it, if that is in the same paragraph; a copy's decision sits at the end of the copy that stays.
- `uncertain`: settled by `default`, or by the scorer with a margin below the threshold in [`pd3f/output.py`](pd3f/output.py).

## How it works

1. LiteParse reads words with their boxes and fonts; lines outside its text blocks are candidates for headers and footers.
2. Pages without usable text are OCRed, and the OCRed PDF is read again.
3. Lines that repeat on enough pages, with numbers that stay the same or count with the page, become running headers and footers.
4. Lines become paragraphs, headings, list items and tables.
5. The paragraphs at the end of a page in a smaller font, from the first one starting with a number, become footnotes.
6. Each line end, each page break a paragraph may run on across and each choice between differing copies is decided and logged; the text, Markdown and CSV are written from the decided paragraphs.

[`docs/design.md`](docs/design.md) records the design of version 1.0 and the measurements behind it.

## Coming from 0.x

pd3f 1.0 replaces the Docker Compose setup of Parsr, Redis, an RQ worker and an OCR container with one image, and merges the former `pd3f-core` package into this repository.
The HTTP API moved from `POST /` and `GET /update/<id>` to `/jobs`; the option `fast` became `scorer=flair-fast`, and what `experimental` switched on is the default.

## Development

```bash
poetry install
poetry run playwright install chromium
poetry run pytest --cov
poetry run ruff check . && poetry run ruff format --check .
```

`tests/data/` holds PDFs with the text pd3f extracts from them, checked by hand.
The OCR test runs only where Tesseract with German and unpaper are installed, as in the Docker image.
The Flair test downloads the `flair-fast` models on its first run.
The browser test checks the web app with axe-core in light and dark mode.

To release, bump `version` in `pyproject.toml`, then run `poetry publish --build` and `./push_image.sh`, which builds the image for amd64 and arm64 and pushes it to Docker Hub.

## License

Affero General Public License 3.0

![](imgs/logo.jpg)
