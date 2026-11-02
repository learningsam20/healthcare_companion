#!/usr/bin/env bash
# Retention evidence and manual recovery entry point.
#
# The scheduled worker owns the same jobs. This script is for a dry-run report or an
# approved manual run, and never purges signed notes or audit events.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/retention.sh [--dry-run] [--live --confirm] [--out FILE]

  (default)   Count what would be purged; change nothing
  --live      Run the implemented retention jobs and append an audit event
  --confirm   Required with --live in a non-interactive shell
  --out FILE  Also write the JSON report to FILE
EOF
}

LIVE=0
OUT=""
while (( $# > 0 )); do
  case "$1" in
    --dry-run) LIVE=0; shift ;;
    --live) LIVE=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    --out)
      [[ $# -ge 2 ]] || die "--out requires a path"
      OUT="$2"
      shift 2
      ;;
    --out=*) OUT="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker python3
activate_profile_from_env
validate_profile_env "$APP_PROFILE"

args=(python scripts/retention_run.py)
if (( LIVE == 1 )); then
  require_confirmation "Run retention purges now? Signed notes and audit events are never deleted."
  args+=(--live --confirm)
else
  args+=(--dry-run)
fi

step "Retention report"
report="$(compose_run_api "${args[@]}")"
printf '%s\n' "$report"
if [[ -n "$OUT" ]]; then
  mkdir -p "$(dirname "$OUT")"
  printf '%s\n' "$report" >"$OUT"
  chmod 600 "$OUT"
  ok "report written to $OUT"
fi
if (( LIVE == 1 )); then
  ok "retention run complete and audited"
else
  dim "  Dry run only. Use --live --confirm for an approved purge."
fi
