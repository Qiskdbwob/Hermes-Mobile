"""Path security validation helpers.

Extracts the resolve() + relative_to() and .. traversal check
patterns from Hermes Desktop path_security.py.
"""

from pathlib import Path
from typing import Optional


def validate_within_dir(path: Path, root: Path) -> Optional[str]:
    """Ensure *path* resolves to a location within *root*.

    Returns an error message string if validation fails, or None if the
    path is safe. Uses Path.resolve() to follow symlinks and normalize
    .. components.
    """
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        resolved.relative_to(root_resolved)
    except (ValueError, OSError) as exc:
        return f"Path escapes allowed directory: {exc}"
    return None


def has_traversal_component(path_str: str) -> bool:
    """Return True if *path_str* contains .. traversal components."""
    parts = Path(path_str).parts
    return ".." in parts


def get_safe_home_dir() -> Path:
    """Get the home directory safely."""
    try:
        return Path.home()
    except Exception:
        return Path.cwd()


def get_allowed_directories() -> list[Path]:
    """Get the list of directories the agent is allowed to access.

    Mirrors the desktop contract: the user's document folders plus the
    current working directory (the app workspace). The workspace is where
    the agent reads/writes project files; without it the sandbox is useless
    on mobile where Documents/Downloads often do not exist.
    """
    home = get_safe_home_dir()
    allowed = [
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
    ]
    # The app workspace (cwd) is always allowed — the agent must be able to
    # read and write the files it is working on.
    try:
        cwd = Path.cwd().resolve()
        if cwd not in allowed:
            allowed.append(cwd)
    except OSError:
        pass
    return [d for d in allowed if d.exists()]


def validate_and_resolve_path(
    raw_path: str,
    extra_dirs: Optional[list[Path]] = None,
    base_dir: Optional[Path] = None,
) -> tuple[Optional[Path], Optional[str]]:
    """Validate and resolve a user-provided path.

    Args:
        raw_path: User-provided path (absolute or relative).
        extra_dirs: Additional allowed roots (e.g. the active project workspace).
        base_dir: When *raw_path* is relative, resolve it against this directory
            first (e.g. the active workspace), so "note.txt" means
            ``<workspace>/note.txt``.

    Returns (resolved_path, error_message). One will always be None.
    """
    path = Path(raw_path).expanduser()
    if base_dir is not None and not path.is_absolute():
        path = base_dir / path

    if has_traversal_component(str(path)):
        return None, "Path traversal detected: '..' components are not allowed"

    try:
        resolved = path.resolve()
    except OSError as exc:
        return None, f"Cannot resolve path: {exc}"

    allowed = get_allowed_directories()
    if extra_dirs:
        allowed = list(allowed) + [d for d in extra_dirs if d is not None]
    for root in allowed:
        if validate_within_dir(resolved, root) is None:
            return resolved, None

    return None, f"Path '{raw_path}' is outside allowed directories"
