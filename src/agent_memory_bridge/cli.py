"""Command-line interface for Agent Memory Bridge."""

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Dict, List
import yaml

from .core import (
    AmbiguousMemoryError,
    MemoryNotFoundError,
    get_neutral_notes_dir,
    list_memories,
    parse_frontmatter,
    patch_frontmatter,
    read_memory,
    rebuild_neutral_index,
    record_memory,
    search_memories,
    serialize_frontmatter,
    validate_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-memory-bridge",
        description="Federated cross-agent persistent memory bridge.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # list
    subparsers.add_parser("list", help="List summary overview across all memory stores.")

    # search
    search_parser = subparsers.add_parser("search", help="Search across all memory stores.")
    search_parser.add_argument("query", help="Text or regex pattern to search for.")
    search_parser.add_argument("-s", "--case-sensitive", action="store_true", help="Case-sensitive search.")
    search_parser.add_argument("--regex", action="store_true", help="Treat query as a regular expression.")

    # read
    read_parser = subparsers.add_parser("read", help="Read full content of a memory file.")
    read_parser.add_argument("slug", help="Memory slug, qualified ID, or substring.")

    # record
    record_parser = subparsers.add_parser("record", help="Record a new memory in the neutral store.")
    record_parser.add_argument("--title", required=True, help="Title of the memory.")
    record_parser.add_argument("--content", dest="content", help="Body text of the memory. If omitted, read from stdin.")
    record_parser.add_argument("--body", dest="body", help="Alias for --content.")
    record_parser.add_argument("--agent", default="cli", help="Agent identifier (default: cli).")
    record_parser.add_argument("--tags", nargs="*", default=[], help="List of tags (or comma-separated).")
    record_parser.add_argument("--scope", default="shared", help="Scope: 'shared' or 'project:<id>'.")
    record_parser.add_argument("--kind", default="fact", help="Kind: 'fact', 'preference', 'convention'.")
    record_parser.add_argument("--evidence", required=False, help="Verifiable external proof ('file:...', 'commit:...', 'user:...').")

    # migrate
    migrate_parser = subparsers.add_parser("migrate", help="Audit and normalize frontmatters in neutral store.")
    migrate_parser.add_argument("--apply", action="store_true", help="Apply fixes to frontmatters and rebuild index.")

    return parser


def parse_tag_args(tags_raw: List[str]) -> List[str]:
    """Support both space-separated and comma-separated tags."""
    parsed: List[str] = []
    for item in tags_raw:
        if "," in item:
            for sub in item.split(","):
                clean = sub.strip()
                if clean:
                    parsed.append(clean)
        else:
            clean = item.strip()
            if clean:
                parsed.append(clean)
    return parsed


def main(argv: List[str] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "list":
        print(list_memories())
        return 0

    elif args.subcommand == "search":
        case_sensitive = args.case_sensitive
        regex = args.regex
        print(search_memories(args.query, case_sensitive=case_sensitive, regex=regex))
        return 0

    elif args.subcommand == "read":
        try:
            content = read_memory(args.slug)
            print(content, end="" if content.endswith("\n") else "\n")
            return 0
        except (AmbiguousMemoryError, MemoryNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    elif args.subcommand == "record":
        content = args.content or args.body
        if not content:
            if sys.stdin.isatty():
                print("Enter memory content (Ctrl-D when finished):", file=sys.stderr)
            content = sys.stdin.read()

        if not content.strip():
            print("Error: Memory content cannot be empty.", file=sys.stderr)
            return 1

        tags = parse_tag_args(args.tags)
        try:
            res = record_memory(
                title=args.title,
                content=content,
                agent=args.agent,
                tags=tags,
                scope=args.scope,
                kind=args.kind,
                evidence=args.evidence,
            )
            print("Recorded memory successfully.")
            print(f"File: {res['file']}")
            print(f"Slug: {res['filename']}")
            print(f"Scope: {res['scope']}")
            print(f"Kind: {res['kind']}")
            print(f"Evidence: {res['evidence']}")
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Error recording memory: {e}", file=sys.stderr)
            return 1

    elif args.subcommand == "migrate":
        notes_dir = get_neutral_notes_dir(create=False)
        if not notes_dir.is_dir():
            print(f"Notes directory does not exist at {notes_dir}")
            return 0

        notes = sorted(notes_dir.glob("*.md"))
        print(f"Auditing {len(notes)} note(s) in {notes_dir}")
        updated_count = 0

        for n in notes:
            with open(n, "r", encoding="utf-8", newline="") as f:
                text = f.read().lstrip("\ufeff")
            meta, body = parse_frontmatter(text)
            if not meta and text.startswith("---"):
                print(f"  [SKIPPING] {n.name}: Malformed YAML frontmatter, skipping to prevent data loss.")
                continue

            missing = [k for k in ["scope", "kind", "evidence"] if k not in meta]
            evidence_invalid = False
            evidence_needs_canonicalization = False
            valid_existing_evidence = None

            if "evidence" in meta:
                try:
                    valid_existing_evidence = validate_evidence(meta["evidence"], allow_legacy=True)
                    if valid_existing_evidence != meta["evidence"]:
                        evidence_needs_canonicalization = True
                except ValueError:
                    evidence_invalid = True
                    missing.append("evidence (invalid)")

            if not missing and not evidence_invalid and not evidence_needs_canonicalization:
                continue

            updates: Dict[str, str] = {}
            if "scope" not in meta:
                updates["scope"] = "shared"
            if "kind" not in meta:
                updates["kind"] = "fact"

            if "evidence" not in meta:
                updates["evidence"] = "legacy:pre_bridge_unverified"
            elif evidence_invalid:
                raw_ev = meta.get("evidence")
                if raw_ev is None or str(raw_ev).strip().lower() in ("", "none"):
                    updates["evidence"] = "legacy:pre_bridge_unverified"
                else:
                    updates["evidence"] = f"legacy:pre_bridge_unverified (was: {str(raw_ev).strip()})"
            elif evidence_needs_canonicalization:
                missing.append("evidence (canonicalize)")
                updates["evidence"] = valid_existing_evidence

            action_label = "UPDATING" if args.apply else "WOULD UPDATE"
            print(f"  [{action_label}] {n.name} (fields to update: {missing})")
            if args.apply:
                orig_mode = stat.S_IMODE(n.stat().st_mode)
                try:
                    new_text = patch_frontmatter(text, updates)
                except Exception as err:
                    print(f"  [ERROR] Failed to patch frontmatter for {n.name}: {err}. Skipping to prevent data loss.", file=sys.stderr)
                    continue

                fd, tmp_str = tempfile.mkstemp(dir=notes_dir, prefix="mig_", suffix=".tmp")
                tmp_p = Path(tmp_str)
                try:
                    os.fchmod(fd, orig_mode)
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                        f.write(new_text)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_p, n)
                    updated_count += 1
                except Exception:
                    if tmp_p.exists():
                        tmp_p.unlink()
                    raise

        if args.apply:
            rebuild_neutral_index()
            print(f"Migration applied: {updated_count} note(s) updated, index rebuilt.")
        else:
            print(f"Dry-run complete. Run with --apply to apply atomic updates.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
