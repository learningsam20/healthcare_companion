#!/usr/bin/env bash
# Tail container logs with credential redaction. Never follows by default in CI.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/logs.sh [--service NAME] [--since DURATION] [--no-follow]

  --service NAME    Limit to one Compose service
  --since DURATION  Docker duration (default: 15m)
  --no-follow       Print the tail and exit (default when not a TTY)
EOF
}

SERVICE=""
SINCE="15m"
FOLLOW=1
if [[ ! -t 1 ]]; then
  FOLLOW=0
fi

while (( $# > 0 )); do
  case "$1" in
    --service)
      [[ $# -ge 2 ]] || die "--service requires a name"
      SERVICE="$2"
      shift 2
      ;;
    --service=*) SERVICE="${1#*=}"; shift ;;
    --since)
      [[ $# -ge 2 ]] || die "--since requires a duration"
      SINCE="$2"
      shift 2
      ;;
    --since=*) SINCE="${1#*=}"; shift ;;
    --no-follow) FOLLOW=0; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd docker
activate_profile_from_env
[[ "$SINCE" =~ ^[0-9]+[smh]$ ]] || die "--since must look like 30s, 15m or 2h"

args=(logs --no-color --timestamps --since "$SINCE")
if (( FOLLOW == 1 )); then
  args+=(--follow)
else
  args+=(--tail 200)
fi
if [[ -n "$SERVICE" ]]; then
  compose_has_service "$SERVICE" || die "unknown service for this profile: $SERVICE"
  args+=("$SERVICE")
fi

compose_all "${args[@]}" 2>&1 | redact_stream
