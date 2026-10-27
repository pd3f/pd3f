"""pd3f input.pdf: the text of a PDF on stdout, or text, Markdown, tables and decisions in a directory."""

import argparse
import json
import logging
import sys
from pathlib import Path

from . import ERRORS, HEADERS_FOOTERS, OCR_MODES, SCORERS, extract, output


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pd3f", description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--lang",
        default="de",
        help="ISO 639-1 code of the text's language (default: de)",
    )
    parser.add_argument("--scorer", default="none", choices=SCORERS)
    parser.add_argument(
        "--headers-footers", default="separate", choices=HEADERS_FOOTERS
    )
    parser.add_argument(
        "--footnotes-in-place",
        action="store_true",
        help="keep footnotes at the end of their page",
    )
    parser.add_argument(
        "--page-breaks",
        action="store_true",
        help="keep each page's text apart and end it with a form feed",
    )
    parser.add_argument(
        "--ocr",
        default="auto",
        choices=OCR_MODES,
        help="auto: OCR the pages without usable text (default)",
    )
    parser.add_argument(
        "--ocr-lang",
        help="Tesseract language, such as rus or deu+eng; needed for languages other than "
        "de, en, es, fr, it",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="write text.txt, text.md, decisions.json, tables/*.csv and the OCRed ocr.pdf "
        "into this new or empty directory",
    )
    args = parser.parse_args(argv)
    # OCRmyPDF warns about the resolution of every page
    logging.getLogger("ocrmypdf").setLevel(logging.ERROR)
    if args.out is not None:
        # outputs of an earlier run, such as more tables, would mix with this one's
        if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
            parser.error(f"--out {args.out} must be a new or empty directory")
        args.out.mkdir(parents=True, exist_ok=True)

    try:
        result = extract(
            args.pdf,
            args.lang,
            args.scorer,
            args.headers_footers,
            not args.footnotes_in_place,
            args.page_breaks,
            args.ocr,
            args.ocr_lang,
            args.out / "ocr.pdf" if args.out else None,
        )
    except ERRORS as e:
        sys.exit(f"pd3f: {e}")
    if result.ocr_pages:
        pages = ", ".join(map(str, result.ocr_pages))
        print(f"pd3f: OCR on pages {pages}", file=sys.stderr)

    text = output.text(result)
    if args.out is None:
        sys.stdout.write(text)
        return
    (args.out / "text.txt").write_text(text)
    (args.out / "text.md").write_text(output.text(result, markdown=True))
    log = json.dumps(output.decisions(result), ensure_ascii=False, indent=1)
    (args.out / "decisions.json").write_text(log + "\n")
    for i, table in enumerate(output.tables(result), 1):
        (args.out / "tables").mkdir(exist_ok=True)
        (args.out / "tables" / f"{i}.csv").write_text(table)
