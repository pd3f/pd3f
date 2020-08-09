import logging
import shutil
from shutil import Error
import time
from pathlib import Path

import flair
from rq import get_current_job

from pdddf import extract

flair.cache_root = "/root/.cache/flair"


def params_to_lang_model(lang, fast_mode):
    """
    https://github.com/flairNLP/flair/blob/master/resources/docs/embeddings/FLAIR_EMBEDDINGS.md
    multi-v0-fast: English, German, French, Italian, Dutch, Polish
    """

    flair_lang = lang
    if fast_mode:
        # for en and es fast exits
        flair_lang += "-fast"
    if lang in ("de", "fr") and fast_mode:
        # no fast for model for de / fr
        flair_lang = "multi-v0-fast"

    tesseract_lang = None

    if lang == "de":
        tesseract_lang = "deu"
    elif lang == "en":
        tesseract_lang = "eng"
    elif lang == "es":
        tesseract_lang = "spa"
    elif lang == "fr":
        tesseract_lang = "fra"

    return flair_lang, tesseract_lang


def do_ocr_via_folder(filenamname, lang):
    """This is blocking the worker, but who cares. The OCR will take all CPUs anyhow.
    """

    logging.info("setting up ocr")
    fn_p = Path("/uploads/" + filenamname)
    new_p = Path("/to-ocr/" + fn_p.stem + f".{lang}" + fn_p.suffix)
    finished_p_success = new_p.with_suffix(".pdf.done")
    finished_p_error = new_p.with_suffix(".pdf.failed")
    finished_p_log = new_p.with_suffix(".pdf.log")
    new_p.parent.mkdir(exist_ok=True)
    shutil.copy2(fn_p, new_p)

    while True:
        # file get's deleted when processing finished
        if not new_p.is_file():
            if finished_p_success.is_file():
                # success
                shutil.copy2(finished_p_success, fn_p)
                logging.info("ocr finished successfully")
                return True
            if finished_p_error.is_file():
                Path()
                finished_p_error.unlink()
                logging.info(finished_p_log.read_text())
                logging.info("ocr failed, aborting. sorry :/")
                return False

        time.sleep(1)


def do_the_job(filename, tables, experimental, flair_lang, tess_lang, lang):
    job = get_current_job()
    job_id = job.id

    logging.basicConfig(filename=f"/uploads/{job_id}.log", level=logging.INFO)

    if tess_lang is not None:
        if not do_ocr_via_folder(filename, tess_lang):
            raise ValueError('could not OCR pdf')

    text, tables = extract(
        "/uploads/" + filename,
        tables=tables,
        experimental=experimental,
        force_gpu=False,
        lang=flair_lang,
        parsr_location="parsr:3001",
    )
    return text, tables
