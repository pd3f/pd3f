FROM python:3.13-slim

RUN pip install --no-cache-dir "poetry>=2.5,<3"

WORKDIR /app
COPY poetry.lock pyproject.toml /app/
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root --no-interaction \
    && rm -rf /root/.cache/pypoetry

COPY pd3f /app/
RUN mkdir /uploads

ENV FLASK_APP=/app/app.py
# inside the `cache` volume, so models survive container restarts
ENV FLAIR_CACHE_ROOT=/root/.cache/flair
