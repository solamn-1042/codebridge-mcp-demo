"""CodeBridge: bounded repository context and allowlisted verification over MCP."""
from __future__ import annotations
import functools
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Literal
from mcp.server import MCPServer
from execution import execute
from repository_policy import ToolError, blocked, safe_path, text_content
import telemetry

mcp = MCPServer("CodeBridge")
ROOT = Path(os.environ.get("CODEBRIDGE_REPO_ROOT", Path(__file__).parent)).resolve()
PROJECT_FILES = {"pyproject.toml", "requirements.txt", "package.json", "pom.xml", "build.gradle",
                 "build.gradle.kts", "go.mod", "Cargo.toml"}
MAX_OUTPUT_CHARS = 4000
SEARCH_SECONDS = 5
MAX_SCAN_FILES = 1000


def observed(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        started = time.perf_counter()
        try:
            result = function(*args, **kwargs)
        except ToolError as exc:
            result = {"error": exc.code, "message": str(exc), "recoverable": True}
        except subprocess.TimeoutExpired:
            result = {"error": "COMMAND_TIMEOUT", "message": "Command exceeded its execution budget.", "recoverable": True}
        except OSError:
            result = {"error": "IO_ERROR", "message": "Unable to access the file or start the command.", "recoverable": True}
        except Exception:
            result = {"error": "TOOL_FAILED", "message": "Tool execution failed; retry with a valid request.", "recoverable": True}
        duration = round((time.perf_counter() - started) * 1000, 2)
        call_id = uuid.uuid4().hex
        output_chars = len(json.dumps(result, ensure_ascii=False))
        recorded = telemetry.record(call_id, function.__name__, duration, result.get("error"), output_chars)
        result["meta"] = {"call_id": call_id, "duration_ms": duration, "telemetry_recorded": recorded}
        return json.dumps(result, ensure_ascii=False)
    return wrapped


def _run_git(args: list[str], limit: int = 24000):
    return execute(["git", "--no-pager", "-c", "core.fsmonitor=false", *args], ROOT, 10, limit)


def _path(value: str, must_exist: bool = True) -> Path:
    path = safe_path(ROOT, value, must_exist=must_exist)
    relative = path.relative_to(ROOT).as_posix()
    ignored = _run_git(["check-ignore", "--quiet", "--", relative])
    if ignored.returncode == 0:
        raise ToolError("PATH_IGNORED", "The requested path is excluded by Git ignore rules.")
    return path


@mcp.tool()
@observed
def repo_overview() -> str:
    """Get repository purpose, manifests, top-level entries and branch before exploring code."""
    if not ROOT.is_dir():
        raise ToolError("REPO_NOT_FOUND", "Configured repository does not exist.")
    entries = sorted(item.name + ("/" if item.is_dir() else "") for item in ROOT.iterdir()
                     if not blocked((item.name,)) and not item.is_symlink() and not item.is_junction())
    readme = ""
    for name in ("README.md", "readme.md", "README.rst", "README"):
        try:
            readme = text_content(_path(name))[:3000]
            break
        except ToolError:
            continue
    branch = _run_git(["branch", "--show-current"])
    return {"repository_name": ROOT.name, "branch": branch.stdout.strip() if branch.returncode == 0 else "unknown",
            "project_files": sorted(name for name in PROJECT_FILES if (ROOT / name).is_file()),
            "top_level_entries": entries[:40], "entries_truncated": len(entries) > 40,
            "readme_excerpt": readme, "limits": {"readme_chars": 3000, "top_level_entries": 40}}


@mcp.tool()
@observed
def search_code(query: str, path: str = ".", max_results: int = 20) -> str:
    """Literal UTF-8 code-content search; return repository paths, line numbers and bounded snippets."""
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise ToolError("INVALID_QUERY", "Query must contain 1 to 200 characters.")
    if type(max_results) is not int or not 1 <= max_results <= 50:
        raise ToolError("INVALID_LIMIT", "max_results must be between 1 and 50.")
    scope = _path(path)
    index = _run_git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"], limit=2 * 1024 * 1024)
    index_truncated = index.truncated
    if index.returncode == 0:
        names = dict.fromkeys(index.stdout.split("\0")[:-1])
        candidates = (ROOT / name for name in names if not blocked(Path(name).parts))
    else:
        def walk():
            nonlocal budget_hit
            if scope.is_file():
                yield scope
                return
            for directory, dirs, files in os.walk(scope, followlinks=False):
                if time.perf_counter() - started > SEARCH_SECONDS:
                    budget_hit = True
                    return
                dirs[:] = sorted(name for name in dirs if not blocked((name,))
                                 and not (Path(directory) / name).is_symlink()
                                 and not (Path(directory) / name).is_junction())
                for name in sorted(files):
                    if time.perf_counter() - started > SEARCH_SECONDS:
                        budget_hit = True
                        return
                    if not blocked((name,)):
                        yield Path(directory) / name
        candidates = walk()
    started = time.perf_counter()
    matches, scanned, skipped = [], 0, 0
    budget_hit = False
    for candidate in candidates:
        if time.perf_counter() - started > SEARCH_SECONDS or scanned >= MAX_SCAN_FILES:
            budget_hit = True
            break
        if scope.is_file() and candidate != scope or scope.is_dir() and not candidate.is_relative_to(scope):
            continue
        scanned += 1
        try:
            relative = candidate.relative_to(ROOT).as_posix()
            content = text_content(safe_path(ROOT, relative))
        except (ToolError, OSError):
            skipped += 1
            continue
        for number, line in enumerate(content.splitlines(), 1):
            position = line.find(query)
            if position >= 0:
                if len(matches) == max_results:
                    budget_hit = True
                    break
                start = max(0, position - 60)
                matches.append({"path": relative, "line": number, "snippet": line[start:start + 240],
                                "snippet_truncated": start > 0 or len(line) > start + 240})
        if budget_hit:
            break
    return {"matches": matches, "scanned_files": scanned, "skipped_files": skipped,
            "truncated": budget_hit or index_truncated,
            "limits": {"max_results": max_results, "max_files": MAX_SCAN_FILES, "search_seconds": SEARCH_SECONDS}}


@mcp.tool()
@observed
def read_file(path: str, start_line: int = 1, line_count: int = 80) -> str:
    """Read a line range; absolute, ignored, credential and linked paths are denied."""
    if type(start_line) is not int or start_line < 1 or type(line_count) is not int or not 1 <= line_count <= 200:
        raise ToolError("INVALID_RANGE", "start_line must be positive; line_count must be between 1 and 200.")
    target = _path(path)
    lines = text_content(target).splitlines()
    if start_line > len(lines) + 1:
        raise ToolError("LINE_OUT_OF_RANGE", "The start line is beyond the file.")
    selected, chars = [], 0
    next_line = None
    line_truncated = False
    for number in range(start_line, min(len(lines) + 1, start_line + line_count)):
        text = lines[number - 1][:400]
        if chars + len(text) > 12000:
            next_line = number
            break
        chars += len(text)
        clipped = len(lines[number - 1]) > 400
        line_truncated |= clipped
        selected.append({"line": number, "text": text, "truncated": clipped})
    if next_line is None and start_line + len(selected) <= len(lines):
        next_line = start_line + len(selected)
    return {"path": target.relative_to(ROOT).as_posix(), "total_lines": len(lines), "lines": selected,
            "next_start_line": next_line, "truncated": next_line is not None or line_truncated,
            "limits": {"max_lines": 200, "max_text_chars": 12000, "max_file_bytes": 262144}}


@mcp.tool()
@observed
def change_summary() -> str:
    """Get Git status and diff statistics; use git_diff for a selected file's patch."""
    status = _run_git(["status", "--short", "--branch"])
    if status.returncode != 0:
        raise ToolError("NOT_A_GIT_REPOSITORY", "Configured root is not an accessible Git repository.")
    lines = status.stdout.splitlines()
    files = [line for line in lines if not line.startswith("##")]
    counts = {"modified_count": 0, "added_count": 0, "deleted_count": 0, "untracked_count": 0}
    for line in files:
        code = line[:2]
        key = "untracked_count" if code == "??" else "deleted_count" if "D" in code else "added_count" if "A" in code else "modified_count"
        counts[key] += 1
    stat = _run_git(["diff", "--no-ext-diff", "--no-textconv", "--stat", "HEAD"])
    return {"branch_status": lines[0] if lines else "unknown", **counts, "changed_files": files[:50],
            "files_truncated": len(files) > 50 or status.truncated,
            "diff_stat": stat.stdout[:2000] if stat.returncode == 0 else "unavailable"}


@mcp.tool()
@observed
def git_diff(path: str, mode: Literal["unstaged", "staged", "all"] = "all", context_lines: int = 3) -> str:
    """Read one file's actual patch: unstaged, staged, or HEAD-to-working-tree changes."""
    if mode not in {"unstaged", "staged", "all"} or type(context_lines) is not int or not 0 <= context_lines <= 10:
        raise ToolError("INVALID_DIFF_OPTIONS", "Choose unstaged/staged/all; context_lines must be between 0 and 10.")
    target = _path(path, must_exist=False)
    if target.is_dir():
        raise ToolError("NOT_A_FILE", "Select one file, not a directory.")
    relative = target.relative_to(ROOT).as_posix()
    args = ["diff", "--no-ext-diff", "--no-textconv", "--no-renames", f"--unified={context_lines}"]
    args += ["--cached"] if mode == "staged" else ["HEAD"] if mode == "all" else []
    result = _run_git([*args, "--", f":(literal){relative}"], limit=12000)
    if result.returncode != 0:
        raise ToolError("GIT_DIFF_FAILED", "Unable to diff the selected file; check repository and HEAD.")
    return {"path": relative, "mode": mode, "diff": result.stdout, "has_changes": bool(result.stdout),
            "truncated": result.truncated, "limits": {"max_output_bytes": 12000},
            "note": "Untracked files have no Git patch; inspect them with read_file."}


@mcp.tool()
@observed
def run_project_check(check_name: str) -> str:
    """Run fixed pytest in a trusted repository; model-supplied commands are not accepted."""
    if check_name != "test":
        return {"error": "CHECK_NOT_CONFIGURED", "allowed_checks": ["test"], "recoverable": True}
    result = execute([sys.executable, "-m", "pytest", "-q"], ROOT, 120, MAX_OUTPUT_CHARS)
    return {"check_name": check_name, "exit_code": result.returncode, "passed": result.returncode == 0,
            "stdout": result.stdout, "stderr": result.stderr, "output_truncated": result.truncated,
            "timeout_seconds": 120}


@mcp.tool()
def tool_metrics() -> str:
    """Summarize persisted calls, latency and errors; this query is excluded from metrics."""
    try:
        return json.dumps(telemetry.metrics(), ensure_ascii=False)
    except Exception:
        return json.dumps({"error": "METRICS_UNAVAILABLE", "recoverable": True})


if __name__ == "__main__":
    mcp.run()
