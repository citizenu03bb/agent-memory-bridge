"""Core operations for querying, reading, and recording memories across agents."""

import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml

from .config import (
    get_claude_projects_dir,
    get_codex_memory_dir,
    get_neutral_index_file,
    get_neutral_memory_dir,
    get_neutral_notes_dir,
)


class AmbiguousMemoryError(Exception):
    """Raised when a memory slug matches multiple candidates."""
    pass


class MemoryNotFoundError(Exception):
    """Raised when a requested memory slug cannot be resolved."""
    pass


# ---------------------------------------------------------------------------
# Claude Project Discovery
# ---------------------------------------------------------------------------

RESERVED_NAMES: Set[str] = {"global", "codex", "neutral", "shared", "claude"}


def get_encoded_home_prefix() -> str:
    """Return the filesystem-safe encoded HOME prefix used by Claude Code."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path.home().resolve()))


def normalize_claude_project_key(sub_part: str) -> str:
    """Normalize subproject key, prefixing reserved names with '@' to prevent alias collisions."""
    return f"@{sub_part}" if sub_part in RESERVED_NAMES else sub_part


def discover_claude_projects() -> Dict[str, Path]:
    """
    Discover valid Claude Code project memory directories.
    Returns a dict mapping project identifiers to their memory directory.
    - 'global' corresponds to the home project (e.g. -home-alice).
    - Subprojects are keyed by their relative project suffix.
    - Subprojects matching reserved names are prefixed with '@' (e.g. '@global')
      to prevent collision with the reserved 'global' alias.
    """
    projects_dir = get_claude_projects_dir()
    if not projects_dir.is_dir():
        return {}

    prefix = get_encoded_home_prefix()
    discovered: Dict[str, Path] = {}

    for d in sorted(projects_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name

        # Global project match
        if name == prefix:
            mem_dir = d / "memory"
            if mem_dir.is_dir() and any(mem_dir.glob("*.md")):
                discovered["global"] = mem_dir
            continue

        # Subprojects must begin with prefix + "-"
        if not name.startswith(prefix + "-"):
            continue

        sub_part = name[len(prefix) + 1:]
        # Exclude hidden, scratch, or tmp subprojects
        if sub_part.startswith("-") or "-tmp-" in sub_part or "scratch" in sub_part.lower():
            continue

        mem_dir = d / "memory"
        if not mem_dir.is_dir() or not any(mem_dir.glob("*.md")):
            continue

        # Protect reserved names by prefixing with '@'
        key = normalize_claude_project_key(sub_part)
        discovered[key] = mem_dir

    return discovered


def get_current_claude_project(cwd: Optional[Path] = None) -> Optional[str]:
    """Detect if the given cwd (default: Path.cwd()) corresponds to a known Claude project."""
    target_cwd = (cwd or Path.cwd()).resolve()
    projects = discover_claude_projects()
    prefix = get_encoded_home_prefix()

    curr = target_cwd
    while True:
        encoded_curr = re.sub(r"[^A-Za-z0-9]", "-", str(curr))
        if encoded_curr == prefix and "global" in projects:
            return "global"
        if encoded_curr.startswith(prefix + "-"):
            proj_suffix = encoded_curr[len(prefix) + 1:]
            candidate_key = normalize_claude_project_key(proj_suffix)
            if candidate_key in projects:
                return candidate_key

        if curr.parent == curr:
            break
        curr = curr.parent

    return None


# ---------------------------------------------------------------------------
# Catalog Enumeration & Resolution
# ---------------------------------------------------------------------------

def build_catalog() -> Dict[str, Path]:
    """
    Exhaustively enumerate all existing memory files across stores.
    Builds a dictionary mapping qualified IDs to their absolute Path.
    Path traversal is impossible by construction because paths come from filesystem scans.
    """
    catalog: Dict[str, Path] = {}

    # 1. Claude Code
    claude_projects = discover_claude_projects()
    # Compute safe short aliases (must not collide with reserved names or duplicate)
    short_aliases: Dict[str, str] = {}
    alias_counts: Dict[str, int] = {}
    for p_name in claude_projects:
        if p_name != "global" and not p_name.startswith("@"):
            alias = p_name.split("-")[-1]
            if alias not in RESERVED_NAMES:
                alias_counts[alias] = alias_counts.get(alias, 0) + 1

    for p_name in claude_projects:
        if p_name != "global" and not p_name.startswith("@"):
            alias = p_name.split("-")[-1]
            if alias not in RESERVED_NAMES and alias_counts.get(alias) == 1:
                short_aliases[p_name] = alias

    for proj_id, mem_dir in claude_projects.items():
        for f in sorted(mem_dir.glob("*.md")):
            slug = f.stem
            catalog[f"claude:{proj_id}/{slug}"] = f
            if proj_id in short_aliases:
                alias_key = f"claude:{short_aliases[proj_id]}/{slug}"
                if alias_key not in catalog:
                    catalog[alias_key] = f

    # 2. Codex
    codex_dir = get_codex_memory_dir()
    if codex_dir.is_dir():
        for f in sorted(codex_dir.glob("*.md")):
            catalog[f"codex:{f.stem}"] = f
        rollouts = codex_dir / "rollout_summaries"
        if rollouts.is_dir():
            for f in sorted(rollouts.glob("*.md")):
                catalog[f"codex:rollout/{f.stem}"] = f

    # 3. Neutral Store
    neutral_notes = get_neutral_notes_dir(create=False)
    if neutral_notes.is_dir():
        for f in sorted(neutral_notes.glob("*.md")):
            catalog[f"neutral:{f.stem}"] = f

    return catalog


def resolve_memory_path(slug: str, cwd: Optional[Path] = None) -> Tuple[str, Path]:
    """
    Resolve a qualified ID or naked slug to its canonical identifier and Path.
    Applies strict total order:
    1. Exact match in cwd project
    2. Exact match in global Claude store
    3. Exact match in ANY store (Neutral, Codex, Claude subprojects)
    4. Unique substring/partial match across stores
    5. Otherwise raises AmbiguousMemoryError or MemoryNotFoundError.
    """
    if not slug or not slug.strip():
        raise ValueError("Slug cannot be empty.")

    clean_slug = slug.strip()
    if clean_slug.endswith(".md"):
        clean_slug = clean_slug[:-3]

    catalog = build_catalog()

    # Case A: Explicitly qualified ID (must be exact)
    if ":" in clean_slug:
        if clean_slug in catalog:
            return clean_slug, catalog[clean_slug]
        raise MemoryNotFoundError(f"Memory not found for qualified identifier '{slug}'.")

    # Case B: Naked slug resolution
    # 1. Exact match in cwd project
    current_proj = get_current_claude_project(cwd)
    if current_proj:
        cwd_key = f"claude:{current_proj}/{clean_slug}"
        if cwd_key in catalog:
            return cwd_key, catalog[cwd_key]

    # 2. Exact match in global Claude store
    global_key = f"claude:global/{clean_slug}"
    if global_key in catalog:
        return global_key, catalog[global_key]

    # 3. Exact match in ANY store (Neutral, Codex root, Codex rollouts, other Claude projects)
    exact_candidates: Dict[Path, str] = {}
    for k, p in catalog.items():
        base_slug = k.split(":")[-1].split("/")[-1]
        if base_slug == clean_slug:
            if p not in exact_candidates:
                exact_candidates[p] = k

    if len(exact_candidates) == 1:
        chosen_key = list(exact_candidates.values())[0]
        return chosen_key, catalog[chosen_key]
    if len(exact_candidates) > 1:
        raise AmbiguousMemoryError(
            f"Ambiguous memory slug '{slug}'. Matching exact candidates: {sorted(exact_candidates.values())}"
        )

    # 4. Partial substring match across all stores
    sub_candidates: Dict[Path, str] = {}
    target_lower = clean_slug.lower()
    for k, p in catalog.items():
        if target_lower in p.stem.lower():
            if p not in sub_candidates:
                sub_candidates[p] = k

    if len(sub_candidates) == 1:
        chosen_key = list(sub_candidates.values())[0]
        return chosen_key, catalog[chosen_key]
    if len(sub_candidates) > 1:
        raise AmbiguousMemoryError(
            f"Ambiguous memory slug '{slug}'. Matching candidates: {sorted(list(sub_candidates.values())[:10])}"
        )

    raise MemoryNotFoundError(
        f"Memory not found for slug '{slug}'. Use list_memories or search_memories to find available slugs."
    )


def read_memory(slug: str, cwd: Optional[Path] = None) -> str:
    """Read the full content of a memory file by slug or qualified ID."""
    _, path = resolve_memory_path(slug, cwd=cwd)
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter Parsing & Serialization (Standard PyYAML)
# ---------------------------------------------------------------------------

FRONTMATTER_REGEX = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", re.DOTALL)


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse frontmatter safely using standard PyYAML parser, stripping BOM if present."""
    clean_content = content.lstrip("\ufeff")
    match = FRONTMATTER_REGEX.match(clean_content)
    if not match:
        return {}, clean_content

    fm_raw = match.group(1)
    body = match.group(2).lstrip("\r\n")

    try:
        data = yaml.safe_load(fm_raw)
        if isinstance(data, dict):
            return data, body
    except Exception:
        pass

    return {}, clean_content


