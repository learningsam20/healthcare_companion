#!/usr/bin/env bash
# Add or update one interactive user through the Keycloak Admin API.
#
# The password is read from ADD_USER_PASSWORD (or a named *_PASSWORD variable) and is
# never printed. The sahyog-admin service account performs the write.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/add-user.sh --username NAME --role ROLE [options] --confirm

  --username NAME            Keycloak username (required)
  --role ROLE                patient|caregiver|doctor|front_desk|pharmacist|compliance|admin
  --clinic CODE              Clinic code; repeat for more than one
  --patient-id UUID          Link a patient account to a patient row
  --email ADDRESS            Email address
  --first-name NAME          Given name
  --last-name NAME           Family name
  --locale LOCALE            en-IN|hi-IN|mr-IN (default en-IN)
  --cohort NAME              Cohort tag (default demo)
  --slack-id ID              Verified Slack member ID
  --slack-audience AUD       patient|staff (required with --slack-id)
  --slack-verified           Mark the Slack mapping verified
  --reset-password           Reset the password for an existing user
  --password-env NAME        Environment variable holding the password
                             (default ADD_USER_PASSWORD)
  --confirm                  Required; acknowledges an identity change

The password variable must already be exported or present in .env.
EOF
}

USERNAME=""
ROLE=""
PASSWORD_ENV="ADD_USER_PASSWORD"
CONFIRM=0
EXTRA=()
while (( $# > 0 )); do
  case "$1" in
    --username | --role | --patient-id | --email | --first-name | --last-name | \
      --locale | --cohort | --slack-id | --slack-audience | --password-env)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      case "$1" in
        --username) USERNAME="$2" ;;
        --role) ROLE="$2" ;;
        --patient-id) EXTRA+=(--patient-id "$2") ;;
        --email) EXTRA+=(--email "$2") ;;
        --first-name) EXTRA+=(--first-name "$2") ;;
        --last-name) EXTRA+=(--last-name "$2") ;;
        --locale) EXTRA+=(--locale "$2") ;;
        --cohort) EXTRA+=(--cohort "$2") ;;
        --slack-id) EXTRA+=(--slack-id "$2") ;;
        --slack-audience) EXTRA+=(--slack-audience "$2") ;;
        --password-env) PASSWORD_ENV="$2" ;;
      esac
      shift 2
      ;;
    --clinic)
      [[ $# -ge 2 ]] || die "--clinic requires a value"
      EXTRA+=(--clinic "$2")
      shift 2
      ;;
    --slack-verified) EXTRA+=(--slack-verified); shift ;;
    --reset-password) EXTRA+=(--reset-password); shift ;;
    --confirm) CONFIRM=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

[[ -n "$USERNAME" ]] || die "--username is required"
[[ -n "$ROLE" ]] || die "--role is required"
(( CONFIRM == 1 )) || die "pass --confirm to change identities"
require_env_file
require_cmd docker python3
activate_profile_from_env
validate_profile_env "$APP_PROFILE"

password="$(env_value "$PASSWORD_ENV" "")"
[[ -n "$password" ]] || die "$PASSWORD_ENV is not set; export it or add it to .env"
(( ${#password} >= 12 )) || die "$PASSWORD_ENV must be at least 12 characters"

export ADD_USER_PASSWORD="$password"
unset password

set +e
result="$(compose run --rm --no-deps -T -e ADD_USER_PASSWORD api \
  python scripts/keycloak_admin.py add-user \
  --username "$USERNAME" \
  --role "$ROLE" \
  --password-env ADD_USER_PASSWORD \
  --confirm \
  "${EXTRA[@]}")"
status=$?
set -e
if (( status != 0 )); then
  die "user provisioning failed; check the Keycloak admin credentials and role"
fi

python3 - <<'PY' "$result"
import json
import sys

payload = json.loads(sys.argv[1])
summary = {
    "username": payload.get("username"),
    "role": payload.get("role"),
    "clinics": payload.get("clinic_ids"),
    "patient_id": payload.get("patient_id"),
    "slack_mapped": bool(payload.get("slack_mapped")),
    "created": payload.get("created"),
    "password_reset": payload.get("password_reset"),
}
print(json.dumps(summary, indent=2, sort_keys=True))
PY

ok "identity $USERNAME is provisioned; no password was printed"
