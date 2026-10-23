#!/bin/bash
# Install or update consult-memory symlinks across agent configs.
# Read-Write skill for Antigravity and Pi; Read-Only skill for Claude Code, Codex, and .agents.
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_RW="$REPO_DIR/skill"
SKILL_RO="$REPO_DIR/skill-readonly"

TARGETS_RW=(
  "$HOME/.gemini/config/skills/consult-memory"
  "$HOME/.gemini/skills/consult-memory"
  "$HOME/.pi/agent/skills/consult-memory"
)

TARGETS_RO=(
  "$HOME/.claude/skills/consult-memory"
  "$HOME/.codex/skills/consult-memory"
  "$HOME/.agents/skills/consult-memory"
)

APPLY=false
BACKUP_DIR="$HOME/.local/share/agent-memory/symlink-backups/$(date +%Y%m%d_%H%M%S)"

for arg in "$@"; do
  case "$arg" in
    --apply)
      APPLY=true
      ;;
    --dry-run)
      APPLY=false
      ;;
    -h|--help)
      echo "Usage: $0 [--apply | --dry-run]"
      echo "Without --apply, only prints the planned actions (dry-run)."
      exit 0
      ;;
  esac
done

echo "Agent Memory Bridge - Symlink Installer"
echo "Read-Write skill: $SKILL_RW"
echo "Read-Only skill:  $SKILL_RO"
echo "Mode: $( [ "$APPLY" = true ] && echo "APPLY" || echo "DRY-RUN (use --apply to execute)" )"
echo ""

if [ ! -f "$SKILL_RW/SKILL.md" ]; then
  echo "Error: Read-write skill not found at $SKILL_RW/SKILL.md" >&2
  exit 1
fi

if [ ! -f "$SKILL_RO/SKILL.md" ]; then
  echo "Error: Read-only skill not found at $SKILL_RO/SKILL.md" >&2
  exit 1
fi

_install_target() {
  local target="$1"
  local source_dir="$2"
  local label="$3"
  local target_parent="$(dirname "$target")"

  echo "Target ($label): $target"
  if [ -L "$target" ]; then
    current_dest="$(readlink "$target")"
    echo "  Current symlink -> $current_dest"
  elif [ -e "$target" ]; then
    echo "  Current path exists (not a symlink)"
  else
    echo "  Current path does not exist yet"
  fi

  if [ "$APPLY" = true ]; then
    mkdir -p "$target_parent"
    if [ -e "$target" ] || [ -L "$target" ]; then
      mkdir -p "$BACKUP_DIR"
      safe_backup_name="$(echo "$target" | sed 's|^/||; s|/|_|g')"
      cp -P "$target" "$BACKUP_DIR/$safe_backup_name" 2>/dev/null || true
      rm -f "$target"
    fi
    ln -s "$source_dir" "$target"
    echo "  -> Linked to $source_dir"
  else
    echo "  [Dry-run] Would link $target -> $source_dir"
  fi
  echo ""
}

echo "=== 1. Read-Write Targets (Antigravity, Pi) ==="
for target in "${TARGETS_RW[@]}"; do
  _install_target "$target" "$SKILL_RW" "Read-Write"
done

echo "=== 2. Read-Only Targets (Claude Code, Codex, Shared Agents) ==="
for target in "${TARGETS_RO[@]}"; do
  _install_target "$target" "$SKILL_RO" "Read-Only"
done

if [ "$APPLY" = true ]; then
  echo "All symlinks successfully updated."
  if [ -d "$BACKUP_DIR" ]; then
    echo "Backups saved to $BACKUP_DIR"
  fi
else
  echo "Dry-run complete. Run with --apply to perform the changes."
fi
