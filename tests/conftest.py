"""Pytest configuration ensuring hermetic isolation for all test runs."""

import os
from pathlib import Path
import re
import pytest

REAL_HOME = Path.home()


def _get_memory_snapshot() -> dict:
    """Capture snapshot strictly of persistent memory markdown files, ignoring transcripts/logs."""
    snapshot = {}
    real_neutral = REAL_HOME / ".local" / "share" / "agent-memory"
    real_codex = REAL_HOME / ".codex" / "memories"
    real_claude = REAL_HOME / ".claude" / "projects"

    if real_neutral.exists():
        for p in real_neutral.glob("notes/*.md"):
            snapshot[str(p)] = (p.stat().st_mtime_ns, p.stat().st_size)
        idx = real_neutral / "INDEX.md"
        if idx.is_file():
            snapshot[str(idx)] = (idx.stat().st_mtime_ns, idx.stat().st_size)

    if real_codex.exists():
        for p in real_codex.glob("*.md"):
            snapshot[str(p)] = (p.stat().st_mtime_ns, p.stat().st_size)
        for p in real_codex.glob("rollout_summaries/*.md"):
            snapshot[str(p)] = (p.stat().st_mtime_ns, p.stat().st_size)

    if real_claude.exists():
        for p in real_claude.glob("*/memory/*.md"):
            snapshot[str(p)] = (p.stat().st_mtime_ns, p.stat().st_size)

    return snapshot


@pytest.fixture(scope="session", autouse=True)
def guard_real_stores():
    """Verify before and after the test session that no real memory markdown files were touched."""
    snap_before = _get_memory_snapshot()
    yield
    snap_after = _get_memory_snapshot()

    assert snap_before == snap_after, "HERMETICITY VIOLATION: Real memory stores were modified during test run!"


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    """Hermetically isolate environment by pointing HOME and XDG to tmp_path with mock stores."""
    # 1. Override home and XDG
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    fake_xdg = fake_home / ".local" / "share"
    fake_xdg.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake_xdg))

    # 2. Clear any host environment variables
    for var in [
        "AMB_CLAUDE_PROJECTS_DIR",
        "AMB_CODEX_DIR",
        "AMB_NEUTRAL_DIR",
        "MEMORY_DIR",
        "CODEX_MEMORY_DIR",
        "NEUTRAL_MEMORY_DIR",
        "CLAUDECODE",
    ]:
        monkeypatch.delenv(var, raising=False)

    # 3. Assert isolation
    assert Path.home() != REAL_HOME
    assert Path.home() == fake_home

    # 4. Populate mock Claude store
    claude_projects = fake_home / ".claude" / "projects"
    prefix = re.sub(r"[^A-Za-z0-9]", "-", str(fake_home))
    # Global project
    global_mem = claude_projects / prefix / "memory"
    global_mem.mkdir(parents=True, exist_ok=True)
    (global_mem / "MEMORY.md").write_text("# Global Claude Memories\n- Index of global notes\n", encoding="utf-8")
    (global_mem / "webapp_project.md").write_text("# Webapp Project\nWebapp deployed on staging with RTX 3060 GPU.\n", encoding="utf-8")
    (global_mem / "npm_global_prefix.md").write_text("Prefix is ~/.local\n", encoding="utf-8")

    # Subproject: Projects-webapp
    sub_mem = claude_projects / f"{prefix}-Projects-webapp" / "memory"
    sub_mem.mkdir(parents=True, exist_ok=True)
    (sub_mem / "MEMORY.md").write_text("# Webapp Memory\n- Subproject local memory\n", encoding="utf-8")
    (sub_mem / "rules.md").write_text("Rules for webapp project.\n", encoding="utf-8")

    # Subproject: global (testing collision guard)
    impostor_mem = claude_projects / f"{prefix}-global" / "memory"
    impostor_mem.mkdir(parents=True, exist_ok=True)
    (impostor_mem / "secret.md").write_text("IMPOSTOR from ~/global\n", encoding="utf-8")

    # 5. Populate mock Codex store
    codex_dir = fake_home / ".codex" / "memories"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "memory_summary.md").write_text("# Codex Memory Summary\nShared rollout summaries.\n", encoding="utf-8")
    (codex_dir / "MEMORY.md").write_text("# Codex Root Memory\nCore rules.\n", encoding="utf-8")
    rollouts = codex_dir / "rollout_summaries"
    rollouts.mkdir(parents=True, exist_ok=True)
    (rollouts / "webapp_agent_corrections.md").write_text("Webapp corrections summary from Codex.\n", encoding="utf-8")

    # 6. Populate mock Neutral store
    neutral_notes = fake_xdg / "agent-memory" / "notes"
    neutral_notes.mkdir(parents=True, exist_ok=True)
    (neutral_notes / "2026-10-21-antigravity-engineering-invariants.md").write_text(
        "---\n"
        "title: \"Antigravity Engineering Invariants\"\n"
        "date: \"2026-10-21T15:42:00+02:00\"\n"
        "agent: \"antigravity\"\n"
        "tags: [invariants, grounding, testing]\n"
        "scope: \"shared\"\n"
        "kind: \"convention\"\n"
        "evidence: \"user:instruction_2026-10-21\"\n"
        "---\n\n"
        "Invariants grounding before action and zero fallback silent.\n",
        encoding="utf-8",
    )
    (fake_xdg / "agent-memory" / "INDEX.md").write_text(
        "# Agent Neutral Memory Index\n\n"
        "| Date | Title | Agent | Tags | File |\n"
        "| :--- | :---- | :---- | :--- | :--- |\n"
        "| 2026-10-21 | Antigravity Engineering Invariants | antigravity | invariants, grounding, testing | [notes/2026-10-21-antigravity-engineering-invariants.md](notes/2026-10-21-antigravity-engineering-invariants.md) |\n",
        encoding="utf-8",
    )

    return fake_home
