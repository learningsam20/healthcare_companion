#!/usr/bin/env bash
# Generate deterministic synthetic scheduling, PDF and transcript data.
#
# Everything is written through the real repositories and object storage, and the
# records carry the synthetic traffic tag. No signed clinical notes are created.
#
# NFR-SCALE-02 targets (500 doctors / 480k slots / 2k PDFs) are supported as caps.
# Full-size runs are slow on P hosts; prefer staged volumes then re-measure grids.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/generate-synthetic.sh [options]

  --doctors N         Doctors to schedule appointments against (0-500; default 6)
  --slots N           Appointment slots to fill (0-480000; default 24)
  --pdfs N            Synthetic clinical PDFs to generate (0-2000; default 4)
  --transcripts N     Synthetic transcripts to generate (0-2000; default 2)
  --patient-cohort C  demo | loadtest | both (default demo). Use loadtest for PERF-02.
  --seed N            Deterministic seed (default 7)
  --ingest            Ingest generated PDFs through the real embedding pipeline
                      (requires LiteLLM and the local embedding model)

Documents and transcripts need patients present:
  demo      → scripts/load-data.sh --sample
  loadtest  → scripts/seed-users.sh --load-test 5 (and matching Patient rows)

Re-running with the same seed is idempotent for fixed IDs.
EOF
}

DOCTORS=6
SLOTS=24
PDFS=4
TRANSCRIPTS=2
SEED=7
PATIENT_COHORT=demo
INGEST=0

while (( $# > 0 )); do
  case "$1" in
    --doctors | --slots | --pdfs | --transcripts | --seed | --patient-cohort)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      case "$1" in
        --doctors) DOCTORS="$2" ;;
        --slots) SLOTS="$2" ;;
        --pdfs) PDFS="$2" ;;
        --transcripts) TRANSCRIPTS="$2" ;;
        --seed) SEED="$2" ;;
        --patient-cohort) PATIENT_COHORT="$2" ;;
      esac
      shift 2
      ;;
    --doctors=*) DOCTORS="${1#*=}"; shift ;;
    --slots=*) SLOTS="${1#*=}"; shift ;;
    --pdfs=*) PDFS="${1#*=}"; shift ;;
    --transcripts=*) TRANSCRIPTS="${1#*=}"; shift ;;
    --seed=*) SEED="${1#*=}"; shift ;;
    --patient-cohort=*) PATIENT_COHORT="${1#*=}"; shift ;;
    --ingest) INGEST=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

case "$PATIENT_COHORT" in
  demo | loadtest | both) ;;
  *) die "--patient-cohort must be demo, loadtest, or both" ;;
esac

for pair in "doctors:$DOCTORS" "slots:$SLOTS" "pdfs:$PDFS" "transcripts:$TRANSCRIPTS" \
  "seed:$SEED"; do
  [[ "${pair#*:}" =~ ^[0-9]+$ ]] || die "${pair%%:*} must be a non-negative integer"
done

require_env_file
require_cmd docker curl python3
activate_profile_from_env

wait_compose_healthy postgres 120 >/dev/null ||
  die "Postgres is not healthy; run scripts/start.sh first"

args=(python scripts/generate_synthetic.py
  --doctors "$DOCTORS" --slots "$SLOTS" --pdfs "$PDFS"
  --transcripts "$TRANSCRIPTS" --seed "$SEED"
  --patient-cohort "$PATIENT_COHORT")
if (( INGEST == 1 )); then
  args+=(--ingest)
fi

step "Generating synthetic clinical data"
compose_run_api "${args[@]}"

ok "synthetic data generated; every row is tagged synthetic and no note was signed"
