#!/usr/bin/env bash
# Graceful stop. Volumes are kept unless --volumes is confirmed.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/stop.sh [--service NAME] [--volumes] [--confirm]

  --service   Stop one service instead of the stack
  --volumes   Remove containers AND named volumes (destructive)
  --confirm   Non-interactive confirmation for --volumes
EOF
}

SERVICE=""
VOLUMES=0
CONFIRM=0
while (( $# > 0 )); do
  case "$1" in
    --service)
      [[ $# -ge 2 ]] || die "--service requires a name"
      SERVICE="$2"
      shift 2
      ;;
    --service=*) SERVICE="${1#*=}"; shift ;;
    --volumes) VOLUMES=1; shift ;;
    --confirm) CONFIRM=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker
activate_profile_from_env

if (( VOLUMES == 1 )); then
  [[ -z "$SERVICE" ]] || die "--volumes stops the whole stack; do not combine it with --service"
  export CONFIRM
  require_confirmation "This removes containers, networks and named volumes (Postgres, MinIO, Redis, Grafana, Ollama, ClickHouse)."
  step "Stopping the stack and removing volumes"
  compose_all down --volumes --remove-orphans
  ok "containers and volumes removed"
  exit 0
fi

if [[ -n "$SERVICE" ]]; then
  step "Stopping $SERVICE"
  compose_all stop "$SERVICE"
  ok "$SERVICE stopped"
else
  step "Stopping the stack (volumes kept)"
  compose_all stop
  ok "stack stopped; restart with ./scripts/start.sh --profile <profile>"
fi