def serialize_frontmatter(meta: Dict[str, Any], body: str) -> str:
    """Serialize frontmatter using standard PyYAML dumper."""
    fm_str = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_str}\n---\n\n{body.strip()}\n"


def patch_frontmatter(content: str, updates: Dict[str, str]) -> str:
    """
    Patch specific keys in a Markdown file's YAML frontmatter using AST-level span replacement.
    Preserves existing formatting, comments, untouched keys, line endings, BOM, and body text verbatim.
    """
    has_bom = content.startswith("\ufeff")
    clean_content = content.lstrip("\ufeff")

    if not clean_content.startswith("---"):
        raise ValueError("Cannot patch content without YAML frontmatter opening delimiter.")

    lines = clean_content.splitlines(True)
    if len(lines) < 2 or not lines[0].startswith("---"):
        raise ValueError("Invalid frontmatter start delimiter.")

    end_idx = None
    offset = len(lines[0])
    for line in lines[1:]:
        if line.startswith("---"):
            end_idx = offset
            break
        offset += len(line)

    if end_idx is None:
        raise ValueError("Cannot patch content without YAML frontmatter closing delimiter.")

    fm_raw = clean_content[len(lines[0]):end_idx]
    body = clean_content[end_idx:]  # Starts with closing delimiter '---...'

    node = yaml.compose(fm_raw)
    node_pairs = []
    if node is not None:
        if isinstance(node, yaml.MappingNode):
            node_pairs = node.value
        else:
            raise ValueError("YAML frontmatter root must be a mapping.")

    spans: Dict[str, Tuple[int, int]] = {}
    for k, v in node_pairs:
        if isinstance(k.value, str) and k.value in updates:
            spans[k.value] = (k.start_mark.index, v.end_mark.index)

    new_fm = fm_raw
    # Replace existing top-level keys in reverse offset order to avoid offset drift
    for key, (start, end) in sorted(spans.items(), key=lambda x: x[1][0], reverse=True):
        val_dump = yaml.safe_dump({key: updates[key]}, default_flow_style=False, width=float("inf")).strip()
        post = new_fm[end:]
        if post and not post.startswith(("\r", "\n")):
            val_dump += "\n"
        new_fm = new_fm[:start] + val_dump + post

    # Append any keys not previously present in frontmatter
    for key, val in updates.items():
        if key not in spans:
            val_dump = yaml.safe_dump({key: val}, default_flow_style=False, width=float("inf")).strip()
            new_fm = new_fm.rstrip("\r\n") + "\n" + val_dump + "\n"

    patched = lines[0] + new_fm + body
    if has_bom:
        patched = "\ufeff" + patched

    # Strict post-patch validation: ensure YAML parses cleanly and matches updates
    test_meta, _ = parse_frontmatter(patched)
    for k, v in updates.items():
        if test_meta.get(k) != v:
            raise ValueError(f"Frontmatter patch validation failed for key '{k}': expected {v!r}, got {test_meta.get(k)!r}")

    return patched


