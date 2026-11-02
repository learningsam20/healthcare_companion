#!/usr/bin/env bash
# Short P-host smoke (not capacity acceptance). Seeds a small cohort if needed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$ROOT/docs/evidence/load_test_smoke_$STAMP.json"
COHORT="${LOAD_TEST_COHORT_SIZE:-5}"

cd "$ROOT"
# Ensure tagged identities exist (idempotent).
./scripts/seed-users.sh --load-test "$COHORT" >/tmp/sahyog-loadtest-seed.log 2>&1 || {
  echo "seed-users warning; see /tmp/sahyog-loadtest-seed.log" >&2
}

./scripts/load_test.sh \
  --profile r1 \
  --host-profile P \
  --duration 60s \
  --cohort-size "$COHORT" \
  --burst 1 \
  --summary "$REPORT" \
  "$@"

printf 'Smoke evidence: %s\n' "$REPORT"
python3 - "$REPORT" <<'PY'
import json, pathlib, sys
r = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(
    f"status={r.get('status')} capacity_accepted={r.get('capacity_accepted')} "
    f"requests={r.get('requests')} p95={r.get('latency_ms', {}).get('p95')} "
    f"errors={r.get('error_rate_pct')}%"
)
PY
