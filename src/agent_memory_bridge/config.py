"""Configuration and store resolution for Agent Memory Bridge."""

import os
from pathlib import Path
import re


def get_claude_projects_dir() -> Path:
    """Return path to Claude Code projects directory."""
    custom = os.environ.get("AMB_CLAUDE_PROJECTS_DIR")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".claude" / "projects"


def get_claude_memory_dir() -> Path:
    """Return path to global Claude Code memory directory."""
    legacy = os.environ.get("MEMORY_DIR")
    if legacy:
        return Path(legacy).expanduser()
    prefix = re.sub(r"[^A-Za-z0-9]", "-", str(Path.home()))
    return get_claude_projects_dir() / prefix / "memory"


def get_codex_memory_dir() -> Path:
    """Return path to Codex memory directory."""
    custom = os.environ.get("AMB_CODEX_DIR") or os.environ.get("CODEX_MEMORY_DIR")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".codex" / "memories"


def get_neutral_memory_dir() -> Path:
    """Return path to neutral agent memory directory (XDG standard)."""
    custom = os.environ.get("AMB_NEUTRAL_DIR") or os.environ.get("NEUTRAL_MEMORY_DIR")
    if custom:
        return Path(custom).expanduser()
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data).expanduser() / "agent-memory"
    return Path.home() / ".local" / "share" / "agent-memory"


def get_neutral_notes_dir(create: bool = False) -> Path:
    """Return path to neutral memory notes subdirectory without side effects unless create=True."""
    d = get_neutral_memory_dir() / "notes"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def get_neutral_index_file(create: bool = False) -> Path:
    """Return path to neutral memory index markdown file without side effects unless create=True."""
    p = get_neutral_memory_dir() / "INDEX.md"
    if create and not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# Agent Neutral Memory Index\n\n"
            "Shared persistent memory for non-vendor agents (Antigravity, Pi, CLI tools).\n"
            "Individual notes are stored in `notes/` with YAML frontmatter.\n\n"
            "| Date | Title | Agent | Tags | Scope | Kind | Evidence | File |\n"
            "| :--- | :---- | :---- | :--- | :---- | :--- | :------- | :--- |\n",
            encoding="utf-8",
        )
    return p
