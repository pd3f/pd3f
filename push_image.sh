#!/usr/bin/env bash

docker build -t pd3f/pd3f:latest -t pd3f/pd3f:0.2.0 .
docker push pd3f/pd3f
