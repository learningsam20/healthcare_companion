#!/usr/bin/env bash
# Aggregate-only FinOps showback export.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/export-finops.sh [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--days N]
                                [--format csv|json] [--out FILE]

The API exposes a rolling window; --days is exact. With --from/--to the window is
converted to a day count ending today. Usage is app-recorded and aggregate-only.
EOF
}

ARGS=()
while (( $# > 0 )); do
  case "$1" in
    --from | --to | --days | --format | --out)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --from=* | --to=* | --days=* | --format=* | --out=*)
      ARGS+=("${1%%=*}" "${1#*=}")
      shift
      ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd python3
exec python3 "$ROOT/scripts/export_finops.py" "${ARGS[@]}"
