"""Project workspace tools for Hermes Mobile (desktop parity).

The desktop shell lets the user work inside named projects (workspaces). On
mobile, projects are directories under the app data dir; switching a project
changes the agent's working directory so file tools stay scoped to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from hermes_mobile.config import settings as settings_module


def is_safe_project_name(name: str) -> bool:
    """Return whether *name* is one project-directory component."""
    if not isinstance(name, str):
        return False
    value = name.strip()
    return bool(
        value
        and value == name
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and not Path(value).is_absolute()
        and Path(value).name == value
    )


def resolve_project_directory(projects_dir: Path, name: str) -> Optional[Path]:
    """Resolve an existing real project without following directory symlinks."""
    if not is_safe_project_name(name) or projects_dir.is_symlink():
        return None
    candidate = projects_dir / name
    if candidate.is_symlink() or not candidate.is_dir():
        return None
    try:
        root = projects_dir.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if resolved.parent == root else None


def _projects_dir() -> Path:
    path = settings_module.get_settings().get_data_dir() / "projects"
    if path.is_symlink():
        raise ValueError("Unsafe projects directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_project_file() -> Path:
    return settings_module.get_settings().get_data_dir() / "config" / "current_project.txt"


def get_current_project() -> Optional[str]:
    """Return the active project name (or None)."""
    try:
        f = _current_project_file()
        if f.exists():
            name = f.read_text(encoding="utf-8").strip()
            if resolve_project_directory(_projects_dir(), name) is not None:
                return name
    except Exception:
        pass
    return None


async def project_list_tool() -> Dict[str, Any]:
    """List projects and the active one."""
    root = _projects_dir()
    projects = sorted(
        path.name
        for path in root.iterdir()
        if resolve_project_directory(root, path.name) is not None
    )
    return {"projects": projects, "current": get_current_project()}


async def project_create_tool(name: str) -> Dict[str, Any]:
    """Create a new project directory."""
    if not name or not name.strip():
        return {"error": "name is required"}
    # Keep names filesystem-safe
    safe = "".join(c for c in name.strip() if c.isalnum() or c in ("-", "_", " ")).strip()
    if not safe:
        return {"error": "Project name must contain letters or numbers"}
    try:
        root = _projects_dir()
        project = root / safe
        if project.is_symlink():
            return {"error": f"Unsafe project path: {safe}"}
        project.mkdir(parents=True, exist_ok=True)
        if resolve_project_directory(root, safe) is None:
            return {"error": f"Unsafe project path: {safe}"}
        return {"ok": True, "project": safe, "current": get_current_project()}
    except Exception as e:
        return {"error": str(e)}


async def project_switch_tool(name: str, agent: Optional[Any] = None) -> Dict[str, Any]:
    """Switch the active project (and the agent's working directory)."""
    if not name:
        return {"error": "name is required"}
    if not is_safe_project_name(name):
        return {"error": "Invalid project name"}
    project_dir = resolve_project_directory(_projects_dir(), name)
    if project_dir is None:
        return {"error": f"Project not found: {name}"}
    try:
        f = _current_project_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(name, encoding="utf-8")
        if agent is not None:
            # Re-point file tools at the project workspace.
            agent._workspace = project_dir
        return {"ok": True, "project": name}
    except Exception as e:
        return {"error": str(e)}
