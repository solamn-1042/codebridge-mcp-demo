"""Fixed-argument execution with bounded output and timeout cleanup."""
from __future__ import annotations
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    truncated: bool

def execute(command: list[str], root: Path, timeout: float, limit: int = 24000) -> CommandResult:
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        kwargs = {"start_new_session": True} if os.name != "nt" else {}
        process = subprocess.Popen(command, cwd=root, stdout=out, stderr=err, shell=False, **kwargs)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    subprocess.run(
                        [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                         "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True, timeout=5, check=False)
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except (OSError, subprocess.TimeoutExpired):
                # Preserve the original timeout if tree cleanup is unavailable.
                if process.poll() is None:
                    process.kill()
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
            raise
        sizes = [stream.tell() for stream in (out, err)]
        chunks = []
        for stream in (out, err):
            stream.seek(0)
            chunks.append(stream.read(limit).decode("utf-8", errors="replace"))
        return CommandResult(process.returncode, chunks[0], chunks[1], any(size > limit for size in sizes))
