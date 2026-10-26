#!/usr/bin/env bash
# Build and push the pd3f and OCR images, tagged with the version from pyproject.toml
set -euo pipefail

version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)

for image in pd3f pd3f-ocr; do
    context=.
    [ "$image" = pd3f-ocr ] && context=./pd3f-ocr
    docker build --platform linux/amd64 -t "pd3f/$image:latest" -t "pd3f/$image:$version" -t "pd3f/$image:${version%.*}" "$context"
    docker push "pd3f/$image" --all-tags
done
