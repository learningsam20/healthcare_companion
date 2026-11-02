#!/usr/bin/env bash
# Real-user-safe synthetic load test over the public API.
#
# The load generator is a client: it authenticates the tagged loadtest.* Keycloak
# cohort with the password grant, drives the SPA's HTTP endpoints and never uses a
# dev bypass or writes to the database directly. Synthetic cost and real activity
# come from /api/v1/analytics/load-guard; the full profile adds Prometheus p95/error
# guardrails for real traffic.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/load_test.sh [options]

  --profile r1|r2|r3|ml    Release profile (default r1); r3/ml use 1,400 req/h
  --host-profile P|S|M|L   Required host size recorded in the evidence report
  --rate N                 Requests per hour (r1/r2 500, r3 1400)
  --burst N                Burst multiplier (r3 defaults to 4)
  --duration 60m           Test window (30s, 60m, 1h)
  --cohort-size N          Load-test patients (1-20; seed-users.sh --load-test N)
  --auth keycloak          Only Keycloak password-grant auth is supported
  --traffic-class synthetic Only the synthetic tag is accepted
  --allow-real-users       Required when real users are active; needs approval env
  --abort-on-real-slo      Abort when real-user p95/error breaches the guard
  --prometheus-url URL     Prometheus base URL (full profile; default PROMETHEUS_URL)
  --budget-usd N           Abort if synthetic model cost exceeds N USD (default 5)
  --include-llm            Also send chat messages (costs model tokens)
  --patients-only          Do not generate front-desk traffic
  --dry-run                Authenticate and preflight only; send no traffic
  --reset-test-data        Remove tagged load-test data after the run
  --summary PATH           Override the JSON evidence path
  --report-md PATH         Override the markdown report (default docs/evidence/load_test_report.md)

Each non-dry run also writes docs/evidence/load_test_report.md next to the JSON evidence.
LOAD_TEST_KILL=1 injects an over-budget cost into the first guard sample (G-22 abort
drill; status kill_drill_passed, never capacity evidence). Needs the guard to poll once.

Real-user mode requires LOAD_TEST_ALLOW_REAL_USERS=true and LOAD_TEST_APPROVAL_REF.
There is no development auth bypass and no direct database seeding.
EOF
}

PROFILE=r1
HOST_PROFILE=""
RATE=""
BURST=""
DURATION=""
COHORT=20
AUTH=keycloak
TRAFFIC=synthetic
ALLOW=0
ABORT=0
PROM=""
BUDGET="5"
INCLUDE_LLM=0
PATIENTS_ONLY=0
DRY_RUN=0
RESET=0
SUMMARY=""
REPORT_MD=""
PASSTHROUGH=()

while (( $# > 0 )); do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --profile=*) PROFILE="${1#*=}"; shift ;;
    --host-profile) HOST_PROFILE="$2"; shift 2 ;;
    --host-profile=*) HOST_PROFILE="${1#*=}"; shift ;;
    --rate) RATE="$2"; shift 2 ;;
    --rate=*) RATE="${1#*=}"; shift ;;
    --burst) BURST="$2"; shift 2 ;;
    --burst=*) BURST="${1#*=}"; shift ;;
    --duration) DURATION="$2"; shift 2 ;;
    --duration=*) DURATION="${1#*=}"; shift ;;
    --cohort-size) COHORT="$2"; shift 2 ;;
    --cohort-size=*) COHORT="${1#*=}"; shift ;;
    --auth) AUTH="$2"; shift 2 ;;
    --auth=*) AUTH="${1#*=}"; shift ;;
    --traffic-class) TRAFFIC="$2"; shift 2 ;;
    --traffic-class=*) TRAFFIC="${1#*=}"; shift ;;
    --allow-real-users) ALLOW=1; shift ;;
    --abort-on-real-slo) ABORT=1; shift ;;
    --prometheus-url) PROM="$2"; shift 2 ;;
    --prometheus-url=*) PROM="${1#*=}"; shift ;;
    --budget-usd) BUDGET="$2"; shift 2 ;;
    --budget-usd=*) BUDGET="${1#*=}"; shift ;;
    --include-llm) INCLUDE_LLM=1; shift ;;
    --patients-only) PATIENTS_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --reset-test-data) RESET=1; shift ;;
    --summary) SUMMARY="$2"; shift 2 ;;
    --summary=*) SUMMARY="${1#*=}"; shift ;;
    --report-md) REPORT_MD="$2"; shift 2 ;;
    --report-md=*) REPORT_MD="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ "$AUTH" == "keycloak" ]] || die "only --auth keycloak is supported; dev auth bypasses do not exist"
