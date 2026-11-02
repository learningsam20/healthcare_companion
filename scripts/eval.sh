#!/usr/bin/env bash
# Run the deterministic safety eval gate, with optional RAGAS/DeepEval adapters.
#
# The deterministic gate is always a release blocker. RAGAS and DeepEval are
# optional dependencies; when they are absent the run is recorded as unavailable
# and the command exits non-zero rather than silently skipping the suite.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/eval.sh [options]

  --suite w1|w2|w3|x01|all   Suite to run (default w1; all runs present sets)
  --alias NAME               LiteLLM judge alias or model purpose (default judge)
  --framework NAME           deterministic | ragas | deepeval (default deterministic)
  --stub                     Prove the harness offline; deterministic only
  --no-persist               Do not record the run in Postgres or object storage
  --report PATH              Write the JSON report inside the container
  --quiet                    Suppress the human summary
  --no-report                Do not write evals/reports/latest.md
  -h, --help                 Show this help

W1/W2 deterministic suites ship in this build. RAGAS/DeepEval suites require case
sets with answer/context fields and the optional eval dependencies; without them the
run is visible as unavailable and exits 3.
EOF
}

RUNNER_ARGS=()
PERSIST=1
WRITE_REPORT=1
while (( $# > 0 )); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --suite | --alias | --framework | --report)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      RUNNER_ARGS+=("$1" "$2")
      shift 2
      ;;
    --suite=* | --alias=* | --framework=* | --report=*)
      RUNNER_ARGS+=("$1")
      shift
      ;;
    --stub | --quiet)
      RUNNER_ARGS+=("$1")
      shift
      ;;
    --no-persist)
      RUNNER_ARGS+=("$1")
      PERSIST=0
      shift
      ;;
    --no-report) WRITE_REPORT=0; shift ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker curl python3
activate_profile_from_env

if (( PERSIST == 1 )); then
  wait_compose_healthy postgres 120 >/dev/null ||
    die "Postgres is not healthy; run scripts/start.sh first or pass --no-persist"
fi

step "Running evaluation suites"
OUTPUT_FILE="$(mktemp)"
trap 'rm -f "$OUTPUT_FILE"' EXIT
set +e
compose_run_api python evals/harness/runner.py "${RUNNER_ARGS[@]}" | tee "$OUTPUT_FILE"
STATUS=${PIPESTATUS[0]}
set -e

if (( WRITE_REPORT == 1 )) && [[ -s "$OUTPUT_FILE" ]]; then
  python3 scripts/eval_report.py "$OUTPUT_FILE" evals/reports/latest.md ||
    warn "could not render evals/reports/latest.md"
fi
exit "$STATUS"
