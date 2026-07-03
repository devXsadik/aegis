#!/usr/bin/env bash
# Thin wrapper — delegates to scripts/setup.sh
exec "$(dirname "$0")/scripts/setup.sh" "$@"
