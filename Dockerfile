FROM python:3.8-slim

RUN apt-get update && apt-get upgrade -y
RUN pip install poetry

COPY ./poetry.lock ./pyproject.toml ./pd3f /app/

RUN mkdir /uploads

WORKDIR /app
RUN poetry config virtualenvs.create false
# poetry does not leverage Docker caching right now
RUN poetry install --no-dev --no-interaction --no-root

ENV FLASK_APP=/app/app.py
