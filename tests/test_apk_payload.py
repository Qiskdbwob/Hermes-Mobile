"""Tests for APK payload auditing."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from io import BytesIO
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "audit_apk_payload", Path("scripts/audit_apk_payload.py")
)
audit_module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = audit_module
SPEC.loader.exec_module(audit_module)
audit = audit_module.audit


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return out.getvalue()


def _write_apk(path: Path, app_entries: dict[str, bytes], site_entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("assets/app.zip", _zip_bytes(app_entries))
        z.writestr("assets/sitepackages.zip", _zip_bytes(site_entries))
        z.writestr("classes.dex", b"dex")


def test_apk_payload_audit_passes_clean_app_payload(tmp_path: Path):
    apk = tmp_path / "clean.apk"
    _write_apk(
        apk,
        {"main.pyc": b"ok", "hermes_mobile/main.pyc": b"ok"},
        {"openai/__init__.pyc": b"ok"},
    )

    summary = audit(apk)

    assert summary["passed"] is True
    assert summary["app_zip"]["forbidden"] == []


def test_apk_payload_audit_rejects_project_payload(tmp_path: Path):
    apk = tmp_path / "dirty.apk"
    _write_apk(
        apk,
        {
            "main.pyc": b"ok",
            "README.md": b"not runtime",
            "docs/plan.md": b"not runtime",
            "hermes_mobile/__pycache__/main.cpython-312.pyc": b"host cache",
        },
        {"openai/__init__.pyc": b"ok"},
    )

    summary = audit(apk)

    assert summary["passed"] is False
    assert "README.md" in summary["app_zip"]["forbidden"]
    assert "docs/plan.md" in summary["app_zip"]["forbidden"]
    assert "hermes_mobile/__pycache__/main.cpython-312.pyc" in summary["app_zip"]["forbidden"]


def test_apk_payload_audit_rejects_dependency_test_payload(tmp_path: Path):
    apk = tmp_path / "deps.apk"
    _write_apk(
        apk,
        {"main.pyc": b"ok"},
        {"pip/__init__.pyc": b"pip", "croniter/tests/test_croniter.pyc": b"test"},
    )

    summary = audit(apk)

    assert summary["passed"] is False
    assert summary["sitepackages_zip"]["warnings"]["pip/"]["count"] == 1
    assert summary["sitepackages_zip"]["warnings"]["croniter/tests/"]["count"] == 1
