#!/usr/bin/env bash
# Judge calibration: LLM labels + optional attested human review for κ gate.
# status=calibrated only when REVIEWER_FILE attests human review AND κ ≥ 0.6.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROVISIONAL="$ROOT/evals/calibration/reviewer_provisional.json"
JUDGE_LABELS="${JUDGE_LABELS_FILE:-$ROOT/evals/calibration/judge_labels.json}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CALIBRATION_OUT="$ROOT/docs/evidence/judge-calibration-$STAMP.json"
REPORT="$ROOT/docs/evidence/judge-calibration-run-$STAMP.json"
REVIEWER_ARGS=()
JUDGE_ARGS=()

cd "$ROOT"
if [[ -n "${REVIEWER_FILE:-}" ]]; then
  python3 - "$REVIEWER_FILE" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("attested_human_review") is not True:
    raise SystemExit("REVIEWER_FILE must explicitly set attested_human_review=true")
PY
  REVIEWER_ARGS=(--reviewer-file "$REVIEWER_FILE")
else
  python3 - "$PROVISIONAL" <<'PY'
import datetime
import json
import pathlib
import sys

root = pathlib.Path.cwd()
template = json.loads(
    (root / "evals/calibration/reviewer_template.json").read_text(encoding="utf-8")
)
fixture = json.loads(
    (root / "evals/calibration/judge_calibration.json").read_text(encoding="utf-8")
)
labels = {}
for pair in fixture["pairs"]:
    labels[pair["good"]["id"]] = pair["good"]["label"]
    labels[pair["bad"]["id"]] = pair["bad"]["label"]
template.update(
    {
        "reviewer_id": "provisional_fixture",
        "reviewed_at": datetime.date.today().isoformat(),
        "attested_human_review": False,
        "review_mode": "fixture_consistency_smoke",
        "calibrated_by": "provisional_fixture",
        "labels": labels,
        "note": "Copied fixture labels for consistency smoke; not human calibration.",
    }
)
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  printf 'Provisional labels: %s (not passed as human review)\n' "$PROVISIONAL"
fi

if [[ "${SKIP_LLM_JUDGE:-0}" != "1" ]]; then
  if [[ -n "${LITELLM_BASE_URL:-}" && -n "${LITELLM_MASTER_KEY:-}" ]]; then
    uv run python evals/harness/produce_judge_labels.py --out "$JUDGE_LABELS"
    JUDGE_ARGS=(--judge-labels "$JUDGE_LABELS")
  elif [[ -f "$JUDGE_LABELS" ]]; then
    JUDGE_ARGS=(--judge-labels "$JUDGE_LABELS")
    printf 'Using existing judge labels: %s\n' "$JUDGE_LABELS"
  else
    printf 'No LiteLLM env and no judge labels file; artefact will stay pending_judge_verdicts\n'
  fi
fi

uv run python evals/harness/framework_runner.py \
  --calibration-only \
  --calibration-out "$CALIBRATION_OUT" \
  --report "$REPORT" \
  "${REVIEWER_ARGS[@]}" \
  "${JUDGE_ARGS[@]}"

printf 'Calibration evidence: %s\n' "$CALIBRATION_OUT"
printf 'Run report: %s\n' "$REPORT"
python3 - "$CALIBRATION_OUT" <<'PY'
import json, pathlib, sys
art = json.loads(pathlib.Path(sys.argv[1]).read_text())
print(
    f"status={art.get('status')} judge_calibration_status={art.get('judge_calibration_status')} "
    f"meets_kappa_target={art.get('meets_kappa_target')}"
)
if art.get("status") != "calibrated":
    print("Note: calibrated requires attested REVIEWER_FILE + κ≥0.6; safety gate stays authoritative.")
PY
