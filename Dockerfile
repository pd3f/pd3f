FROM python:3.13-slim

# Tesseract with the languages pd3f knows (tesseract-ocr brings eng and osd) and unpaper for
# OCRmyPDF; without Ghostscript, its optimizer warns about each JPEG it leaves as it is
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita tesseract-ocr-spa \
        ghostscript unpaper \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY pd3f pd3f
RUN pip install --no-cache-dir ".[web]"

# jobs and the scorers' models live in volumes, so they survive restarts
ENV PD3F_JOBS=/data/jobs FLAIR_CACHE_ROOT=/data/flair
VOLUME /data
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "pd3f.web:create_app()"]
