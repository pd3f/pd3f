#!/usr/bin/env bash
# Build the pd3f and OCR images for amd64 and arm64 and push them, tagged with the version from pyproject.toml
set -euo pipefail

version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)

for image in pd3f pd3f-ocr; do
    context=.
    [ "$image" = pd3f-ocr ] && context=./pd3f-ocr
    docker buildx build --platform linux/amd64,linux/arm64 --push \
        -t "pd3f/$image:latest" -t "pd3f/$image:$version" -t "pd3f/$image:${version%.*}" "$context"
done
