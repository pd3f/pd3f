#!/usr/bin/env bash

docker build -t pd3f/pd3f-ocr:latest -t pd3f/pd3f-ocr:0.1.0 .
docker push pd3f/pd3f-ocr
