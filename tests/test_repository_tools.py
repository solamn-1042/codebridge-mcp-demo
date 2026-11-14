import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest
import server
import telemetry
from execution import execute

def value(tool, *args, **kwargs):
    return json.loads(tool(*args, **kwargs))

def test_search_returns_citable_lines_and_ignores_noise(repository):
    root, _ = repository
    for directory in ("ignored", "node_modules", ".dsh"):
        (root / directory).mkdir()
        (root / directory / "noise.py").write_text("return a + b", encoding="utf-8")
    (root / ".env").write_text("return a + b", encoding="utf-8")
    result = value(server.search_code, "return a + b")
    assert [(item["path"], item["line"]) for item in result["matches"]] == [("app.py", 2)]

def test_literal_search_scope_and_limit(repository):
    root, _ = repository
    (root / "many.py").write_text("x.y\n" * 40, encoding="utf-8")
    result = value(server.search_code, "x.y", path="many.py", max_results=3)
    assert len(result["matches"]) == 3 and result["truncated"]
    assert value(server.search_code, "x.*")["matches"] == []

@pytest.mark.parametrize("path", ["../outside.txt", "C:\\Windows\\win.ini", "/etc/passwd", "app.py:secret", ".env", ".dsh/credentials.yml", "secret.key", "NUL", ".dsh./data.txt"])
def test_read_denies_paths_without_content(repository, path):
    result = value(server.read_file, path)
    assert result["error"] in {"PATH_OUTSIDE_ROOT", "PATH_BLOCKED"}
    assert "lines" not in result

def test_read_range_and_limits(repository):
    root, _ = repository
    (root / "lines.txt").write_text("\n".join(str(i) for i in range(500)), encoding="utf-8")
    result = value(server.read_file, "lines.txt", 11, 20)
    assert result["lines"][0] == {"line": 11, "text": "10", "truncated": False}
    assert result["next_start_line"] == 31
    assert value(server.read_file, "lines.txt", line_count=201)["error"] == "INVALID_RANGE"
    (root / "large.txt").write_bytes(b"x" * 262145)
    assert value(server.read_file, "large.txt")["error"] == "FILE_TOO_LARGE"
    (root / "image.bin").write_bytes(b"a\0b")
    assert value(server.read_file, "image.bin")["error"] == "BINARY_FILE"

def test_read_gitignored_file_is_denied(repository):
    root, _ = repository
    (root / "ignored").mkdir()
    (root / "ignored" / "data.txt").write_text("secret", encoding="utf-8")
    assert value(server.read_file, "ignored/data.txt")["error"] == "PATH_IGNORED"

def test_junction_escape_is_denied(repository, tmp_path_factory):
    root, _ = repository
    outside = tmp_path_factory.mktemp("outside")
    (outside / "data.txt").write_text("outside", encoding="utf-8")
    link = root / "link"
    if os.name == "nt":
        # PowerShell creates a junction without requiring Developer Mode.
        # Paths originate in pytest, and single quotes are escaped as PowerShell literals.
        link_literal = str(link).replace("'", "''")
        target_literal = str(outside).replace("'", "''")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"New-Item -ItemType Junction -Path '{link_literal}' -Target '{target_literal}' | Out-Null"],
                       check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    assert value(server.read_file, "link/data.txt")["error"] == "LINK_NOT_ALLOWED"
    assert value(server.search_code, "outside")["matches"] == []

def test_git_diff_staged_unstaged_and_deleted(repository):
    root, git = repository
    (root / "app.py").write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
    git("add", "app.py")
    (root / "app.py").write_text("def add(a, b):\n    return a + b + 2\n", encoding="utf-8")
    assert "+    return a + b + 1" in value(server.git_diff, "app.py", "staged")["diff"]
    assert "+    return a + b + 2" in value(server.git_diff, "app.py", "unstaged")["diff"]
    assert "-    return a + b" in value(server.git_diff, "app.py")["diff"]
    (root / "README.md").unlink()
    assert "-Addition service" in value(server.git_diff, "README.md")["diff"]
    assert value(server.git_diff, ".env")["error"] == "PATH_BLOCKED"

def test_fixed_check_reports_success_and_failure(repository):
    root, _ = repository
    (root / "test_app.py").write_text("from app import add\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    assert value(server.run_project_check, "test")["passed"] is True
    (root / "test_app.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    result = value(server.run_project_check, "test")
    assert result["passed"] is False and result["exit_code"] == 1
    assert value(server.run_project_check, "test; whoami")["error"] == "CHECK_NOT_CONFIGURED"

def test_execution_timeout_and_bounded_output(repository):
    root, _ = repository
    with pytest.raises(subprocess.TimeoutExpired):
        execute([sys.executable, "-c", "import time; time.sleep(10)"], root, .2)
    result = execute([sys.executable, "-c", "print('x' * 10000)"], root, 5, 200)
    assert result.truncated and len(result.stdout) <= 200

def test_timeout_cleans_child_process(repository):
    root, _ = repository
    child_code = "import time,pathlib;time.sleep(2);pathlib.Path('escaped.txt').write_text('alive')"
    parent_code = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]);time.sleep(10)"
    with pytest.raises(subprocess.TimeoutExpired):
        execute([sys.executable, "-c", parent_code], root, .3)
    time.sleep(2.2)
    assert not (root / "escaped.txt").exists()

def test_errors_and_telemetry_failure_leave_tools_usable(repository, monkeypatch):
    assert value(server.read_file, "missing.py")["error"] == "FILE_NOT_FOUND"
    assert value(server.read_file, "app.py")["lines"]
    monkeypatch.setattr(telemetry, "record", lambda *args: False)
    assert value(server.read_file, "app.py")["meta"]["telemetry_recorded"] is False

def test_metrics_store_metadata_not_content(repository):
    value(server.search_code, "return a + b")
    value(server.read_file, "../bad")
    metrics = value(server.tool_metrics)
    assert metrics["total_calls"] == 2
    assert metrics["tools"]["read_file"]["error_codes"] == {"PATH_OUTSIDE_ROOT": 1}
    with sqlite3.connect(telemetry.database_path()) as db:
        columns = [row[1] for row in db.execute("pragma table_info(calls)")]
    assert columns == ["id", "created_at", "tool", "duration_ms", "error_code", "output_chars"]
