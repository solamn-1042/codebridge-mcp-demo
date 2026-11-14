"""Persist metadata, never code, prompts, search queries or command output."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path

def database_path() -> Path:
    return Path(os.environ.get("CODEBRIDGE_AUDIT_DB", Path(__file__).parent / ".codebridge" / "audit.sqlite3"))

def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    connection.execute("""CREATE TABLE IF NOT EXISTS calls (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        tool TEXT NOT NULL, duration_ms REAL NOT NULL, error_code TEXT,
        output_chars INTEGER NOT NULL)""")
    return connection

def record(call_id: str, tool: str, duration_ms: float, error: str | None, output_chars: int) -> bool:
    connection = None
    try:
        connection = connect()
        with connection:
            connection.execute("INSERT INTO calls(id,tool,duration_ms,error_code,output_chars) VALUES(?,?,?,?,?)",
                               (call_id, tool, duration_ms, error, output_chars))
        return True
    except (OSError, sqlite3.Error):
        return False
    finally:
        if connection is not None:
            connection.close()

def metrics() -> dict:
    connection = connect()
    try:
        rows = connection.execute("SELECT tool,duration_ms,error_code,output_chars FROM calls").fetchall()
    finally:
        connection.close()
    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(row[0], []).append(row)
    summary = {}
    for tool, values in groups.items():
        durations = sorted(row[1] for row in values)
        errors: dict[str, int] = {}
        for row in values:
            if row[2]:
                errors[row[2]] = errors.get(row[2], 0) + 1
        summary[tool] = {"calls": len(values), "successful_calls": len(values) - sum(errors.values()),
                         "average_ms": round(sum(durations) / len(values), 2),
                         "p95_ms": round(durations[max(0, (95 * len(values) + 99) // 100 - 1)], 2),
                         "error_codes": errors}
    return {"total_calls": len(rows), "tools": summary,
            "scope": "Local tool executions; schema rejection before execution is not included."}
