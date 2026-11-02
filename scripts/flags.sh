#!/usr/bin/env bash
# Inspect and validate feature flags using the API configuration objects.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/flags.sh [--validate] [--json] [--diff]

  (none)      Human-readable effective flags
  --validate  Fail on an invalid registry, expired flag, unknown FEATURE_* variable or
              an attempt to disable a locked safety flag
  --json      Machine-readable effective flags
  --diff      Only flags whose source is not the registry default
EOF
}

MODE="list"
case "${1:-}" in
  "")
    ;;
  --validate) MODE="validate" ;;
  --json) MODE="json" ;;
  --diff) MODE="diff" ;;
  -h | --help) usage; exit 0 ;;
  *) die "unknown option: $1 (try --help)" ;;
esac

require_env_file
require_cmd docker python3
activate_profile_from_env
validate_profile_env "$APP_PROFILE"

case "$MODE" in
  validate)
    step "Validating configuration and feature flags"
    compose_run_api python scripts/validate_config.py
    ;;
  json)
    compose_run_api python scripts/flags_report.py --json
    ;;
  diff)
    compose_run_api python scripts/flags_report.py --diff
    ;;
  list)
    compose_run_api python scripts/flags_report.py
    ;;
esac
