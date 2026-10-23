"""MCP Server exposing memory tools via the Model Context Protocol."""

from typing import List, Optional
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .core import (
    AmbiguousMemoryError,
    MemoryNotFoundError,
    list_memories as core_list,
    read_memory as core_read,
    record_memory as core_record,
    search_memories as core_search,
)

app = MCPServer("agent-memory-bridge")


@app.tool(
    name="list_memories",
    description="List all persistent memory indices and summaries across Claude Code, Codex, and Neutral stores in real time.",
)
def list_memories() -> str:
    """List memory summaries."""
    return core_list()


@app.tool(
    name="search_memories",
    description="Search across all memory stores (Claude Code, Codex, and Neutral) for a literal query or regex pattern. Output is bounded and qualified.",
)
def search_memories(query: str, case_sensitive: bool = False, regex: bool = False) -> str:
    """Search memory contents."""
    return core_search(query, case_sensitive=case_sensitive, regex=regex)


@app.tool(
    name="read_memory",
    description="Read the complete content of a memory file by slug or qualified ID (e.g. claude:global/foo, neutral:bar, codex:baz).",
)
def read_memory(slug: str) -> str:
    """Read full memory text."""
    try:
        return core_read(slug)
    except (AmbiguousMemoryError, MemoryNotFoundError, ValueError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Unexpected error reading memory '{slug}': {e}")


@app.tool(
    name="record_memory",
    description=(
        "Record a persistent memory note in the neutral store. "
        "Strict Evidence-Bound contract: for scope='shared', a non-empty external verifiable 'evidence' "
        "('file:...', 'commit:...', 'user:...') is strictly required. "
        "Model-specific behavioral rules or self-discipline notes must NOT be recorded here; "
        "put them in your local harness file (e.g. GEMINI.md, CLAUDE.md, OPENCODE.md, ~/.pi/agent/AGENTS.md)."
    ),
)
def record_memory(
    title: str,
    content: str,
    agent: str = "antigravity",
    tags: Optional[List[str]] = None,
    scope: str = "shared",
    kind: str = "fact",
    evidence: Optional[str] = None,
) -> str:
    """Record a memory note with structured frontmatter."""
    try:
        res = core_record(
            title=title,
            content=content,
            agent=agent,
            tags=tags,
            scope=scope,
            kind=kind,
            evidence=evidence,
        )
        return (
            f"Successfully recorded memory note.\n"
            f"File: {res['file']}\n"
            f"Slug: {res['filename']}\n"
            f"Scope: {res['scope']}\n"
            f"Kind: {res['kind']}\n"
            f"Evidence: {res['evidence']}\n"
            f"Agent: {res['agent']}\n"
            f"Date: {res['date']}"
        )
    except (ValueError, FileExistsError) as e:
        raise ToolError(str(e))
    except Exception as e:
        raise ToolError(f"Unexpected error recording memory: {e}")


def main():
    app.run(transport="stdio")


if __name__ == "__main__":
    main()
