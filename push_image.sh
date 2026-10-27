#!/usr/bin/env bash
# Build the pd3f image for amd64 and arm64 and push it, tagged with the version from pyproject.toml
set -euo pipefail

version=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
docker buildx build --platform linux/amd64,linux/arm64 --push \
    -t pd3f/pd3f:latest -t "pd3f/pd3f:$version" -t "pd3f/pd3f:${version%.*}" .
