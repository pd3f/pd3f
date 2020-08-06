import logging

from pdddf import extract


def do_the_job(filename, tables, experimental, lang):
    logging.basicConfig(filename=f"/uploads/{filename}.log", level=logging.INFO)
    text, tables = extract(
        "/uploads/" + filename,
        tables=tables,
        experimental=experimental,
        force_gpu=False,
        lang=lang,
        parsr_location="parsr:3001",
    )
    return text, tables
