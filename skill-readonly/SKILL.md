---
name: consult-memory
description: Query the user's persistent agent memories across Claude Code (~/.claude/projects/*/memory/), Codex (~/.codex/memories/), and the neutral agent store (~/.local/share/agent-memory/). Use when you need historical context, user preferences, prior research findings, production deployments, or hardware/environment constraints.
---

# consult-memory (Read-Only)

The user maintains persistent memory stores across sessions:
1. `~/.claude/projects/` populated by Claude Code sessions (global memory in the home-directory project, e.g. `-home-<user>/memory/`, plus project-specific memories).
2. `~/.codex/memories/` populated by Codex sessions (`memory_summary.md`, `MEMORY.md`, and `rollout_summaries/`).
3. `~/.local/share/agent-memory/` neutral persistent store populated by Antigravity, Pi, and CLI sessions (`INDEX.md` and `notes/`).

This skill lets you query all stores transparently. (For agents with native memory stores such as Claude Code or Codex, recording is managed via your native mechanism).

## When to consult

- Before making assumptions about project status, production state, or capabilities (e.g. where a service is deployed, public vs private repos).
- You're about to do something costly (re-extract a model, re-run an experiment, restart a daemon) — check first whether prior state exists.
- You're about to make a design call (parameter sweep vs. structural test, single PR vs. many) — check if the user has a documented preference.
- The user references prior work ("the gate thing", "the patch we wrote", "the daemon") — pull the relevant memory rather than reconstructing.
- Anything about the user's environment (hardware, RAM, GPU, mount points, file paths) where guessing is worse than checking.

## Tools (CLI)

Invoke the `agent-memory-bridge` command (installed with `uv tool install` or `pipx install`). If it is not on `PATH`, use the equivalent wrapper scripts in the `scripts/` directory of the agent-memory-bridge checkout this skill is linked from (`list_memories.sh`, `grep_memories.sh`, `read_memory.sh`).

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
