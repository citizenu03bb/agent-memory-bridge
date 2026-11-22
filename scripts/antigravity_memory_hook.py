#!/usr/bin/env python3
"""Antigravity PreInvocation hook: push the memory index into a new conversation.

Antigravity only reads cross-agent memory when the agent decides to call the
bridge (pull). This hook makes it push, like Claude Code's MEMORY.md: on the
first model invocation of each user turn it runs `agent-memory-bridge list`
and returns the result as an `ephemeralMessage` step (see should_inject).

Install as a PreInvocation hook in ~/.gemini/config/hooks.json (global) or
<workspace>/.agents/hooks.json; see README "Antigravity push hook".

Contract (see Antigravity's hooks.md): JSON on stdin, JSON on stdout. The hook
must never break the agent loop, so every failure path prints `{}`.

Environment:
  AMB_BIN                 bridge binary (default: checkout .venv, then PATH)
  AMB_HOOK_MAX_CHARS      truncate the injected index (default 12000)
  AMB_HOOK_STATE_DIR      where per-conversation markers live
                          (default $XDG_STATE_HOME/agent-memory-bridge/antigravity-hook)
  AMB_HOOK_DEBUG=1        also append each stdin payload to <state>/debug.jsonl
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HEADER = (
    "[agent-memory-bridge] Cross-agent memory index (Claude Code, Codex, neutral). "
    "These are summaries only: before relying on a note, open it with the "
    "agent-memory `read_memory` tool (or `agent-memory-bridge read <id>`). "
    "Record durable, evidence-bound findings with `record_memory`.\n\n"
)
DEFAULT_MAX_CHARS = 12000
SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def state_dir() -> Path:
    override = os.environ.get("AMB_HOOK_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "agent-memory-bridge" / "antigravity-hook"


def resolve_bin() -> str | None:
    explicit = os.environ.get("AMB_BIN")
    if explicit:
        return explicit
    venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "agent-memory-bridge"
    if venv.is_file() and os.access(venv, os.X_OK):
        return str(venv)
    return shutil.which("agent-memory-bridge")


def claim_conversation(state: Path, conversation_id: str) -> bool:
    """Atomically mark the conversation as served. False if already served."""
    marker = state / "seen" / SAFE_ID.sub("_", conversation_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    os.close(fd)
    return True


def should_inject(payload: dict, state: Path) -> bool:
    """Inject on the first model call of every user turn.

    Observed with agy 1.5.14: `ephemeralMessage` steps are dropped after the
    turn they were injected in, and `invocationNum` restarts at 0 on each user
    message. Injecting at invocationNum == 0 keeps the index in view for the
    whole session at ~1k tokens per turn. Without invocationNum, fall back to
    once per conversation.
    """
    invocation = payload.get("invocationNum")
    if isinstance(invocation, int) and not isinstance(invocation, bool):
        return invocation == 0
    conversation_id = payload.get("conversationId")
    if not isinstance(conversation_id, str) or not conversation_id:
        return False
    return claim_conversation(state, conversation_id)


def build_message(max_chars: int) -> str | None:
    binary = resolve_bin()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "list"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    body = proc.stdout.strip()
    if proc.returncode != 0 or not body:
        return None
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n… (truncated; run `agent-memory-bridge list` for the rest)"
    return HEADER + body


def run(stdin_text: str) -> dict:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}

    state = state_dir()
    if os.environ.get("AMB_HOOK_DEBUG") == "1":
        state.mkdir(parents=True, exist_ok=True)
        with open(state / "debug.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")

    if not should_inject(payload, state):
        return {}

    try:
        max_chars = int(os.environ.get("AMB_HOOK_MAX_CHARS", DEFAULT_MAX_CHARS))
    except ValueError:
        max_chars = DEFAULT_MAX_CHARS
    message = build_message(max_chars)
    if message is None:
        return {}
    return {"injectSteps": [{"ephemeralMessage": message}]}


def main() -> int:
    try:
        result = run(sys.stdin.read())
    except Exception:  # never break the agent loop
        result = {}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
