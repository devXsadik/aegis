#!/usr/bin/env bash
# Compatibility wrapper — prefer: ./run.sh
exec "$(cd "$(dirname "$0")/.." && pwd)/run.sh" "$@"
