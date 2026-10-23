#!/bin/bash
# Read a memory file by slug or qualified ID across all stores.
set -e
source "$(dirname "$(readlink -f "$0")")/_resolve_bin.sh"
exec "$BIN" read "$@"
