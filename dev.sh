#!/usr/bin/env bash

# docker run --rm -p 6379:6379 --name some-redis redis

export FLASK_ENV=development
rq worker &
flask run --host=0.0.0.0
