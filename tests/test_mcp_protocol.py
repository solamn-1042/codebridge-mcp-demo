import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

import server


@asynccontextmanager
async def connected(root, audit):
    script = Path(server.__file__).resolve()
    params = StdioServerParameters(command=sys.executable, args=[str(script)],
                                  env={"CODEBRIDGE_REPO_ROOT": str(root), "CODEBRIDGE_AUDIT_DB": str(audit)},
                                  cwd=str(script.parent))
    async with Client(params, read_timeout_seconds=135) as client:
        yield client


def payload(result):
    return json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_stdio_mcp_client_discovers_and_calls_codebridge_tools(tmp_path):
    """Exercise the same stdio transport that DSH uses to launch CodeBridge."""
    server_script = Path(server.__file__).resolve()
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_script)],
        env={"CODEBRIDGE_REPO_ROOT": str(server.ROOT), "CODEBRIDGE_AUDIT_DB": str(tmp_path / "protocol.sqlite3")},
        cwd=str(server_script.parent),
    )

    async with Client(params, read_timeout_seconds=10) as client:
        discovered = await client.list_tools()
        names = {tool.name for tool in discovered.tools}
        assert {"repo_overview", "change_summary", "run_project_check", "search_code", "read_file", "git_diff", "tool_metrics"} == names

        result = await client.call_tool(
            "run_project_check", {"check_name": "not-configured"}
        )
        assert result.content
        assert "CHECK_NOT_CONFIGURED" in result.content[0].text


@pytest.mark.anyio
async def test_real_mcp_repository_workflow(repository):
    root, _ = repository
    (root / "app.py").write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
    (root / "test_app.py").write_text("from app import add\ndef test_add():\n    assert add(1, 2) == 4\n", encoding="utf-8")
    async with connected(root, root / "audit.sqlite3") as client:
        overview = payload(await client.call_tool("repo_overview", {}))
        assert overview["readme_excerpt"].startswith("# Sample")
        hits = payload(await client.call_tool("search_code", {"query": "return a + b"}))
        assert hits["matches"][0]["path"] == "app.py"
        read = payload(await client.call_tool("read_file", {"path": "app.py", "start_line": 2, "line_count": 1}))
        assert "+ 1" in read["lines"][0]["text"]
        diff = payload(await client.call_tool("git_diff", {"path": "app.py"}))
        assert "+    return a + b + 1" in diff["diff"]
        check = payload(await client.call_tool("run_project_check", {"check_name": "test"}))
        assert check["passed"] is True
        metrics = payload(await client.call_tool("tool_metrics", {}))
        assert metrics["total_calls"] == 5


@pytest.mark.anyio
async def test_schema_errors_and_denial_do_not_end_mcp_session(repository):
    root, _ = repository
    async with connected(root, root / "audit.sqlite3") as client:
        for arguments in ({}, {"path": "app.py", "start_line": "invalid-number"}):
            rejected = await client.call_tool("read_file", arguments)
            assert rejected.is_error is True
            assert payload(await client.call_tool("read_file", {"path": "app.py"}))["lines"]
        denied = payload(await client.call_tool("read_file", {"path": "../outside"}))
        assert denied["error"] == "PATH_OUTSIDE_ROOT"
        assert payload(await client.call_tool("repo_overview", {}))["repository_name"] == root.name
