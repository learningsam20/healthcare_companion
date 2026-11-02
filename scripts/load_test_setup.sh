#!/usr/bin/env bash
# Prepare load_test datasets (Kaggle-derived) and seed volume into the running stack.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

PHARMACY_LIMIT=25000
DOCTOR_LIMIT=500
SLOTS=5000
COHORT=5
PDFS=10
INGEST_PDFS=1

usage() {
  cat <<'EOF'
Usage: scripts/load_test_setup.sh [options]

  --pharmacy-limit N   Active medicines mapped into stock (default 25000)
  --doctor-limit N     Doctors from healthcare dataset (default 500)
  --slots N            Load-test appointments to seed (default 5000)
  --cohort N           loadtest.patient* count (default 5)
  --pdfs N             Synthetic PDFs on loadtest patients (default 10)
  --no-ingest-pdfs     Skip embedding ingest
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --pharmacy-limit) PHARMACY_LIMIT="$2"; shift 2 ;;
    --doctor-limit) DOCTOR_LIMIT="$2"; shift 2 ;;
    --slots) SLOTS="$2"; shift 2 ;;
    --cohort) COHORT="$2"; shift 2 ;;
    --pdfs) PDFS="$2"; shift 2 ;;
    --no-ingest-pdfs) INGEST_PDFS=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

require_env_file
activate_profile_from_env
wait_compose_healthy postgres 120 >/dev/null || die "Postgres is not healthy"

step "Seeding loadtest Keycloak + Patient rows"
./scripts/seed-users.sh --load-test "$COHORT" >/tmp/sahyog-load_test_seed_users.log 2>&1 ||
  warn "seed-users reported issues; see /tmp/sahyog-load_test_seed_users.log"

step "Building load_test_* datasets from Kaggle extracts"
python3 scripts/load_test_prepare_datasets.py \
  --pharmacy-limit "$PHARMACY_LIMIT" \
  --doctor-limit "$DOCTOR_LIMIT" \
  --patient-ref-limit 2000

step "Importing pharmacy stock + seeding appointments/PDFs"
pdf_args=(--ingest-pdfs "$PDFS")
if (( INGEST_PDFS == 0 )); then
  pdf_args=(--ingest-pdfs 0)
fi
# Mount host datasets + scripts so freshly built CSVs are visible without image rebuild.
compose run --rm --no-deps -T \
  -v "${ROOT}/docs/evidence/datasets:/app/docs/evidence/datasets:ro" \
  -v "${ROOT}/scripts:/app/scripts:ro" \
  api python scripts/load_test_seed_volume.py \
    --pharmacy-csv docs/evidence/datasets/load_test_pharmacy_stock.csv \
    --doctors-csv docs/evidence/datasets/load_test_doctors.csv \
    --import-pharmacy \
    --slots "$SLOTS" \
    --cohort-size "$COHORT" \
    "${pdf_args[@]}"

ok "load_test volume ready (pharmacy + appointments + optional PDFs)"
