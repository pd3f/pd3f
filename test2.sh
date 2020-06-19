#!/usr/bin/env bash

curl --header "Content-Type: application/json" \
    --request POST \
    --data '{"texts":["Ich lebe in Berlin", "Ich lebe in Auto"]}' \
    http://localhost:5000/score_async
