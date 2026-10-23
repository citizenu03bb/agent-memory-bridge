---
name: consult-memory
description: Query and record the user's persistent agent memories across Claude Code (~/.claude/projects/*/memory/), Codex (~/.codex/memories/), and the neutral agent store (~/.local/share/agent-memory/). Use when you need historical context, user preferences, prior research findings, production deployments, or hardware/environment constraints.
---

# consult-memory

The user maintains persistent memory stores across sessions:
1. `~/.claude/projects/` populated by Claude Code sessions (global memory in the home-directory project, e.g. `-home-<user>/memory/`, plus project-specific memories).
2. `~/.codex/memories/` populated by Codex sessions (`memory_summary.md`, `MEMORY.md`, and `rollout_summaries/`).
3. `~/.local/share/agent-memory/` neutral persistent store populated by Antigravity, Pi, and CLI sessions (`INDEX.md` and `notes/`).

This skill lets you query all stores transparently and record persistent findings into the neutral store.

## When to consult

- Before making assumptions about project status, production state, or capabilities (e.g. where a service is deployed, public vs private repos).
- You're about to do something costly (re-extract a model, re-run an experiment, restart a daemon) — check first whether prior state exists.
- You're about to make a design call (parameter sweep vs. structural test, single PR vs. many) — check if the user has a documented preference.
- The user references prior work ("the gate thing", "the patch we wrote", "the daemon") — pull the relevant memory rather than reconstructing.
- Anything about the user's environment (hardware, RAM, GPU, mount points, file paths) where guessing is worse than checking.

## When to record & The Evidence-Bound Invariant

You should record a memory when:
- You resolved a non-obvious bug or architectural constraint that future agents must know.
- You established a new production deployment invariant (e.g. systemd unit, token format, backup schedule).
- The user states a recurring preference or explicit rule.

### Strict Rules: No Model Introspection or Self-Discipline Notes
- **The Swap Test**: An entry is eligible for shared memory if and only if replacing the model/agent name with `__AGENT__` keeps the proposition true and useful for any other agent.
- **Model-Specific Disciplines Belong in Harness Files**: Any rule compensating for a model's specific blind spots or tool execution habits (e.g. "remember to call write_to_file before updating status") belongs **exclusively** in the local harness configuration file (`GEMINI.md`, `CLAUDE.md`, `OPENCODE.md`, `~/.pi/agent/AGENTS.md`), **never** in the shared memory store.
- **Mandatory Evidence**: All notes with `scope: shared` require verifiable non-empty `evidence` pointing to an external artifact:
  - Code reference: `file:<path>#<line>` (e.g. `file:src/db.py#45`)
  - Commit reference: `commit:<hash>` (e.g. `commit:56746fb`)
  - Explicit user directive: `user:<date/id>` (e.g. `user:instruction_2026-10-21`)

## Tools (CLI)

Invoke the `agent-memory-bridge` command (installed with `uv tool install` or `pipx install`). If it is not on `PATH`, use the equivalent wrapper scripts in the `scripts/` directory of the agent-memory-bridge checkout this skill is linked from (`list_memories.sh`, `grep_memories.sh`, `read_memory.sh`, `record_memory.sh`).

### `agent-memory-bridge list`
Print aggregated memory summaries from Claude, Codex, and Neutral stores in real time. Use this first to explore available knowledge.

### `agent-memory-bridge search <query> [-s] [--regex]`
Search across memory bodies in Claude, Codex, and Neutral stores. Returns matching files, line numbers, and snippets.
- Defaults to literal search. Pass `--regex` for regular expressions. Pass `-s` for case-sensitive match.
- If your search pattern begins with `-`, use `--`: `agent-memory-bridge search -- -v`.

### `agent-memory-bridge read <slug>`
Print the full body of a specific memory file across all stores.
- Qualified ID: `claude:global/<slug>`, `claude:<project>/<slug>`, `codex:<slug>`, `codex:rollout/<name>`, or `neutral:<slug>`.
- Naked slug: resolved automatically via strict total order (exact cwd match $\to$ exact global Claude $\to$ exact unique Neutral/Codex $\to$ unique substring match).

### `agent-memory-bridge record --title "<title>" --evidence "<evidence>" [--scope "shared"] [--kind "fact"] [--agent "<agent>"] [--tags "<t1,t2>"] [--body "<text>"]`
Save a new persistent memory note in the neutral store with structured YAML frontmatter and atomic indexing.

## MCP Tools (Native for Antigravity)

If running in an MCP-enabled agent like Antigravity, the `agent-memory` MCP server provides native tools:
- `list_memories()`
- `search_memories(query="...", case_sensitive=False, regex=False)`
- `read_memory(slug="...")`
- `record_memory(title="...", content="...", evidence="...", agent="antigravity", tags=[...], scope="shared", kind="fact")`
