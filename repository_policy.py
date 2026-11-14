"""Application-level read policy for trusted local repositories."""
from __future__ import annotations
from pathlib import Path, PureWindowsPath

IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build",
           ".dsh", ".npm-cache", ".tmp", ".codebridge", ".acl-recovery", ".ssh", ".aws", ".azure", ".kube"}
MAX_FILE_BYTES = 256 * 1024

class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

def blocked(parts: tuple[str, ...]) -> bool:
    for part in parts:
        lower = part.lower()
        if lower in IGNORED or lower.startswith((".env", ".credentials")):
            return True
        if lower in {".npmrc", ".netrc", "id_rsa", "id_ed25519", "credentials.json", "credentials.yaml",
                     "credentials.yml", "secrets.json", "secrets.yaml", "secrets.yml"}:
            return True
        if Path(lower).suffix in {".pem", ".key", ".p12", ".pfx"}:
            return True
    return False

def safe_path(root: Path, value: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value or len(value) > 500 or "\0" in value:
        raise ToolError("INVALID_PATH", "Supply a nonempty repository-relative path.")
    relative = Path(value.replace("\\", "/"))
    windows = PureWindowsPath(value)
    if relative.is_absolute() or windows.drive or windows.root or ".." in relative.parts or any(":" in part for part in relative.parts):
        raise ToolError("PATH_OUTSIDE_ROOT", "Absolute paths and parent traversal are not allowed.")
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
    if any(part.endswith((" ", ".")) or part.lower().split(".")[0] in reserved for part in relative.parts):
        raise ToolError("PATH_BLOCKED", "Windows device names and trailing-dot/space path aliases are excluded.")
    if blocked(relative.parts):
        raise ToolError("PATH_BLOCKED", "Dependency, runtime, and known credential paths are excluded.")
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink() or candidate.is_junction():
            raise ToolError("LINK_NOT_ALLOWED", "Symbolic links and junctions are not read.")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ToolError("PATH_OUTSIDE_ROOT", "Path must remain inside the configured repository.")
    if must_exist and not resolved.exists():
        raise ToolError("FILE_NOT_FOUND", "The requested path does not exist.")
    return resolved

def text_content(path: Path) -> str:
    if not path.is_file():
        raise ToolError("NOT_A_FILE", "Select a regular text file.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ToolError("FILE_TOO_LARGE", "File exceeds the 256 KiB read budget.")
    if b"\0" in data:
        raise ToolError("BINARY_FILE", "Binary files are not returned as code context.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ToolError("UNSUPPORTED_ENCODING", "Expected a UTF-8 text file.") from exc
