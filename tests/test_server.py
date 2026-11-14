import json
import subprocess

import server


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )


def test_repo_overview_reports_manifests_and_readme(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("# Sample project\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(server, "ROOT", tmp_path)

    result = json.loads(server.repo_overview())

    assert result["repository_name"] == tmp_path.name
    assert "pyproject.toml" in result["project_files"]
    assert "src/" in result["top_level_entries"]
    assert ".venv/" not in result["top_level_entries"]
    assert "Sample project" in result["readme_excerpt"]


def test_change_summary_counts_modified_added_and_untracked(tmp_path, monkeypatch):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "CodeBridge Test")
    _git(tmp_path, "config", "user.email", "codebridge-test@example.invalid")
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "test baseline")
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(server, "ROOT", tmp_path)

    result = json.loads(server.change_summary())

    assert result["modified_count"] == 1
    assert result["untracked_count"] == 1
    assert any("tracked.txt" in item for item in result["changed_files"])
    assert any("new.txt" in item for item in result["changed_files"])


def test_change_summary_handles_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ROOT", tmp_path / "does-not-exist")
    result = json.loads(server.change_summary())
    assert result["error"] == "IO_ERROR"


def test_run_project_check_rejects_unknown_command():
    result = json.loads(server.run_project_check("deploy"))
    assert result["error"] == "CHECK_NOT_CONFIGURED"
    assert result["allowed_checks"] == ["test"]
