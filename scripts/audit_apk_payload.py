#!/usr/bin/env python3
"""Audit Hermes Mobile APK payload contents.

The APK embeds two nested archives produced by Flet/serious_python:
- assets/app.zip: app code and project payload
- assets/sitepackages.zip: Python dependencies

This script is intentionally conservative: app.zip development/repository files are
release blockers; third-party dependency test/pip payload is reported separately
because removing it may require changing the Flet/serious_python packaging step.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

APP_FORBIDDEN_EXACT = {
    ".env",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "README.md",
    "SECURITY.md",
    "build_android.sh",
    "buildozer.spec",
    "pyproject.toml",
    "setup.py",
}
APP_FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/",
    ".venv/",
    ".flet/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".buildozer/",
    "build/",
    "docs/",
    "scripts/",
    "tests/",
    "htmlcov/",
)
APP_FORBIDDEN_CONTAINS = (
    "/__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
)
SITEPACKAGES_WARN_PREFIXES = (
    "pip/",
    "pip-",
    "setuptools/",
    "wheel/",
    "regex/tests/",
    "croniter/tests/",
    "certifi/tests/",
    "sniffio/_tests/",
)


@dataclass(frozen=True)
class ArchiveSummary:
    entries: int
    uncompressed_bytes: int
    top_level_bytes: dict[str, int]
    forbidden: list[str]
    warnings: dict[str, dict[str, int]]


def _top_level_sizes(infos: list[zipfile.ZipInfo]) -> dict[str, int]:
    sizes: dict[str, int] = defaultdict(int)
    for info in infos:
        top = info.filename.split("/", 1)[0]
        sizes[top] += info.file_size
    return dict(sorted(sizes.items(), key=lambda item: item[1], reverse=True))


def _is_forbidden_app_path(name: str) -> bool:
    normalized = name.lstrip("/")
    return (
        normalized in APP_FORBIDDEN_EXACT
        or any(normalized.startswith(prefix) for prefix in APP_FORBIDDEN_PREFIXES)
        or any(marker in f"/{normalized}" for marker in APP_FORBIDDEN_CONTAINS)
        or normalized.endswith((".pyo",))
    )


def _summarize_inner(data: bytes, *, app_archive: bool) -> ArchiveSummary:
    with zipfile.ZipFile(BytesIO(data)) as inner:
        infos = inner.infolist()
        names = [info.filename for info in infos]
        forbidden = sorted(name for name in names if app_archive and _is_forbidden_app_path(name))
        warnings: dict[str, dict[str, int]] = {}
        if not app_archive:
            for prefix in SITEPACKAGES_WARN_PREFIXES:
                matching = [info for info in infos if info.filename.startswith(prefix)]
                if matching:
                    warnings[prefix] = {
                        "count": len(matching),
                        "uncompressed_bytes": sum(info.file_size for info in matching),
                    }
        return ArchiveSummary(
            entries=len(infos),
            uncompressed_bytes=sum(info.file_size for info in infos),
            top_level_bytes=_top_level_sizes(infos),
            forbidden=forbidden,
            warnings=warnings,
        )


def audit(apk_path: Path) -> dict[str, object]:
    if not apk_path.exists():
        raise FileNotFoundError(apk_path)
    with zipfile.ZipFile(apk_path) as apk:
        names = set(apk.namelist())
        missing = [
            name for name in ("assets/app.zip", "assets/sitepackages.zip") if name not in names
        ]
        if missing:
            raise RuntimeError(f"missing nested archives: {', '.join(missing)}")
        app = _summarize_inner(apk.read("assets/app.zip"), app_archive=True)
        sitepackages = _summarize_inner(apk.read("assets/sitepackages.zip"), app_archive=False)
        outer_top = _top_level_sizes(apk.infolist())
    return {
        "apk": str(apk_path),
        "apk_bytes": apk_path.stat().st_size,
        "outer_top_level_bytes": outer_top,
        "app_zip": app.__dict__,
        "sitepackages_zip": sitepackages.__dict__,
        "passed": not app.forbidden,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path, help="Path to Hermes-Mobile.apk")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args(argv)

    summary = audit(args.apk)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(f"APK: {summary['apk']}")
        print(f"Size: {summary['apk_bytes']} bytes")
        app = summary["app_zip"]
        site = summary["sitepackages_zip"]
        print(f"app.zip: {app['entries']} entries, {app['uncompressed_bytes']} bytes")
        print(f"sitepackages.zip: {site['entries']} entries, {site['uncompressed_bytes']} bytes")
        if app["forbidden"]:
            print("Forbidden app payload:")
            for name in app["forbidden"][:100]:
                print(f"- {name}")
            if len(app["forbidden"]) > 100:
                print(f"... {len(app['forbidden']) - 100} more")
        if site["warnings"]:
            print("Dependency payload warnings:")
            for prefix, item in site["warnings"].items():
                print(f"- {prefix}: {item['count']} entries, {item['uncompressed_bytes']} bytes")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
