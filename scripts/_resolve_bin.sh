#!/bin/bash
# Resolve the agent-memory-bridge binary for the wrapper scripts.
# Order: $AMB_BIN, the checkout's .venv, then PATH.
DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
if [ -n "$AMB_BIN" ]; then
  BIN="$AMB_BIN"
elif [ -x "$DIR/.venv/bin/agent-memory-bridge" ]; then
  BIN="$DIR/.venv/bin/agent-memory-bridge"
else
  BIN="$(command -v agent-memory-bridge || true)"
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "Error: agent-memory-bridge not found (set AMB_BIN, create $DIR/.venv, or run 'uv tool install .')" >&2
  exit 1
fi
