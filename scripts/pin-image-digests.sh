#!/usr/bin/env bash
# Resolve Compose image tags to digests for G-27 evidence (does not rewrite compose by default).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/docs/evidence/image-digests-$(date -u +%Y%m%dT%H%M%SZ).txt}"
cd "$ROOT"
{
  echo "# Image digests captured $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Source: docker compose images / docker inspect"
  echo
  docker compose --profile minimal --profile core --profile full config --images 2>/dev/null | sort -u | while read -r image; do
    [[ -z "$image" ]] && continue
    digest="$(docker image inspect "$image" --format '{{index .RepoDigests 0}}' 2>/dev/null || true)"
    if [[ -z "$digest" || "$digest" == "<no value>" ]]; then
      echo "$image  (digest unavailable — pull first)"
    else
      echo "$image  $digest"
    fi
  done
} | tee "$OUT"
printf 'Wrote %s\n' "$OUT"
