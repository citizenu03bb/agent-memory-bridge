#!/bin/bash
# Search across memories (Claude Code, Codex, and Neutral store).
set -e
source "$(dirname "$(readlink -f "$0")")/_resolve_bin.sh"
exec "$BIN" search "$@"
