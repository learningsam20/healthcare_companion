#!/usr/bin/env bash
# Restart one service or the whole active stack without recreating containers.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/restart.sh [--service NAME]

  --service NAME  Restart one service; default restarts every created service
EOF
}

SERVICE=""
while (( $# > 0 )); do
  case "$1" in
    --service)
      [[ $# -ge 2 ]] || die "--service requires a name"
      SERVICE="$2"
      shift 2
      ;;
    --service=*) SERVICE="${1#*=}"; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker
activate_profile_from_env

if [[ -n "$SERVICE" ]]; then
  step "Restarting $SERVICE"
  compose_all restart "$SERVICE"
  ok "$SERVICE restarted"
else
  step "Restarting the stack"
  compose_all restart
  ok "stack restarted"
fi

dim "Configuration changes need ./scripts/start.sh, not restart; restart keeps the old environment."
