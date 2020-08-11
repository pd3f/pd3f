#!/usr/bin/env bash

docker-compose -f docker-compose.yml -f docker-compose.dev.yml up $1
