import logging

import flair
from rq import get_current_job

from pdddf import extract

flair.cache_root = "/root/.cache/flair"


def do_the_job(filename, tables, experimental, lang):
    job_id = get_current_job().id

    logging.basicConfig(filename=f"/uploads/{job_id}.log", level=logging.INFO)

    text, tables = extract(
        "/uploads/" + filename,
        tables=tables,
        experimental=experimental,
        force_gpu=False,
        lang=lang,
        parsr_location="parsr:3001",
    )
    return text, tables
