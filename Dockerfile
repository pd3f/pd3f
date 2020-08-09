FROM python:3.8-slim

RUN apt-get update && apt-get upgrade -y

RUN pip install poetry

# leverage Docker cache
COPY ./poetry.lock /app/poetry.lock
COPY ./pyproject.toml /app/pyproject.toml

COPY ./pdddf-service /app
RUN mkdir /uploads

# temp fix until pdddf is released
COPY ./pdddf /pdddf

WORKDIR /app
RUN poetry config virtualenvs.create false

# poet
# RUN poetry install --no-dev -vv
# RUN poetry export -f requirements.txt > requirements.txt
# RUN pip install -r requirements.txt

RUN /bin/bash -c 'poetry install --no-dev --no-interaction --no-root'



ENV FLASK_APP=/app/app.py
