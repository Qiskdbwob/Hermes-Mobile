"""Regression tests for the Flet/serious_python entry point."""

from __future__ import annotations

import ast
import runpy
from pathlib import Path

import flet as ft

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_passes_main_positionally(monkeypatch):
    """Flet 0.86 requires ``main`` as run()'s first positional argument.

    This reproduces the Android crash:
    ``TypeError: run() missing 1 required positional argument: 'main'``.
    """
    called: dict[str, object] = {}

    def fake_run(main, **kwargs):
        called["main"] = main
        called["kwargs"] = kwargs

    monkeypatch.setattr(ft, "run", fake_run)
    runpy.run_path(str(PROJECT_ROOT / "main.py"), run_name="__main__")

    assert callable(called["main"])
    assert called["kwargs"] == {"assets_dir": "assets"}


def test_entrypoint_exports_android_main():
    """serious_python imports module ``main`` and expects a callable main."""
    namespace = runpy.run_path(str(PROJECT_ROOT / "main.py"), run_name="main")
    assert callable(namespace["main"])


def test_all_script_entrypoints_pass_main_positionally():
    """No executable Flet entry point may rely on deprecated ``target=``."""
    entrypoints = (
        PROJECT_ROOT / "main.py",
        PROJECT_ROOT / "hermes_mobile" / "main.py",
        PROJECT_ROOT / "scripts" / "capture_views.py",
    )
    for path in entrypoints:
        tree = ast.parse(path.read_text(), filename=str(path))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"run", "app"}
        ]
        assert calls, f"no Flet runner found in {path}"
        for call in calls:
            assert isinstance(call.func, ast.Attribute)
            assert call.func.attr == "run", f"deprecated ft.app() remains in {path}"
            assert call.args, f"ft.run() must receive main positionally in {path}"
            assert not any(keyword.arg == "target" for keyword in call.keywords)
