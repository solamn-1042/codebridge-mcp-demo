import subprocess
import pytest
import server

@pytest.fixture(autouse=True)
def isolated_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEBRIDGE_AUDIT_DB", str(tmp_path / "audit.sqlite3"))

@pytest.fixture
def repository(tmp_path, monkeypatch):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True)
    git("init")
    git("config", "user.name", "CodeBridge Test")
    git("config", "user.email", "codebridge@example.invalid")
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Sample\nAddition service\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored/\naudit.sqlite3\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "initial")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    return tmp_path, git
