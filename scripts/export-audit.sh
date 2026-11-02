#!/usr/bin/env bash
# Compliance-scoped audit export.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/export-audit.sh [--from YYYY-MM-DD] [--to YYYY-MM-DD]
                               [--actor SUBJECT] [--action ACTION]
                               [--format json|csv] [--out FILE]
EOF
}

ARGS=()
while (( $# > 0 )); do
  case "$1" in
    --from | --to | --actor | --action | --format | --out)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --from=* | --to=* | --actor=* | --action=* | --format=* | --out=*)
      ARGS+=("${1%%=*}" "${1#*=}")
      shift
      ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
done

require_env_file
require_cmd python3
exec python3 "$ROOT/scripts/export_audit.py" "${ARGS[@]}"
