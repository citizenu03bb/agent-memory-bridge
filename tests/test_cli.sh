#!/bin/bash
# Hermetic End-to-end CLI Test Suite
set -e
set -o pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1. Setup isolated temporary environment
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

export HOME="$TEST_TMP/home"
export XDG_DATA_HOME="$HOME/.local/share"
mkdir -p "$HOME" "$XDG_DATA_HOME"

# Unset any real environment overrides
unset AMB_CLAUDE_PROJECTS_DIR AMB_CODEX_DIR AMB_NEUTRAL_DIR MEMORY_DIR CODEX_MEMORY_DIR NEUTRAL_MEMORY_DIR CLAUDECODE

# 2. Populate mock stores in isolated environment
PREFIX="$(echo "$HOME" | sed 's|[^A-Za-z0-9]|-|g')"
CLAUDE_MEM="$HOME/.claude/projects/$PREFIX/memory"
mkdir -p "$CLAUDE_MEM"
echo "# Global Claude Memories" > "$CLAUDE_MEM/MEMORY.md"
echo "Webapp deployed on staging with RTX 3060 GPU." > "$CLAUDE_MEM/webapp_project.md"

CODEX_MEM="$HOME/.codex/memories/rollout_summaries"
mkdir -p "$CODEX_MEM"
echo "# Codex Summary" > "$HOME/.codex/memories/memory_summary.md"
echo "Webapp agent corrections summary." > "$CODEX_MEM/webapp_agent_corrections.md"

NEUTRAL_NOTES="$XDG_DATA_HOME/agent-memory/notes"
mkdir -p "$NEUTRAL_NOTES"
cat << 'EOF' > "$NEUTRAL_NOTES/2026-10-21-mock-invariant.md"
---
title: "Mock Invariant"
date: "2026-10-21T10:00:00+02:00"
agent: "test"
tags: ["cli", "mock"]
scope: "shared"
kind: "convention"
evidence: "user:mock_2026-10-21"
---

Mock note body for CLI test.
EOF

echo "=== 1. Testing list_memories.sh ==="
LIST_OUT="$(bash "$DIR/scripts/list_memories.sh")"
echo "$LIST_OUT" | grep -F "CLAUDE CODE MEMORIES" >/dev/null
echo "$LIST_OUT" | grep -F "CODEX SHARED MEMORIES" >/dev/null
echo "$LIST_OUT" | grep -F "NEUTRAL AGENT MEMORIES" >/dev/null
echo "$LIST_OUT" | grep -F "Mock Invariant" >/dev/null
echo "PASS: list_memories.sh"

echo "=== 2. Testing grep_memories.sh ==="
GREP_OUT1="$(bash "$DIR/scripts/grep_memories.sh" "RTX 3060")"
echo "$GREP_OUT1" | grep -F "claude:" >/dev/null
GREP_OUT2="$(bash "$DIR/scripts/grep_memories.sh" --regex "RTX [0-9]+ GPU")"
echo "$GREP_OUT2" | grep -F "claude:" >/dev/null
echo "PASS: grep_memories.sh"

echo "=== 3. Testing read_memory.sh on Claude store ==="
READ_CLAUDE="$(bash "$DIR/scripts/read_memory.sh" webapp_project)"
echo "$READ_CLAUDE" | grep -F "Webapp deployed on staging" >/dev/null
echo "PASS: read_memory.sh (Claude)"

echo "=== 4. Testing read_memory.sh on Codex store ==="
READ_CODEX="$(bash "$DIR/scripts/read_memory.sh" webapp_agent_corrections)"
echo "$READ_CODEX" | grep -F "Webapp agent corrections" >/dev/null
echo "PASS: read_memory.sh (Codex)"

echo "=== 5. Testing record_memory.sh with Evidence-Bound constraint ==="
# Test 5A: Missing evidence must fail with non-zero exit and [MemoryRejection]
set +e
ERR_OUT1="$(bash "$DIR/scripts/record_memory.sh" --title "Failing Note Without Evidence" --body "Should fail" 2>&1)"
EXIT_CODE1=$?
set -e

if [ $EXIT_CODE1 -eq 0 ]; then
  echo "FAIL: Expected non-zero exit code for missing evidence, but got 0!" >&2
  exit 1
fi
if ! echo "$ERR_OUT1" | grep -F "[MemoryRejection]" >/dev/null; then
  echo "FAIL: Output did not contain literal '[MemoryRejection]': $ERR_OUT1" >&2
  exit 1
fi
echo "PASS: record_memory.sh rejected note without evidence (exit code $EXIT_CODE1)"

# Test 5B: Harness scope must fail
set +e
ERR_OUT2="$(bash "$DIR/scripts/record_memory.sh" --title "Harness Discipline Note" --scope "harness:gemini" --body "Model discipline" 2>&1)"
EXIT_CODE2=$?
set -e

if [ $EXIT_CODE2 -eq 0 ]; then
  echo "FAIL: Expected non-zero exit code for harness scope, but got 0!" >&2
  exit 1
fi
if ! echo "$ERR_OUT2" | grep -F "[MemoryRejection]" >/dev/null; then
  echo "FAIL: Output did not contain literal '[MemoryRejection]' for harness scope: $ERR_OUT2" >&2
  exit 1
fi
echo "PASS: record_memory.sh rejected harness scope (exit code $EXIT_CODE2)"

# Test 5C: Valid recording with evidence
REC_OUT="$(bash "$DIR/scripts/record_memory.sh" \
  --title "Hermetic CLI Invariant" \
  --agent "test-cli" \
  --tags "test,cli,hermetic" \
  --scope "shared" \
  --kind "fact" \
  --evidence "commit:12345678" \
  --body "Testing isolated shell script memory creation.")"
echo "$REC_OUT" | grep -F "Recorded memory successfully" >/dev/null

READ_REC="$(bash "$DIR/scripts/read_memory.sh" "hermetic-cli-invariant")"
echo "$READ_REC" | grep -F "commit:12345678" >/dev/null

GREP_REC="$(bash "$DIR/scripts/grep_memories.sh" "Hermetic CLI Invariant")"
echo "$GREP_REC" | grep -F "neutral:" >/dev/null
echo "PASS: record_memory.sh & read_memory.sh (Neutral)"

echo "=== 6. Testing install_symlinks.sh dry-run ==="
SYM_OUT="$(bash "$DIR/scripts/install_symlinks.sh" --dry-run)"
echo "$SYM_OUT" | grep -F "Dry-run complete" >/dev/null
echo "PASS: install_symlinks.sh --dry-run"

echo ""
echo "ALL HERMETIC CLI TESTS PASSED!"
