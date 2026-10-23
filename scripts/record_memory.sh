#!/bin/bash
# Record a memory note into the neutral store via agent-memory-bridge CLI.
set -e
source "$(dirname "$(readlink -f "$0")")/_resolve_bin.sh"
exec "$BIN" record "$@"
