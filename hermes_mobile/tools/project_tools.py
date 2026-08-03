"""Project workspace tools for Hermes Mobile (desktop parity).

The desktop shell lets the user work inside named projects (workspaces). On
mobile, projects are directories under the app data dir; switching a project
changes the agent's working directory so file tools stay scoped to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from hermes_mobile.config.settings import get_settings


def _projects_dir() -> Path:
    path = get_settings().get_data_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _current_project_file() -> Path:
    return get_settings().get_data_dir() / "config" / "current_project.txt"


def get_current_project() -> Optional[str]:
    """Return the active project name (or None)."""
    try:
        f = _current_project_file()
        if f.exists():
            name = f.read_text(encoding="utf-8").strip()
            if name and (_projects_dir() / name).is_dir():
                return name
    except Exception:
        pass
    return None


async def project_list_tool() -> Dict[str, Any]:
    """List projects and the active one."""
    projects = sorted(p.name for p in _projects_dir().iterdir() if p.is_dir())
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
        (_projects_dir() / safe).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "project": safe, "current": get_current_project()}
    except Exception as e:
        return {"error": str(e)}


async def project_switch_tool(name: str, agent: Optional[Any] = None) -> Dict[str, Any]:
    """Switch the active project (and the agent's working directory)."""
    if not name:
        return {"error": "name is required"}
    project_dir = _projects_dir() / name
    if not project_dir.is_dir():
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
