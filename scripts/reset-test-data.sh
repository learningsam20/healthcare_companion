#!/usr/bin/env bash
# Remove only the tagged synthetic load-test cohort.
#
# The reset is deterministic: it selects loadtest.* Keycloak subjects and their
# patient IDs, deletes their objects and child rows, clears synthetic usage records,
# then appends one audit event. Demo and real-user rows are never selected.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/reset-test-data.sh [options]

  --cohort loadtest     Only the tagged load-test cohort is supported
  --tag synthetic       Only the synthetic traffic tag is supported
  --cohort-size N       Number of loadtest patients (1-20; default 20)
  --include-users       Also delete the loadtest.* Keycloak users
  --include-eval-artefacts  Also delete stored evaluation runs and metrics
  --allow-protected     Permit the reset when APP_ENV=production
  --confirm             Required in a non-interactive shell
  --dry-run             Print the scope without changing rows or objects

This never truncates tables, never deletes demo users and is safe to re-run.
EOF
}

COHORT=loadtest
TAG=synthetic
COHORT_SIZE=20
INCLUDE_USERS=0
INCLUDE_EVAL=0
ALLOW_PROTECTED=0
DRY_RUN=0

while (( $# > 0 )); do
  case "$1" in
    --cohort)
      [[ $# -ge 2 ]] || die "--cohort requires a value"
      COHORT="$2"
      shift 2
      ;;
    --cohort=*) COHORT="${1#*=}"; shift ;;
    --tag)
      [[ $# -ge 2 ]] || die "--tag requires a value"
      TAG="$2"
      shift 2
      ;;
    --tag=*) TAG="${1#*=}"; shift ;;
    --cohort-size)
      [[ $# -ge 2 ]] || die "--cohort-size requires a number"
      COHORT_SIZE="$2"
      shift 2
      ;;
    --cohort-size=*) COHORT_SIZE="${1#*=}"; shift ;;
    --include-users) INCLUDE_USERS=1; shift ;;
    --include-eval-artefacts) INCLUDE_EVAL=1; shift ;;
    --allow-protected) ALLOW_PROTECTED=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ "$COHORT" == "loadtest" ]] ||
  die "only --cohort loadtest is supported; other cohorts are not tagged for deletion"
[[ "$TAG" == "synthetic" ]] ||
  die "only --tag synthetic is supported; real rows must never be reset by this script"
[[ "$COHORT_SIZE" =~ ^[0-9]+$ ]] || die "--cohort-size must be an integer"
(( COHORT_SIZE >= 1 && COHORT_SIZE <= 20 )) ||
  die "--cohort-size must be between 1 and 20"

require_env_file
require_cmd docker curl python3
activate_profile_from_env

if (( DRY_RUN == 1 )); then
  step "Reset scope (dry run; nothing is deleted)"
  say "  cohort:       $COHORT"
  say "  traffic tag:  $TAG"
  say "  patients:     $COHORT_SIZE"
  say "  keycloak:     $(( INCLUDE_USERS == 1 ? 3 * COHORT_SIZE : 0 )) loadtest.* users"
  say "  excludes:     demo users, real patients, signed notes and real usage records"
  exit 0
fi

require_confirmation "Delete all rows, objects and synthetic usage for the loadtest cohort (size $COHORT_SIZE)?"

step "Resetting the synthetic load-test cohort"

args=(python scripts/reset_test_data.py --cohort "$COHORT" --tag "$TAG"
  --cohort-size "$COHORT_SIZE" --confirm)
if (( INCLUDE_USERS == 1 )); then
  args+=(--include-users)
fi
if (( INCLUDE_EVAL == 1 )); then
  args+=(--include-eval-artefacts)
fi
if (( ALLOW_PROTECTED == 1 )); then
  args+=(--allow-protected)
fi

compose_run_api "${args[@]}"

ok "cohort $COHORT reset; the reset audit event is recorded and no demo/real rows were touched"
