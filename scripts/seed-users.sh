#!/usr/bin/env bash
# Create or update the synthetic demo and load-test Keycloak cohorts.
#
# Uses the sahyog-admin service account after bootstrap. Idempotent. Passwords are
# taken from SEED_DEMO_PASSWORD and are never printed.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/seed-users.sh [--realm REALM] [--force] [--load-test N]

  --realm      Override KEYCLOAK_REALM for this run
  --force      Reset demo-user passwords (never production users)
  --load-test  Create N loadtest.* users (0-100) and their patient rows
EOF
}

FORCE=0
LOAD_TEST=0
while (( $# > 0 )); do
  case "$1" in
    --realm)
      [[ $# -ge 2 ]] || die "--realm requires a value"
      export KEYCLOAK_REALM="$2"
      shift 2
      ;;
    --realm=*)
      export KEYCLOAK_REALM="${1#*=}"
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --load-test)
      [[ $# -ge 2 ]] || die "--load-test requires a number"
      LOAD_TEST="$2"
      shift 2
      ;;
    --load-test=*)
      LOAD_TEST="${1#*=}"
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1 (try --help)"
      ;;
  esac
done

[[ "$LOAD_TEST" =~ ^[0-9]+$ ]] || die "--load-test must be an integer"
(( LOAD_TEST <= 100 )) || die "--load-test must be 100 or fewer unless the guard is reviewed"

require_env_file
require_cmd docker curl python3
activate_profile_from_env
check_required_keys KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_ADMIN_CLIENT_SECRET \
  KEYCLOAK_CLI_CLIENT_SECRET KEYCLOAK_MCP_CLIENT_SECRET SEED_DEMO_PASSWORD ||
  die "Keycloak seeding requires complete credentials in $ENV_FILE"
validate_profile_env "$APP_PROFILE"

step "Synchronising realm, roles, clients and protocol mappers"
compose_run_api python scripts/keycloak_admin.py sync >/dev/null
ok "realm $(env_value KEYCLOAK_REALM sahyog) is in sync"

seed_args=(python scripts/keycloak_admin.py seed-demo)
if (( FORCE == 1 )); then
  seed_args+=(--force)
fi
if (( LOAD_TEST > 0 )); then
  seed_args+=(--load-test "$LOAD_TEST")
fi

step "Seeding demo users"
compose_run_api "${seed_args[@]}" >/tmp/sahyog-seed-users.json
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads(Path("/tmp/sahyog-seed-users.json").read_text())
summary = {
    "realm": payload.get("realm"),
    "demo_users": payload.get("demo_users"),
    "load_test_users": payload.get("load_test_users"),
    "created": payload.get("created"),
    "updated": payload.get("updated"),
}
print(json.dumps(summary, indent=2, sort_keys=True))
PY
rm -f /tmp/sahyog-seed-users.json

if (( LOAD_TEST > 0 )); then
  step "Seeding load-test patient rows"
  compose_run_api python scripts/seed_demo.py --load-test "$LOAD_TEST" >/dev/null
  compose_run_api python scripts/keycloak_admin.py sync-loadtest-links \
    --load-test "$LOAD_TEST" >/dev/null
  ok "load-test patient rows are linked to their Keycloak subjects"
fi

ok "users are seeded; set SEED_DEMO_PASSWORD locally and never commit it"

step "Re-linking existing demo rows to the issued Keycloak subjects"
compose_run_api python scripts/keycloak_admin.py sync-demo-links >/dev/null
ok "demo rows point at real Keycloak user IDs"
