#!/usr/bin/env bash

docker build -t pd3f/pd3f:latest -t pd3f/pd3f:0.5.0 -t pd3f/pd3f:0.5 .
docker push pd3f/pd3f --all-tags