def _escape_cell(val: Any) -> str:
    """Clean and escape cell value for Markdown tables."""
    s = str(val if val is not None else "-").replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    return s.strip() or "-"


def _format_date(val: Any, default: str = "-") -> str:
    """Robust date formatting supporting strings, dates, and datetimes."""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    s = str(val if val is not None else "").strip()
    m = re.match(r"^\d{4}-\d{2}-\d{2}", s)
    if m:
        return m.group(0)
    return default


# ---------------------------------------------------------------------------
# List Memories (Token-Optimized, Real-Time Notes Reading)
# ---------------------------------------------------------------------------

def list_memories(cwd: Optional[Path] = None) -> str:
    """Return a concise overview of Claude, Codex, and Neutral memory stores."""
    sections: List[str] = []
    is_claudecode = os.environ.get("CLAUDECODE") == "1"
    current_proj = get_current_claude_project(cwd) if is_claudecode else None

    # 1. Claude Code Overview
    claude_projects = discover_claude_projects()
    if claude_projects:
        sections.append("=== CLAUDE CODE MEMORIES ===")
        for proj_id, mem_dir in sorted(claude_projects.items()):
            if is_claudecode and proj_id == current_proj and proj_id != "global":
                sections.append(f"- **{proj_id}**: (Active project memory auto-loaded by Claude Code)")
                continue

            md_files = [f.stem for f in sorted(mem_dir.glob("*.md")) if f.name != "MEMORY.md"]
            count = len(md_files) + (1 if (mem_dir / "MEMORY.md").is_file() else 0)
            notes_sample = f" (notes: {', '.join(md_files[:5])}{'...' if len(md_files) > 5 else ''})" if md_files else ""
            sections.append(f"- **{proj_id}** [{mem_dir}]: {count} file(s){notes_sample}")

    # 2. Codex Overview
    codex_dir = get_codex_memory_dir()
    if codex_dir.is_dir():
        sections.append("\n=== CODEX SHARED MEMORIES ===")
        summary_file = codex_dir / "memory_summary.md"
        root_mem = codex_dir / "MEMORY.md"
        rollouts = sorted((codex_dir / "rollout_summaries").glob("*.md")) if (codex_dir / "rollout_summaries").is_dir() else []
        if summary_file.is_file():
            sections.append(f"- Summary: {summary_file}")
        if root_mem.is_file():
            sections.append(f"- Core Memory: {root_mem}")
        if rollouts:
            sample = ", ".join(f.stem for f in rollouts[:5])
            sections.append(f"- Rollouts ({len(rollouts)}): {sample}{'...' if len(rollouts) > 5 else ''}")

    # 3. Neutral Store (Real-Time from notes/*.md)
    neutral_notes_dir = get_neutral_notes_dir(create=False)
    sections.append(f"\n=== NEUTRAL AGENT MEMORIES ({neutral_notes_dir}) ===")
    note_files = sorted(neutral_notes_dir.glob("*.md")) if neutral_notes_dir.is_dir() else []
    if note_files:
        table_lines = [
            "| Date | Title | Agent | Tags | Scope | Kind | Evidence | File |",
            "| :--- | :---- | :---- | :--- | :---- | :--- | :------- | :--- |",
        ]
        for nf in note_files:
            try:
                content = nf.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(content)
                date_str = _format_date(meta.get("date"), default=nf.name[:10])
                date = _escape_cell(date_str)
                title = _escape_cell(meta.get("title", nf.stem))
                agent = _escape_cell(meta.get("agent", "-"))
                tags_val = meta.get("tags", [])
                tags_str = ", ".join(str(t) for t in tags_val) if isinstance(tags_val, list) else str(tags_val)
                tags = _escape_cell(tags_str)
                scope = _escape_cell(meta.get("scope", "shared"))
                kind = _escape_cell(meta.get("kind", "fact"))
                evidence = _escape_cell(meta.get("evidence", "-"))
                table_lines.append(f"| {date} | {title} | {agent} | {tags} | {scope} | {kind} | {evidence} | [notes/{nf.name}](notes/{nf.name}) |")
            except Exception:
                table_lines.append(f"| - | {_escape_cell(nf.stem)} | - | - | - | - | - | [notes/{nf.name}](notes/{nf.name}) |")
        sections.append("\n".join(table_lines))
    else:
        sections.append("(No notes recorded in neutral store)")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Rebuild Neutral INDEX.md (Atomic Temp File + Replace)
