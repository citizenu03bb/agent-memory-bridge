"""Unit and integration tests for core memory operations under hermetic isolation."""

from pathlib import Path
import pytest

from agent_memory_bridge.core import (
    AmbiguousMemoryError,
    MemoryNotFoundError,
    build_catalog,
    discover_claude_projects,
    get_current_claude_project,
    list_memories,
    parse_frontmatter,
    read_memory,
    rebuild_neutral_index,
    record_memory,
    resolve_memory_path,
    search_memories,
    serialize_frontmatter,
)


def test_discover_claude_projects():
    projects = discover_claude_projects()
    assert "global" in projects
    assert "Projects-webapp" in projects


def test_build_catalog_reserved_names():
    catalog = build_catalog()
    assert "claude:global/webapp_project" in catalog
    assert "claude:Projects-webapp/rules" in catalog
    assert "claude:webapp/rules" in catalog  # Short alias
    assert "codex:memory_summary" in catalog
    assert "codex:rollout/webapp_agent_corrections" in catalog
    assert "neutral:2026-10-21-antigravity-engineering-invariants" in catalog

    # Ensure no subproject named 'global' took over claude:global
    assert "claude:@global/secret" in catalog
    assert "claude:global/secret" not in catalog


def test_list_memories_live_sync():
    res = list_memories()
    assert "=== CLAUDE CODE MEMORIES ===" in res
    assert "=== CODEX SHARED MEMORIES ===" in res
    assert "=== NEUTRAL AGENT MEMORIES" in res
    assert "Antigravity Engineering Invariants" in res
    assert "user:instruction_2026-10-21" in res