[[ "$TRAFFIC" == "synthetic" ]] || die "only --traffic-class synthetic is supported"
case "$PROFILE" in
  r1 | r2 | r3 | ml) ;;
  *) die "--profile must be r1, r2, r3 or ml" ;;
esac
case "$HOST_PROFILE" in
  P | S | M | L) ;;
  *) die "--host-profile is required and must be P, S, M or L" ;;
esac
[[ -n "$DURATION" ]] || DURATION="$([[ "$PROFILE" == "ml" ]] && printf '300' || printf '60m')"

require_env_file
require_cmd uv python3 curl
activate_profile_from_env

[[ -n "$(env_value SEED_DEMO_PASSWORD "")" ]] ||
  die "SEED_DEMO_PASSWORD is required to authenticate the load-test cohort"
[[ -n "$(env_value KEYCLOAK_CLI_CLIENT_SECRET "")" ]] ||
  die "KEYCLOAK_CLI_CLIENT_SECRET is required to authenticate the load-test cohort"
wait_http "${API_BASE_URL%/}/healthz" "API liveness" 30 >/dev/null ||
  die "the API is not reachable; start the stack and seed the cohort first"

if (( ALLOW == 1 )); then
  require_confirmation "Load test will run while real users may be active. Approval reference: $(env_value LOAD_TEST_APPROVAL_REF '<missing>')"
  [[ "$(env_value LOAD_TEST_ALLOW_REAL_USERS false)" == "true" ]] ||
    die "set LOAD_TEST_ALLOW_REAL_USERS=true in .env for an approved real-user window"
  [[ -n "$(env_value LOAD_TEST_APPROVAL_REF "")" ]] ||
    die "set LOAD_TEST_APPROVAL_REF to the recorded approval identifier"
  (( ABORT == 1 )) || die "--abort-on-real-slo is required with --allow-real-users"
fi

cmd=(uv run python scripts/load_test.py --profile "$PROFILE" --host-profile "$HOST_PROFILE" --duration "$DURATION"
  --cohort-size "$COHORT" --budget-usd "$BUDGET")
[[ -n "$RATE" ]] && cmd+=(--rate "$RATE")
[[ -n "$BURST" ]] && cmd+=(--burst "$BURST")
[[ -n "$PROM" ]] && cmd+=(--prometheus-url "$PROM")
[[ -n "$SUMMARY" ]] && cmd+=(--summary "$SUMMARY")
[[ -n "$REPORT_MD" ]] && cmd+=(--report-md "$REPORT_MD")
(( ALLOW == 1 )) && cmd+=(--allow-real-users)
(( ABORT == 1 )) && cmd+=(--abort-on-real-slo)
(( INCLUDE_LLM == 1 )) && cmd+=(--include-llm)
(( PATIENTS_ONLY == 1 )) && cmd+=(--patients-only)
(( DRY_RUN == 1 )) && cmd+=(--dry-run)

cd "$ROOT"
set +e
"${cmd[@]}"
status=$?
set -e

if (( RESET == 1 )); then
  step "Resetting tagged load-test data"
  "$ROOT/scripts/reset-test-data.sh" --cohort loadtest --cohort-size "$COHORT" \
    --include-users --confirm ||
    warn "load-test data reset failed; rerun scripts/reset-test-data.sh before the next benchmark"
fi

exit "$status"
