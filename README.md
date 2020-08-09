# `pdddf-service`

*Experimental, use with care.*

Web-based GUI and micro service (API) for [pdddf](https://github.com/jfilter/pdddf).

`pdddf-service` is a self-hosted PDF processing pipeline to reconstruct text from PDFs. It can OCR PDFs witch [ocrmypdf](https://github.com/jbarlow83/OCRmyPDF) (tesseract) and extract tables with [camelot](https://github.com/camelot-dev/camelot) and [tabula](https://github.com/tabulapdf/tabula). It's build upon [parsr](https://github.com/axa-group/Parsr).

The underlying Python package [pdddf](https://github.com/jfilter/pdddf) tries to reconstruct the original text of PDFs by removing hyphens and new lines based on machine learning.

You can find a demo at [demo.ddd.jetzt](https://demo.ddd.jetzt).

## Installation

You need to setup [Docker](https://docs.docker.com/get-docker/).

You need the `docker-compose.yml` file of this repo. You can download it separately or just `git clone https://github.com/jfilter/pdddf-service`.

You need to have ~4 GB of space to store all the software / data to run this.


## Usage: GUI

You need the `docker-compose.yml` and then run

```bash
docker-compose up
```

This will download the Docker images and will take a while. After it's finished access the Web-based GUI at <http://localhost:1616>.

After uploading a PDF you will get redirect to a web page.

## Usage: API

```python

```

### Scaling

You can also run more worker with this:


```bash
docker-compose up --scale worker=3
```

To increase the frontend threads, change this line in `docker-compose.yml`:

```yml
command: gunicorn app:app --workers=5 --bind=0.0.0.0:5000
```

### House Keeping

You will see tghree folders:

- `pdddf-data-uploads`: input & output files
- `pdddf-data-cache`: storing data so you don't have to download model files over and over again
- `pdddf-data-to-ocr`: temporary location for PDFs to get OCRd. Files get deleted but logs get kept.

Results are kept for 24 hours per default. But no files get deleted automatically (only the results in the queue (e.g. the extracted text)).

Run this command from time to time to schedule jobs in order to delete files in `pdddf-data-uploads` and `pdddf-data-to-ocr`.

```bash
docker-compose run --rm worker rqscheduler --host redis --burst
```

## License

GPLv3