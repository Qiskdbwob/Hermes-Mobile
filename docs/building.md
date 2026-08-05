---
layout: default
---

# Building from Source

## Prerequisites

- Python 3.9+ (3.12 recommended)
- [uv](https://docs.astral.sh/uv/) for package management
- Android SDK (for APK builds)
- Flutter SDK (auto-installed by Flet during `flet build apk`)

## Desktop Testing

```bash
git clone git@github.com:plcunha/Hermes-Mobile.git
cd hermes-mobile
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
cp .env.example .env
# Add your API keys to .env
HERMES_MOBILE_LAYOUT=mobile uv run --python 3.12 python main.py
```

The mobile layout renders on desktop with `HERMES_MOBILE_LAYOUT=mobile`.

## Running Tests

```bash
# Current Flet (Python 3.12)
.venv/bin/python -m pytest -q

# Legacy Flet (Python 3.9 — CI gate)
uv python install 3.9
uv venv --python 3.9 /tmp/hermes-mobile-py39
/tmp/hermes-mobile-py39/bin/pip install "flet==0.28.3" # plus deps
/tmp/hermes-mobile-py39/bin/pip install -e .
/tmp/hermes-mobile-py39/bin/python -m pytest -q

# Lint
uvx ruff check .
uvx ruff format --check .
```

## Building the APK

```bash
./scripts/build_android.sh
```

The APK lands at `build/apk/hermes-mobile.apk`.

The build script uses `flet build apk` (Flutter + serious_python) and automatically excludes development payload (tests, venv, docs, caches). The resulting APK is ~215 MB for all ABIs.

## CI

GitHub Actions runs on every push and PR against `main`:

- Ruff lint + format check
- Pytest on Python 3.9 and 3.12
- Read-only permissions, no token exposure

## Project Structure

See the [README](https://github.com/plcunha/Hermes-Mobile#architecture) for the full architecture diagram.
