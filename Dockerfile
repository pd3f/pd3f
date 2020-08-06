FROM python:3.8-slim

RUN pip install poetry

# leverage Docker cache
COPY ./poetry.lock /app/poetry.lock
COPY ./pyproject.toml /app/pyproject.toml

WORKDIR /app

COPY ./pdddf /pdddf

RUN poetry config virtualenvs.create false
RUN poetry install --no-dev

COPY ./pdddf-service /app

RUN mkdir /uploads

ENV FLASK_APP=/app/app.py
