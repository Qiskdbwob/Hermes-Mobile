#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export FLET_CLI_SKIP_FLUTTER_DOCTOR="${FLET_CLI_SKIP_FLUTTER_DOCTOR:-true}"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

# Flet's exclude matcher does not remove nested interpreter caches reliably.
# Clean only app-source caches before packaging; compile-app will generate the
# optimized top-level .pyc files that Serious Python expects at runtime.
"$PYTHON_BIN" -c '
from pathlib import Path
import shutil

roots = (Path("hermes_mobile"), Path("__pycache__"))
for root in roots:
    if root.name == "__pycache__":
        shutil.rmtree(root, ignore_errors=True)
        continue
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    for pattern in ("*.pyc", "*.pyo"):
        for compiled in root.rglob(pattern):
            compiled.unlink(missing_ok=True)
'

flet build apk --yes \
  --exclude .venv \
  --exclude .flet \
  --exclude .pytest_cache \
  --exclude .ruff_cache \
  --exclude .mypy_cache \
  --exclude .coverage \
  --exclude htmlcov \
  --exclude __pycache__ \
  --exclude '**/__pycache__/**' \
  --exclude '*.py[co]' \
  --exclude '**/*.py[co]' \
  --exclude .buildozer \
  --exclude .git \
  --exclude .github \
  --exclude build \
  --exclude tests \
  --exclude docs \
  --exclude scripts \
  --exclude test_app.py \
  --exclude AGENTS.md \
  --exclude CLAUDE.md \
  --exclude README.md \
  --exclude CONTRIBUTING.md \
  --exclude SECURITY.md \
  --exclude .env \
  --exclude .env.example \
  --exclude .gitattributes \
  --exclude .gitignore \
  --exclude pyproject.toml \
  --exclude setup.py \
  --exclude buildozer.spec

APK_PATH="$ROOT_DIR/build/apk/hermes-mobile.apk"
if [[ -f "$APK_PATH" ]]; then
  "$PYTHON_BIN" scripts/audit_apk_payload.py "$APK_PATH"
fi