def test_list_memories_claudecode_masking(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDECODE", "1")
    fake_webapp_cwd = tmp_path / "home" / "Projects" / "webapp"
    fake_webapp_cwd.mkdir(parents=True, exist_ok=True)

    res = list_memories(cwd=fake_webapp_cwd)
    # Global memory must remain visible
    assert "global" in res
    # Current project memory must be masked
    assert "(Active project memory auto-loaded by Claude Code)" in res


def test_search_memories_literal_and_regex():
    # Literal search
    res = search_memories("RTX 3060 GPU")
    assert "claude:global/webapp_project" in res
    assert "Webapp deployed on staging with RTX 3060 GPU." in res

    # Regex search
    res_regex = search_memories(r"RTX \d+ GPU", regex=True)
    assert "claude:global/webapp_project" in res_regex

    # Case sensitive search
    assert "No matches found" in search_memories("rtx 3060 gpu", case_sensitive=True)


def test_search_memories_deduplication():
    # Searching for Webapp should only match each physical file once, not duplicate for aliases
    res = search_memories("Webapp")
    lines = [line for line in res.splitlines() if "webapp_agent_corrections" in line]
    assert len(lines) == 1


def test_read_memory_qualified_and_aliases():
    content = read_memory("claude:global/webapp_project")
    assert "Webapp deployed on staging" in content

    content_sub = read_memory("claude:webapp/rules")
    assert "Rules for webapp project." in content_sub

    content_codex = read_memory("codex:rollout/webapp_agent_corrections")
    assert "Webapp corrections summary from Codex." in content_codex

    content_neutral = read_memory("neutral:2026-10-21-antigravity-engineering-invariants")
    assert "Invariants grounding before action" in content_neutral


def test_qualified_id_requires_exact_match():
    # Prefix lookup on qualified ID must fail
    with pytest.raises(MemoryNotFoundError):
        read_memory("neutral:2026-10")


def test_read_memory_naked_slug_order(tmp_path):
    assert "Webapp deployed on staging" in read_memory("webapp_project")
    assert "Webapp corrections summary" in read_memory("webapp_agent_corrections")
    assert "Invariants grounding" in read_memory("antigravity-engineering-invariants")


def test_read_memory_errors():
    with pytest.raises(MemoryNotFoundError):
        read_memory("non_existent_memory_slug_12345")

    with pytest.raises(ValueError):
        read_memory("")


def test_frontmatter_pyyaml_handling():
    # Title with dashes and block-list tags
    raw = (
        "---\n"
        "title: Project A --- B Invariants\n"
        "date: 2026-10-21T12:00:00Z\n"
        "agent: antigravity\n"
        "tags:\n"
        "  - alpha\n"
        "  - beta\n"
        "scope: shared\n"
        "kind: fact\n"
        "evidence: 'file:src/main.py#10'\n"
        "---\n\n"
        "Body content here.\n"
    )
    meta, body = parse_frontmatter(raw)
    assert meta["title"] == "Project A --- B Invariants"
    assert meta["tags"] == ["alpha", "beta"]
    assert meta["evidence"] == "file:src/main.py#10"
    assert body.strip() == "Body content here."

    serialized = serialize_frontmatter(meta, body)
    meta2, body2 = parse_frontmatter(serialized)
    assert meta2["title"] == meta["title"]
    assert meta2["tags"] == meta["tags"]
    assert body2.strip() == "Body content here."


def test_record_memory_evidence_bound_rejections():
    # Rejection: missing evidence
    with pytest.raises(ValueError) as excinfo1:
        record_memory(
            title="Model Workaround",
            content="Penser a write_to_file",
            scope="shared",
            evidence=None,
        )
    assert "[MemoryRejection]" in str(excinfo1.value)

    # Rejection: empty prefix payload
    with pytest.raises(ValueError) as excinfo2:
        record_memory(
            title="Model Workaround",
            content="Penser a write_to_file",
            scope="shared",
            evidence="user:",
        )
    assert "[MemoryRejection]" in str(excinfo2.value)

    # Rejection: invalid commit hash
    with pytest.raises(ValueError) as excinfo3:
        record_memory(
            title="Model Workaround",
            content="Penser a write_to_file",
            scope="shared",
            evidence="commit:not_a_hex",
        )
    assert "[MemoryRejection]" in str(excinfo3.value)

    # Rejection: invalid file evidence without path and line number
    with pytest.raises(ValueError) as excinfo_file:
        record_memory(
            title="Model Workaround",
            content="Penser a write_to_file",
            scope="shared",
            evidence="file:#",
        )
    assert "[MemoryRejection]" in str(excinfo_file.value)

    # Rejection: file without line number
    with pytest.raises(ValueError) as excinfo_noline:
        record_memory(
            title="Model Workaround",
            content="Penser a write_to_file",
            scope="shared",
            evidence="file:src/core.py",
        )
    assert "[MemoryRejection]" in str(excinfo_noline.value)

    # Rejection: legacy: evidence is strictly forbidden for new records
    with pytest.raises(ValueError) as excinfo_legacy:
        record_memory(
            title="Model Workaround",
            content="Trying to use legacy prefix directly",
            scope="shared",
            evidence="legacy:trust_me_bro",
        )
    assert "[MemoryRejection]" in str(excinfo_legacy.value)
    assert "réservé à la migration" in str(excinfo_legacy.value)


def test_record_memory_native_agent_bypass_rejection():
    # Block long names, hyphenated names, compound names, and short model IDs
    blocked_agents = [
        "claude", "claude_code", "claude-code", "claudecode",
        "gpt4o", "gpt-4o", "chatgpt", "opus-4", "opus4",
        "codex_cli", "codex-cli", "codexbot",
        "o1", "o1preview", "o1-mini", "o3mini", "o3-mini", "o4", "4o"
    ]
    for agent in blocked_agents:
        with pytest.raises(ValueError) as excinfo:
            record_memory(
                title="Bypass Note",
                content="Testing native agent bypass attempt.",
                agent=agent,
                evidence="commit:12345678",
            )
        assert "native persistent memory" in str(excinfo.value)

    # Verify non-native agents are allowed without false positives on substrings
    from agent_memory_bridge.core import is_native_memory_agent
    assert not is_native_memory_agent("antigravity")
    assert not is_native_memory_agent("pi")
    assert not is_native_memory_agent("open-code")
    assert not is_native_memory_agent("pro1")
    assert not is_native_memory_agent("octopus")
    assert not is_native_memory_agent("photo")


def test_record_memory_success_and_atomic_index():
    res = record_memory(
        title="Production Invariant Data Mount",
        content="The external SSD is mounted at /mnt/data.",
        agent="antigravity",
        tags=["hardware", "mount", "ssd"],
        scope="shared",
        kind="fact",
        evidence="file:/etc/fstab#12",
    )

    assert res["status"] == "success"
    assert Path(res["file"]).is_file()
    assert "production-invariant-data-mount" in res["filename"]
    assert res["evidence"] == "file:/etc/fstab#12"

    body = read_memory(res["filename"])
    assert "/mnt/data" in body
    assert "file:/etc/fstab#12" in body

    listed = list_memories()
    assert "Production Invariant Data Mount" in listed
    assert "file:/etc/fstab#12" in listed


def test_rebuild_neutral_index_robustness(tmp_path):
    from agent_memory_bridge.core import get_neutral_notes_dir
    notes_dir = get_neutral_notes_dir(create=True)

    # 1. Note with numeric tags
    (notes_dir / "2026-10-21-numeric-tags.md").write_text(
        "---\n"
        "title: Numeric Tags Note\n"
        "date: 2026-10-21T12:00:00Z\n"
        "agent: antigravity\n"
        "tags: [2026, ops]\n"
        "scope: shared\n"
        "kind: fact\n"
        "evidence: 'file:src/main.py#10'\n"
        "---\n\n"
        "Body content.\n",
        encoding="utf-8",
    )

    # 2. Note with broken frontmatter
    (notes_dir / "2026-10-21-broken-note.md").write_text(
        "---\ntitle: [unclosed\n---\nBroken body\n",
        encoding="utf-8",
    )

    idx_file = rebuild_neutral_index()
    idx_content = idx_file.read_text(encoding="utf-8")
    assert "Numeric Tags Note" in idx_content
    assert "2026, ops" in idx_content
    assert "2026-10-21-broken-note" in idx_content  # Rendered fallback row


def test_search_capped_display():
    from agent_memory_bridge.core import get_neutral_notes_dir
    notes_dir = get_neutral_notes_dir(create=True)

    # Create 25 matching notes in neutral store
    for i in range(25):
        (notes_dir / f"2026-10-21-match-{i}.md").write_text(
            f"---\ntitle: Match Note {i}\nevidence: 'file:src/m.py#{i+1}'\n---\nUniqueKeywordFoobar\n",
            encoding="utf-8",
        )

    out = search_memories("UniqueKeywordFoobar")
    # Must report accurate total count and capped display
    assert "(showing 20 of 25 matches)" in out


def test_cli_migrate(tmp_path):
    import stat
    import time
    from agent_memory_bridge.cli import main
    from agent_memory_bridge.core import get_neutral_notes_dir

    notes_dir = get_neutral_notes_dir(create=True)

    # 1. Target note with invalid evidence (missing #line) and frontmatter comment
    target_note = notes_dir / "2026-10-21-legacy-note.md"
    target_note.write_text(
        "---\n"
        "# Comment preserved\n"
        "title: Legacy Note\n"
        "date: 2026-10-21T12:00:00+02:00\n"
        "evidence: file:src/a.py\n"
        "---\r\n"
        "Legacy body with CRLF\r\nline 2\r\n",
        encoding="utf-8",
    )
    target_note.chmod(0o600)

    # 2. BOM note
    bom_note = notes_dir / "2026-10-21-bom-note.md"
    bom_note.write_text(
        "\ufeff---\ntitle: BOM Note\n---\nBOM body\n",
        encoding="utf-8",
    )

    # 3. Malformed note
    malformed_note = notes_dir / "2026-10-21-malformed.md"
    malformed_note.write_text(
        "---\ntitle: [broken\n---\nBody\n",
        encoding="utf-8",
    )

    # 4. Valid note that must be left completely untouched
    valid_note = notes_dir / "2026-10-21-valid-note.md"
    valid_content = (
        "---\n"
        "title: Valid Note\n"
        "date: 2026-10-21T10:00:00+02:00\n"
        "agent: antigravity\n"
        "tags: [ops]\n"
        "scope: shared\n"
        "kind: fact\n"
        "evidence: 'file:src/main.py#42'\n"
        "---\n"
        "Valid body\n"
    )
    valid_note.write_text(valid_content, encoding="utf-8")
    time.sleep(0.01)
    valid_mtime_before = valid_note.stat().st_mtime_ns

    # 5. Note with empty evidence (None)
    none_note = notes_dir / "2026-10-21-none-note.md"
    none_note.write_text(
        "---\n"
        "title: None Note\n"
        "evidence:\n"
        "---\n"
        "Body\n",
        encoding="utf-8",
    )

    # 6. Note with valid uncanonicalized commit
    canon_note = notes_dir / "2026-10-21-canon-note.md"
    canon_note.write_text(
        "---\n"
        "title: Canon Note\n"
        "scope: shared\n"
        "kind: fact\n"
        "evidence: commit:ABCDEF0\n"
        "---\n"
        "Body\n",
        encoding="utf-8",
    )

    exit_code = main(["migrate", "--apply"])
    assert exit_code == 0

    # Verification 1: Valid note untouched (exact mtime and byte content)
    assert valid_note.stat().st_mtime_ns == valid_mtime_before
    assert valid_note.read_text(encoding="utf-8") == valid_content

    # Verification 2: Target note updated with honest legacy evidence preserving original pointer
    assert stat.S_IMODE(target_note.stat().st_mode) == 0o600
    updated_content = target_note.read_bytes().decode("utf-8")
    assert "legacy:pre_bridge_unverified (was: file:src/a.py)" in updated_content
    assert "# Comment preserved" in updated_content
    assert "date: 2026-10-21T12:00:00+02:00" in updated_content
    assert "\r\nline 2\r\n" in updated_content
    assert "scope: shared" in updated_content
    assert "kind: fact" in updated_content

    # Verification 3: BOM note parsed and written cleanly without double frontmatter
    bom_content = bom_note.read_text(encoding="utf-8")
    assert not bom_content.startswith("\ufeff")
    assert bom_content.count("---") == 2
    assert "BOM Note" in bom_content

    # Verification 4: Malformed note left unchanged
    assert malformed_note.read_text(encoding="utf-8") == "---\ntitle: [broken\n---\nBody\n"

    # Verification 5: None evidence note never produces '(was: None)'
    none_content = none_note.read_text(encoding="utf-8")
    assert "legacy:pre_bridge_unverified" in none_content
    assert "(was: None)" not in none_content

    # Verification 6: Canonicalization of commit hash executed
    canon_content = canon_note.read_text(encoding="utf-8")
    assert "commit:abcdef0" in canon_content

    # Verification 7: Second run is strictly idempotent (0 updates)
    exit_code_2 = main(["migrate", "--apply"])
    assert exit_code_2 == 0


def test_validate_evidence_canonicalization():
    from agent_memory_bridge.core import validate_evidence
    assert validate_evidence("file:  src/main.py#10") == "file:src/main.py#10"
    assert validate_evidence("file:  src/main.py#L42") == "file:src/main.py#42"
    assert validate_evidence("commit:  ABC1234") == "commit:abc1234"
    assert validate_evidence("user:   please do this") == "user:please do this"
    assert validate_evidence("legacy:  pre_bridge_note", allow_legacy=True) == "legacy:pre_bridge_note"

    # Padded evidence with length < 5 after strip MUST raise ValueError
    with pytest.raises(ValueError):
        validate_evidence("user:     ab")

    with pytest.raises(ValueError):
        validate_evidence("legacy:     ab", allow_legacy=True)


def test_patch_frontmatter_ast_robustness():
    from agent_memory_bridge.core import patch_frontmatter, parse_frontmatter

    # 1. Values with apostrophes, multiline list, and block scalar
    raw_md = (
        "---\n"
        "# Top comment\n"
        "title: AST Test\n"
        "date: 2026-10-21T12:00:00+02:00\n"
        "description: |\n"
        "  kind: this is prose and must stay untouched\n"
        "source:\n"
        "  evidence: nested_evidence_must_stay\n"
        "evidence:\n"
        "  - old_item_1\n"
        "  - old_item_2\n"
        "---\n"
        "Body content.\n"
    )

    updates = {
        "evidence": "legacy:pre_bridge_unverified (was: don't trust me)",
        "scope": "shared",
        "kind": "fact",
    }

    patched = patch_frontmatter(raw_md, updates)

    # Comments and unaffected fields preserved verbatim
    assert "# Top comment" in patched
    assert "date: 2026-10-21T12:00:00+02:00" in patched
    assert "kind: this is prose and must stay untouched" in patched
    assert "nested_evidence_must_stay" in patched

    # Valid YAML load
    meta, body = parse_frontmatter(patched)
    assert meta["evidence"] == "legacy:pre_bridge_unverified (was: don't trust me)"
    assert meta["scope"] == "shared"
    assert meta["kind"] == "fact"
    assert meta["source"]["evidence"] == "nested_evidence_must_stay"
    assert "Body content." in body


def test_get_current_claude_project_reserved_global(monkeypatch):
    import agent_memory_bridge.core as core_mod

    monkeypatch.setattr(
        core_mod,
        "discover_claude_projects",
        lambda: {"global": Path("/fake/global"), "@global": Path("/fake/@global")},
    )

    home_dir = Path.home().resolve()
    cwd = home_dir / "global" / "subdir"
    detected = core_mod.get_current_claude_project(cwd=cwd)
    assert detected == "@global"
