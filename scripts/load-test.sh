#!/usr/bin/env bash
# Compatibility wrapper — prefer scripts/load_test.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/load_test.sh" "$@"
