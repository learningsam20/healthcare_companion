#!/usr/bin/env bash
# End-to-end smoke against a running stack. Real Keycloak auth; no dev bypass.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/smoke.sh [options]

  --sources        Assert the chat source/provenance panel
  --notifications  Assert in-app notifications and channel declarations
  --analytics      Exercise overview/quality/compliance/evaluations/finops/insights
  --flags          Exercise the feature-flag registry endpoint
  --stt            Report the STT adapter state for this profile
  --telemetry      Check that the profile exposes telemetry
  --cost           Include FinOps checks
  --summary        Print a JSON summary
  --skip-ui        Skip the web container probe
EOF
}

ARGS=()
while (( $# > 0 )); do
  case "$1" in
    --sources | --notifications | --analytics | --flags | --stt | --telemetry | \
      --cost | --summary | --skip-ui)
      ARGS+=("$1")
      shift
      ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd curl python3
activate_profile_from_env
check_required_keys KEYCLOAK_CLI_CLIENT_SECRET SEED_DEMO_PASSWORD >/dev/null ||
  die "SEED_DEMO_PASSWORD and KEYCLOAK_CLI_CLIENT_SECRET are required; seed users first"

if (( ${#ARGS[@]} > 0 )); then
  exec python3 "$ROOT/scripts/smoke.py" "${ARGS[@]}"
fi
exec python3 "$ROOT/scripts/smoke.py"
