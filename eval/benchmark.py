"""Repeatable real-stdio regression benchmark, independent of LLM calls or API keys."""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from mcp import Client, StdioServerParameters

PROJECT = Path(__file__).resolve().parents[1]


async def benchmark(rounds: int) -> dict:
    records = []
    denial_passed = schema_passed = after_denial = after_schema = 0
    with tempfile.TemporaryDirectory(prefix="codebridge-benchmark-") as directory:
        root = Path(directory)
        def git(*args):
            subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
        git("init")
        git("config", "user.name", "CodeBridge Benchmark")
        git("config", "user.email", "benchmark@example.invalid")
        (root / "README.md").write_text("# Addition service\n", encoding="utf-8")
        (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (root / "test_app.py").write_text("from app import add\ndef test_add():\n    assert add(1, 2) == 4\n", encoding="utf-8")
        (root / ".gitignore").write_text("audit.sqlite3\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "benchmark baseline")
        (root / "app.py").write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
        parameters = StdioServerParameters(command=sys.executable, args=[str(PROJECT / "server.py")],
                                          cwd=str(PROJECT), env={"CODEBRIDGE_REPO_ROOT": str(root),
                                          "CODEBRIDGE_AUDIT_DB": str(root / "audit.sqlite3")})
        async with Client(parameters, read_timeout_seconds=135) as client:
            tools = await client.list_tools()
            tool_names = sorted(tool.name for tool in tools.tools)
            async def call(name, arguments, expected, category="normal"):
                started = time.perf_counter()
                result = await client.call_tool(name, arguments)
                elapsed = (time.perf_counter() - started) * 1000
                try:
                    body = json.loads(result.content[0].text)
                except (ValueError, IndexError):
                    body = {}
                passed = bool(expected(result, body))
                records.append({"tool": name, "category": category, "passed": passed, "latency_ms": round(elapsed, 2)})
                return passed
            valid_read = lambda result, body: not result.is_error and bool(body.get("lines"))
            for _ in range(rounds):
                await call("repo_overview", {}, lambda r, b: b.get("readme_excerpt", "").startswith("# Addition"))
                await call("search_code", {"query": "return a + b"}, lambda r, b: [(m["path"], m["line"]) for m in b.get("matches", [])] == [("app.py", 2)])
                await call("read_file", {"path": "app.py", "start_line": 2, "line_count": 1}, valid_read)
                await call("git_diff", {"path": "app.py"}, lambda r, b: "+    return a + b + 1" in b.get("diff", ""))
                denial_passed += await call("read_file", {"path": "../outside"}, lambda r, b: b.get("error") == "PATH_OUTSIDE_ROOT", "policy_denial")
                after_denial += await call("read_file", {"path": "app.py"}, valid_read)
                schema_passed += await call("read_file", {}, lambda r, b: r.is_error is True, "schema_rejection")
                after_schema += await call("read_file", {"path": "app.py"}, valid_read)
            await call("run_project_check", {"check_name": "test"}, lambda r, b: b.get("passed") is True)
            telemetry = json.loads((await client.call_tool("tool_metrics", {})).content[0].text)
    timings = {}
    normal = [record for record in records if record["category"] == "normal"]
    for tool in sorted({record["tool"] for record in normal}):
        values = sorted(record["latency_ms"] for record in normal if record["tool"] == tool)
        timings[tool] = {"calls": len(values), "average_ms": round(sum(values) / len(values), 2),
                         "p95_ms": values[(95 * len(values) + 99) // 100 - 1]}
    files = ["server.py", "repository_policy.py", "execution.py", "telemetry.py", "plugins/codebridge-manager.ts"]
    digest = {name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest() for name in files}
    return {"measured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "platform": platform.platform(), "python": platform.python_version(), "rounds": rounds,
            "method": "Real stdio MCP calls against a temporary Git/Python fixture; no model or end-user task evaluation.",
            "tools": tool_names, "normal_calls": len(normal), "normal_passed": sum(r["passed"] for r in normal),
            "denials": {"expected": rounds, "passed": denial_passed, "subsequent_read_passed": after_denial},
            "schema_errors": {"expected": rounds, "passed": schema_passed, "subsequent_read_passed": after_schema},
            "latency_including_ipc": timings, "server_metrics": telemetry, "source_sha256": digest,
            "all_assertions_passed": all(record["passed"] for record in records), "records": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--output", type=Path, default=PROJECT / "eval" / "tool_benchmark.json")
    options = parser.parse_args()
    if not 1 <= options.rounds <= 100:
        parser.error("rounds must be between 1 and 100")
    result = asyncio.run(benchmark(options.rounds))
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"records", "source_sha256", "server_metrics"}}, ensure_ascii=False, indent=2))
    sys.exit(0 if result["all_assertions_passed"] else 1)
