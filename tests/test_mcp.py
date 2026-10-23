"""Tests for agent-memory MCP server tool endpoints and exception translation."""

import pytest

# Skip if mcp is not installed
mcp = pytest.importorskip("mcp")
from mcp.server.mcpserver.exceptions import ToolError
from agent_memory_bridge.mcp_server import app


@pytest.mark.asyncio
async def test_mcp_list_tools():
    tools = await app.list_tools()
    tool_names = {t.name for t in tools}
    assert "list_memories" in tool_names
    assert "search_memories" in tool_names
    assert "read_memory" in tool_names
    assert "record_memory" in tool_names


@pytest.mark.asyncio
async def test_mcp_read_memory_success():
    res = await app.call_tool("read_memory", {"slug": "webapp_project"})
    assert res is not None
    assert len(res.content) > 0
    assert "Webapp deployed on staging" in res.content[0].text


@pytest.mark.asyncio
async def test_mcp_read_memory_tool_error():
    with pytest.raises(ToolError) as excinfo:
        await app.call_tool("read_memory", {"slug": "unknown_slug_99999"})
    assert "Memory not found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_mcp_record_memory_rejection_tool_error():
    with pytest.raises(ToolError) as excinfo:
        await app.call_tool(
            "record_memory",
            {
                "title": "Model Workaround",
                "content": "Penser a write_to_file",
                "scope": "shared",
                # missing evidence
            },
        )
    assert "[MemoryRejection]" in str(excinfo.value)
    assert "GEMINI.md" in str(excinfo.value)


@pytest.mark.asyncio
async def test_mcp_record_memory_success():
    res = await app.call_tool(
        "record_memory",
        {
            "title": "MCP Tool Invariant",
            "content": "Testing MCP tool recording with evidence.",
            "scope": "shared",
            "kind": "fact",
            "evidence": "commit:98765432",
            "tags": ["mcp", "test"],
        },
    )
    assert res is not None
    assert "Successfully recorded memory note" in res.content[0].text
    assert "Evidence: commit:98765432" in res.content[0].text