# ---------------------------------------------------------------------------

def rebuild_neutral_index() -> Path:
    """Regenerate INDEX.md atomically from actual notes on disk."""
    neutral_dir = get_neutral_memory_dir()
    notes_dir = get_neutral_notes_dir(create=True)
    index_file = get_neutral_index_file(create=True)

    header = (
        "# Agent Neutral Memory Index\n\n"
        "Shared persistent memory for non-vendor agents (Antigravity, Pi, CLI tools).\n"
        "Individual notes are stored in `notes/` with YAML frontmatter.\n\n"
        "| Date | Title | Agent | Tags | Scope | Kind | Evidence | File |\n"
        "| :--- | :---- | :---- | :--- | :---- | :--- | :------- | :--- |\n"
    )

    rows = []
    if notes_dir.is_dir():
        for nf in sorted(notes_dir.glob("*.md")):
            try:
                content = nf.read_text(encoding="utf-8")
                meta, _ = parse_frontmatter(content)
                date_str = _format_date(meta.get("date"), default=nf.name[:10])
                date = _escape_cell(date_str)
                title = _escape_cell(meta.get("title", nf.stem))
                agent = _escape_cell(meta.get("agent", "-"))
                tags_val = meta.get("tags", [])
                tags_str = ", ".join(str(t) for t in tags_val) if isinstance(tags_val, list) else str(tags_val)
                tags = _escape_cell(tags_str)
                scope = _escape_cell(meta.get("scope", "shared"))
                kind = _escape_cell(meta.get("kind", "fact"))
                evidence = _escape_cell(meta.get("evidence", "-"))
                rows.append(f"| {date} | {title} | {agent} | {tags} | {scope} | {kind} | {evidence} | [notes/{nf.name}](notes/{nf.name}) |\n")
            except Exception:
                rows.append(f"| - | {_escape_cell(nf.stem)} | - | - | - | - | - | [notes/{nf.name}](notes/{nf.name}) |\n")

    full_content = header + "".join(rows)

    fd, tmp_path_str = tempfile.mkstemp(dir=neutral_dir, prefix="index_", suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        target_mode = stat.S_IMODE(index_file.stat().st_mode) if index_file.exists() else 0o644
        os.fchmod(fd, target_mode)

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(full_content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, index_file)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    return index_file


# ---------------------------------------------------------------------------
# Record Memory (Evidence-Bound Contract & Atomic Creation)
# ---------------------------------------------------------------------------

def slugify(title: str, max_length: int = 80) -> str:
    """Generate a clean ASCII filesystem slug with length bound and collision hash."""
    clean = unicodedata.normalize("NFKD", title).encode("ASCII", "ignore").decode("ASCII").lower()
    slug = re.sub(r"[^a-z0-9_\-]+", "-", clean).strip("-")
    if not slug:
        slug = "note"

    if len(slug) > max_length:
        h = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
        slug = f"{slug[:max_length - 9]}-{h}"

    return slug


def validate_evidence(evidence: Optional[str], allow_legacy: bool = False) -> str:
    """Validate that evidence is non-empty, backed by a verifiable payload, and canonicalize format."""
    if not evidence or not isinstance(evidence, str):
        raise ValueError(
            "[MemoryRejection] Une note enregistrée dans la mémoire partagée exige une preuve externe vérifiable non-vide. "
            "Formats acceptés:\n"
            "  - 'file:<path>#<line>' (ex: 'file:src/core.py#42', 'file:src/app.py#L10')\n"
            "  - 'commit:<hash>' (hash git d'au moins 7 caractères hexadécimaux, ex: 'commit:56746fb')\n"
            "  - 'user:<instruction>' (directive explicite de l'utilisateur, au moins 5 caractères)\n"
            "  - 'legacy:<provenance>' (réservé exclusivement à la migration de notes historiques)\n"
            "S'il s'agit d'une règle de comportement ou d'auto-discipline de votre modèle/agent, "
            "elle ne doit PAS être enregistrée ici mais consignée dans votre fichier de harnais local "
            "(ex: GEMINI.md, CLAUDE.md, OPENCODE.md, ~/.pi/agent/AGENTS.md)."
        )

    clean_ev = evidence.strip()
    if clean_ev.startswith("file:"):
        match = re.match(r"^file:\s*(.+)#L?([1-9]\d*)$", clean_ev)
        if not match or not match.group(1).strip():
            raise ValueError("[MemoryRejection] 'file:' doit être au format 'file:<path>#<line>' avec un chemin non-vide et un numéro de ligne strictement positif (ex: file:src/db.py#10).")
        return f"file:{match.group(1).strip()}#{match.group(2)}"
    elif clean_ev.startswith("commit:"):
        match = re.match(r"^commit:\s*([0-9a-fA-F]{7,40})$", clean_ev)
        if not match:
            raise ValueError("[MemoryRejection] 'commit:' doit être suivi d'un hash Git hexadécimal valide d'au moins 7 caractères.")
        return f"commit:{match.group(1).lower()}"
    elif clean_ev.startswith("user:"):
        payload = clean_ev[5:].strip()
        if len(payload) < 5 or not re.search(r"[a-zA-Z0-9]", payload):
            raise ValueError("[MemoryRejection] 'user:' doit contenir une instruction utilisateur explicite d'au moins 5 caractères.")
        return f"user:{payload}"
    elif clean_ev.startswith("legacy:"):
        if not allow_legacy:
            raise ValueError(
                "[MemoryRejection] Le format 'legacy:' est strictement réservé à la migration d'anciennes notes historiques. "
                "Les nouveaux enregistrements doivent fournir une preuve externe active ('file:', 'commit:', ou 'user:')."
            )
        payload = clean_ev[7:].strip()
        if len(payload) < 5:
            raise ValueError("[MemoryRejection] 'legacy:' doit contenir une provenance d'au moins 5 caractères.")
        return f"legacy:{payload}"
    else:
        raise ValueError(
            "[MemoryRejection] Préfixe de preuve non reconnu. Utilisez 'file:...#<line>', 'commit:...', ou 'user:...'. "
            "Les règles d'auto-discipline d'agent appartiennent à votre fichier de harnais local."
        )


# Guardrail regex to catch honest mistakes by agents with native memory stores (Claude, Codex, etc.)
NATIVE_AGENT_REGEX = re.compile(
    r"(?:^|[\W_])("
    r"claude(?:[-_]?code)?|"
    r"codex(?:[-_]?(?:cli|bot))?|"
    r"opus(?:[-_]?[0-9]+)?|"
    r"sonnet(?:[-_]?[0-9]+)?|"
    r"haiku(?:[-_]?[0-9]+)?|"
    r"chatgpt|"
    r"gpt(?:[-_]?[0-9a-z]+)?|"
    r"o[134](?:[-_]?[0-9a-z]+)?|"
    r"4o"
    r")(?:$|[\W_])",
    re.IGNORECASE,
)


def is_native_memory_agent(agent_name: Optional[str]) -> bool:
    """
    Guardrail check to prevent honest mistakes by agents with native stores writing to the neutral store.
    Matches Claude, Codex, GPT/o1/o3/o4 agents while avoiding false positives on unrelated words.
    """
    clean = (agent_name or "").strip().lower()
    return bool(NATIVE_AGENT_REGEX.search(clean))


def record_memory(
    title: str,
    content: str,
    agent: str = "antigravity",
    tags: Optional[List[str]] = None,
    scope: str = "shared",
    kind: str = "fact",
    evidence: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record a persistent memory note in the neutral store with structured frontmatter.
    Enforces Evidence-Bound schema across all notes to prevent model introspection from polluting shared memory.
    """
    if not title or not title.strip():
        raise ValueError("Title cannot be empty.")
    if not content or not content.strip():
        raise ValueError("Content cannot be empty.")

    clean_agent = (agent or "antigravity").strip().lower()

    # Reject write bypass attempts from agents with native memory stores
    if is_native_memory_agent(clean_agent):
        raise ValueError(
            f"[MemoryRejection] Agent '{agent}' uses native persistent memory and should not write to neutral store. Use skill-readonly."
        )

    clean_scope = (scope or "shared").strip().lower()
    clean_kind = (kind or "fact").strip().lower()

    # Prohibit harness scope in shared store
    if clean_scope.startswith("harness:"):
        raise ValueError(
            "[MemoryRejection] Le scope 'harness:' est formellement interdit dans la mémoire partagée. "
            "Les règles de modèle et d'auto-discipline doivent être écrites dans votre fichier de harnais local "
            "(ex: GEMINI.md, CLAUDE.md, OPENCODE.md, ~/.pi/agent/AGENTS.md)."
        )

    if clean_scope != "shared" and not re.match(r"^project:[a-zA-Z0-9_\-]+$", clean_scope):
        raise ValueError(f"Invalid scope '{scope}'. Allowed: 'shared' or 'project:<valid_id>'.")

    valid_kinds = {"fact", "preference", "convention"}
    if clean_kind not in valid_kinds:
        raise ValueError(f"Invalid kind '{kind}'. Allowed: {sorted(valid_kinds)}.")

    # All notes in the neutral store MUST be evidence-bound (legacy: forbidden for new notes)
    clean_evidence = validate_evidence(evidence, allow_legacy=False)

    clean_title = title.strip()
    tag_list = [t.strip().lower() for t in (tags or []) if t.strip()]

    now = datetime.now().astimezone()
    date_str = now.strftime("%Y-%m-%d")
    iso_timestamp = now.isoformat(timespec="seconds")

    slug_base = slugify(clean_title, max_length=80)
    notes_dir = get_neutral_notes_dir(create=True)

    meta: Dict[str, Any] = {
        "title": clean_title,
        "date": iso_timestamp,
        "agent": clean_agent,
        "tags": tag_list,
        "scope": clean_scope,
        "kind": clean_kind,
        "evidence": clean_evidence,
    }
    file_body = serialize_frontmatter(meta, content)

    # Atomic creation: reserve filename with O_EXCL, write via tempfile + fsync + replace
    counter = 1
    filename = f"{date_str}-{slug_base}.md"
    note_path = notes_dir / filename

    for attempt in range(10):
        try:
            fd = os.open(str(note_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(fd)
            break
        except FileExistsError:
            counter += 1
            filename = f"{date_str}-{slug_base}-{counter}.md"
            note_path = notes_dir / filename
    else:
        raise FileExistsError(f"Could not allocate unique filename for slug '{slug_base}' after 10 attempts.")

    # Write content atomically to tempfile matching note permissions, then atomic replace
    tmp_fd, tmp_file_str = tempfile.mkstemp(dir=notes_dir, prefix="note_", suffix=".tmp")
    tmp_path = Path(tmp_file_str)
    try:
        target_mode = stat.S_IMODE(note_path.stat().st_mode)
        os.fchmod(tmp_fd, target_mode)

        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(file_body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, note_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        if note_path.exists():
            note_path.unlink()
        raise

    # Rebuild index atomically; if it fails, roll back the note to prevent inconsistency
    try:
        rebuild_neutral_index()
    except Exception:
        if note_path.exists():
            note_path.unlink()
        raise

    return {
        "status": "success",
        "file": str(note_path),
        "filename": filename,
        "title": clean_title,
        "agent": clean_agent,
        "date": iso_timestamp,
        "tags": tag_list,
        "scope": clean_scope,
        "kind": clean_kind,
        "evidence": clean_evidence,
    }


# ---------------------------------------------------------------------------
# Search Memories (Deduplicated Files, Literal by Default, Accurate Count)
# ---------------------------------------------------------------------------

def search_memories(
    query: str,
    case_sensitive: bool = False,
    regex: bool = False,
    max_results: int = 50,
) -> str:
    """
    Search for a text pattern across memory stores.
    Deduplicates files by Path to prevent duplicate results from aliases or rollout keys.
    Accurately counts all matches across all files.
    """
    if not query:
        return "Empty query provided."

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern_str = query if regex else re.escape(query)
    try:
        pattern = re.compile(pattern_str, flags)
    except re.error as e:
        return f"Invalid regex pattern '{query}': {e}"

    catalog = build_catalog()
    # Map physical Path to its primary/canonical qualified ID
    unique_files: Dict[Path, str] = {}
    for k, p in catalog.items():
        if p not in unique_files:
            unique_files[p] = k
        else:
            if "rollout/" in k and "rollout/" not in unique_files[p]:
                unique_files[p] = k

    results: List[str] = []
    total_matches = 0
    matches_per_store: Dict[str, int] = {}

    for path, qualified_id in sorted(unique_files.items(), key=lambda x: x[1]):
        if not path.is_file():
            continue

        store_name = qualified_id.split(":")[0]

        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f, start=1):
                    if pattern.search(line):
                        total_matches += 1
                        # If under global and per-store display limits, record snippet
                        if len(results) < max_results and matches_per_store.get(store_name, 0) < 20:
                            clean_line = line.strip()
                            if len(clean_line) > 200:
                                clean_line = clean_line[:197] + "..."
                            results.append(f"{qualified_id}:{line_no}: {clean_line}")
                            matches_per_store[store_name] = matches_per_store.get(store_name, 0) + 1
        except OSError:
            continue

    if not results:
        return f"No matches found for query '{query}' across memory stores."

    cutoff_note = f" (showing {len(results)} of {total_matches} matches)" if len(results) < total_matches else f" ({total_matches} matches)"
    header = f"=== Search Results for '{query}'{cutoff_note} ==="
    return header + "\n" + "\n".join(results)
