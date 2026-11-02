#!/usr/bin/env bash
# Capture the G6 product reel (slides + live E1–E6 UI) with narration to MP4.
# Delegates to assemble-demo-reel.sh. Legacy silent-only path: DEMO_SILENT=1.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${DEMO_SILENT:-0}" == "1" ]]; then
  OUT_DIR="$ROOT/docs/evidence/demo-recording"
  mkdir -p "$OUT_DIR"
  export PLAYWRIGHT_BASE_URL="${PLAYWRIGHT_BASE_URL:-http://localhost:5729}"
  echo "==> Legacy silent capture against $PLAYWRIGHT_BASE_URL"
  (
    cd apps/web
    npx playwright test auth.setup.ts --project=setup
    npx playwright test demo-silent.spec.ts --project=chromium-desktop-light
  )
  WEBM_SRC="$(find apps/web/test-results -name '*.webm' -type f -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1 || true)"
  if [[ -z "${WEBM_SRC}" ]]; then
    echo "No Playwright webm found under apps/web/test-results" >&2
    exit 1
  fi
  WEBM="$OUT_DIR/sahyog-demo-6min.webm"
  MP4="$OUT_DIR/sahyog-demo-6min.mp4"
  cp "$WEBM_SRC" "$WEBM"
  ffmpeg -y -i "$WEBM" -c:v libx264 -pix_fmt yuv420p -movflags +faststart -an "$MP4"
  ls -lh "$MP4"
  echo "Canonical recording: docs/evidence/demo-recording/sahyog-demo-6min.mp4"
  exit 0
fi

exec "$ROOT/scripts/assemble-demo-reel.sh"
