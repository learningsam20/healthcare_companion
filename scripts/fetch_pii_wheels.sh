#!/usr/bin/env bash
# Prefetch manylinux aarch64 CPU torch + gliner wheels for docker/api.Dockerfile (G-28).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$ROOT/data/wheels}"
mkdir -p "$DEST"
python3 -m pip download -d "$DEST" \
  --platform manylinux2014_aarch64 --python-version 312 --only-binary=:all: \
  --index-url https://download.pytorch.org/whl/cpu \
  --extra-index-url https://pypi.org/simple \
  'torch>=2.2,<3'
python3 -m pip download -d "$DEST" \
  --platform manylinux2014_aarch64 --python-version 312 --only-binary=:all: \
  'gliner>=0.2,<1'
echo "Wheels in $DEST: $(ls "$DEST" | wc -l | tr -d ' ') files"
ls "$DEST" | grep -E 'torch-|gliner-|nvidia' || true
