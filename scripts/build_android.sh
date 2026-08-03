#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export FLET_CLI_SKIP_FLUTTER_DOCTOR="${FLET_CLI_SKIP_FLUTTER_DOCTOR:-true}"

flet build apk --yes \
  --exclude .venv \
  --exclude .flet \
  --exclude .pytest_cache \
  --exclude .ruff_cache \
  --exclude .buildozer \
  --exclude .git \
  --exclude .github \
  --exclude build \
  --exclude tests \
  --exclude docs \
  --exclude scripts \
  --exclude test_app.py
