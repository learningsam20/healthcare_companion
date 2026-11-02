#!/usr/bin/env bash
# M/L evidence run. capacity_accepted=true only when --host-profile is M or L and SLOs pass.
# On a laptop, prefer scripts/load_test_smoke.sh (P host); do not claim M/L capacity from P/S.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
HOST_PROFILE="${LOAD_TEST_HOST_PROFILE:-M}"
PROFILE="${LOAD_TEST_PROFILE:-r3}"
DURATION="${LOAD_TEST_DURATION:-300s}"
COHORT="${LOAD_TEST_COHORT_SIZE:-20}"
REPORT="$ROOT/docs/evidence/load_test_${PROFILE}_${HOST_PROFILE}_$STAMP.json"

case "$HOST_PROFILE" in
  M | L) ;;
  *)
    echo "warning: host-profile=$HOST_PROFILE cannot set capacity_accepted=true" >&2
    ;;
esac

"$ROOT/scripts/seed-users.sh" --load-test "$COHORT" >/tmp/sahyog-loadtest-seed.log 2>&1 || true

"$ROOT/scripts/load_test.sh" \
  --profile "$PROFILE" \
  --host-profile "$HOST_PROFILE" \
  --duration "$DURATION" \
  --cohort-size "$COHORT" \
  --burst 4 \
  --summary "$REPORT" \
  "$@"

printf 'Evidence report: %s\n' "$REPORT"
python3 - "$REPORT" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(
    f"status={r.get('status')} capacity_accepted={r.get('capacity_accepted')} "
    f"req/h={r.get('actual_requests_per_hour')} p95={r.get('latency_ms', {}).get('p95')} "
    f"note={r.get('capacity_acceptance_note')}"
)
PY

