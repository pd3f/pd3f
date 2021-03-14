#!/usr/bin/env bash

docker build -t pd3f/pd3f:latest -t pd3f/pd3f:0.3.2 .
docker push pd3f/pd3f --all-tags
