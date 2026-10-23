# Agent Memory Bridge

Federated cross-agent persistent memory bridge for Claude Code, Codex, Antigravity, and Pi.

> **Status: v0.1, experimental.** It reads the native memory layouts of Claude Code and Codex, which are undocumented and may change between releases.

## Why

Modern agent workflows often span multiple LLMs and environments (Claude Code, OpenAI Codex, Google Antigravity, Pi, etc.). Each one keeps its own memory, so what one agent learned is invisible to the next.

Most memory servers (Mem0/OpenMemory, basic-memory, the reference MCP `memory` server) solve this by introducing **their own** store and asking every agent to write into it. Agent Memory Bridge takes the opposite approach:

- **Read native stores in place.** Claude Code and Codex keep writing memories the way they already do; the bridge federates them read-only. No migration, no sync job, no duplicate copies.
- **Plain files only.** The neutral store for agents without native memory is Markdown with YAML frontmatter plus a generated `INDEX.md`. No database, no embeddings, nothing you can't `cat` or `git` yourself.
- **Evidence-bound notes.** Shared notes must cite a verifiable source (`file:<path>#<line>`, `commit:<hash>`, or `user:<id>`), which keeps model self-talk out of the shared store.

## Overview

1. **Zero-friction federation**: Queries native stores where they live:
   - Claude Code native store (`~/.claude/projects/<encoded-path>/memory/`, global and per-project)
   - Codex shared memory store (`~/.codex/memories/`)
2. **Neutral persistent store for vendorless agents**:
   - Antigravity, Pi, and CLI agents persist notes into `~/.local/share/agent-memory/notes/` (honours `XDG_DATA_HOME`) with YAML frontmatter.
   - Automatically maintained `INDEX.md` catalog.
3. **Dual interface**:
   - **CLI / Shell**: `agent-memory-bridge` command plus thin POSIX wrappers (`list_memories.sh`, `grep_memories.sh`, `read_memory.sh`, `record_memory.sh`).
   - **MCP Server**: Stdio Model Context Protocol server exposing `list_memories`, `search_memories`, `read_memory`, and `record_memory` to Antigravity, Cursor, and other MCP clients.

## Architecture

```
                  ┌────────────────────────┐
                  │   Agent Memory Bridge  │
                  └───────────┬────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   Claude Code Store     Codex Store        Neutral Store
   (~/.claude/projects/  (~/.codex/         (~/.local/share/
     */memory/)           memories/)        agent-memory/)
   - MEMORY.md           - memory_summary    - INDEX.md
   - *.md notes          - rollouts/*.md     - notes/*.md
```

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/citizenu03bb/agent-memory-bridge.git
cd agent-memory-bridge

# Install the commands on your PATH
uv tool install .        # or: pipx install .
```

This provides two commands: `agent-memory-bridge` (CLI) and `agent-memory-mcp` (MCP stdio server).

For development, use an in-repo virtualenv instead:

```bash
uv venv
uv pip install -e ".[dev]"
```

## Quick Start (CLI)

```bash
# List index summaries across all three stores
agent-memory-bridge list

# Search across all memory files (literal by default, --regex and -s available)
agent-memory-bridge search "append-only"

# Read a specific memory entry by slug or qualified ID
agent-memory-bridge read claude:global/user_profile

# Record a new persistent finding into the neutral store
agent-memory-bridge record \
  --title "Production Topology Invariant" \
  --agent "antigravity" \
  --tags "systemd,caddy" \
  --evidence "file:deploy/app.service#12" \
  --body "The API runs behind Caddy TLS as a hardened systemd unit."
```

The `scripts/*.sh` wrappers accept the same arguments. They use the checkout's `.venv` when present, otherwise `agent-memory-bridge` from your `PATH` (override with `AMB_BIN=/path/to/agent-memory-bridge`).

### Configuration

Store locations default to the standard paths and can be overridden with environment variables:

| Variable | Default |
| :------- | :------ |
| `AMB_CLAUDE_PROJECTS_DIR` | `~/.claude/projects` |
| `AMB_CODEX_DIR` | `~/.codex/memories` |
| `AMB_NEUTRAL_DIR` | `$XDG_DATA_HOME/agent-memory` or `~/.local/share/agent-memory` |

## MCP Server Configuration

Register the server in any MCP client. For Antigravity, add this entry to `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "agent-memory-mcp"
    }
  }
}
```

If the client does not inherit your shell `PATH`, use the absolute path printed by `command -v agent-memory-mcp`.

## Skill Installation & Symlinks

The repo ships a `consult-memory` skill in two flavours: read-write (`skill/`) for agents without native memory, and read-only (`skill-readonly/`) for Claude Code and Codex, which record through their own mechanism. To link it into every installed agent:

```bash
# Preview changes
bash scripts/install_symlinks.sh --dry-run

# Apply symlinks (existing entries are backed up first)
bash scripts/install_symlinks.sh --apply
```

## Limitations

- Search is line-based text/regex matching, not semantic search. It is fast and predictable at personal scale, not designed for very large corpora.
- Claude Code and Codex memory layouts are internal formats; a vendor release can change them and break discovery until the bridge is updated.
- Native stores are read-only through the bridge by design; only the neutral store is written.

## Testing

```bash
# Run Python unit & integration tests
.venv/bin/pytest -v

# Run POSIX shell end-to-end tests
bash tests/test_cli.sh
```

Both suites are hermetic: they run against temporary stores and never touch your real memories.

## License

[MIT](LICENSE)
