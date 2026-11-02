#!/usr/bin/env bash
# Capture analytics for a window. Dry-run by default; --live writes an evidence file.
#
# This build computes analytics at request time, so this is a frozen live snapshot,
# not a scheduled database rollup.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/analytics-refresh.sh [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--days N]
                                    [--metric ID] [--live] [--out FILE]

  (no --live)  Show which sections would be captured
  --live       Call the analytics API and write docs/evidence/analytics-snapshot-*.json
EOF
}

ARGS=()
while (( $# > 0 )); do
  case "$1" in
    --from | --to | --days | --metric | --out)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --from=* | --to=* | --days=* | --metric=* | --out=*)
      ARGS+=("${1%%=*}" "${1#*=}")
      shift
      ;;
    --live) ARGS+=(--live); shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd python3
exec python3 "$ROOT/scripts/analytics_snapshot.py" "${ARGS[@]}"
