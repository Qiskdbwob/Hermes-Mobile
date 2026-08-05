# Contributing to Hermes Mobile

Thank you for contributing! Hermes Mobile is a mobile AI agent for
Android, built with Python and Flet. It ports the Hermes Desktop
architecture (Nous Research) to mobile form factors. This guide
covers development setup, what to build, and how to get a PR merged.

---

## Before You Start

- Search [existing issues](https://github.com/plcunha/Hermes-Mobile/issues)
  and [open PRs](https://github.com/plcunha/Hermes-Mobile/pulls) before
  starting work. A duplicate PR costs you time and delays review.
- For larger changes, comment on the issue to signal you're working on it.

---

## Development Setup

### Prerequisites

| Requirement | Notes |
|---|---|
| **Git** | |
| **Python 3.9+** | 3.12 recommended; 3.9 required for APK compatibility |
| **uv** | Fast Python package manager ([install](https://docs.astral.sh/uv/)) |

### Clone and install

```bash
git clone git@github.com:plcunha/Hermes-Mobile.git
cd hermes-mobile
uv venv --python 3.12 .venv
export PATH="$PWD/.venv/bin:$HOME/.local/bin:$PATH"
uv pip install -e ".[dev]"
```

### Dual-Flet test environment

The app must work on **both** Flet 0.86.5 (current build line) and
Flet 0.28.x (Python 3.9 CI). Create the 3.9 venv once:

```bash
uv python install 3.9
uv venv --python 3.9 /tmp/hermes-mobile-py39
/tmp/hermes-mobile-py39/bin/pip install "flet==0.28.3" openai httpx pydantic pydantic-settings python-dotenv sqlite-utils aiofiles pyyaml rich tenacity tiktoken markdown beautifulsoup4 lxml cryptography keyring platformdirs apscheduler croniter plyer pytest pytest-asyncio pytest-cov ruff
/tmp/hermes-mobile-py39/bin/pip install -e .
```

### Run tests

```bash
# Current Flet (3.12)
.venv/bin/python -m pytest -q

# Legacy Flet (3.9)
/tmp/hermes-mobile-py39/bin/python -m pytest -q

# Lint
uvx ruff check .
uvx ruff format --check .
```

### Desktop testing

```bash
HERMES_MOBILE_LAYOUT=mobile uv run --python 3.12 python main.py
```

---

## What We Want

1. **Bug fixes** — fix the whole class, not the symptom. Verify with tests.
2. **Provider support** — new `ProviderProfile` entries in
   `hermes_mobile/providers/__init__.py`. Follow the existing pattern.
3. **New platform adapters** — add a `*Adapter` class inheriting
   `BasePlatformAdapter` in the gateway module.
4. **Tests** — keep the suite green. Add regression coverage for every
   agent-loop, storage, entrypoint, tool, and Android lifecycle fix.
5. **Mobile-native polish** — NavigationBar, bottom sheets, snack bars,
   proper keyboard handling. Touch targets ≥ 44 dp.

---

## What We Don't Want

- **Deps without justification** — every dependency increases APK size.
- **Breaking the agent loop** — `run_conversation` is the heart.
- **Desktop-only patterns** — avoid assumptions about keyboard, mouse,
  large screens, or filesystem structure.

---

## Design Principles

1. **Mobile-first, Desktop-compatible** — NavigationBar on phones,
   NavigationRail on desktop.
2. **Config is external** — `.env` or `HermesMobileSettings`, not
   hardcoded constants.
3. **Graceful degradation** — missing API key → helpful message, not a crash.
4. **Security is not optional** — path traversal protection, AST-based
   evaluation, encrypted memory, and pairing codes are load-bearing.
5. **Cron is self-contained** — JSON files + advisory locks, no external
   services.

---

## Footprint Ladder

When adding capability, prefer this order:

1. Extend existing code
2. CLI script + cron job
3. Skill (Python file/package, no core changes)
4. Plugin (plugin.yaml manifest, discovered at runtime)
5. Platform adapter (gateway module)
6. New core tool (last resort — every tool ships on every API call)

---

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

| Type | Use for |
|---|---|
| `fix` | Bug fixes |
| `feat` | New features |
| `docs` | Documentation |
| `test` | Tests |
| `refactor` | No behavior change |
| `chore` | Build, CI, deps |

Scopes: `ui`, `agent`, `tools`, `skills`, `memory`, `cron`, `gateway`,
`remote`, `providers`, `settings`, `build`.

Examples:
```
fix(ui): snackbar no longer overlaps bottom navigation
feat(settings): add transactional draft/save/discard model
test(agent): cover streaming tool-call reconstruction
```

---

## PR Process

### Branch naming

```
fix/description       # Bug fixes
feat/description      # New features
docs/description      # Documentation
test/description      # Tests
refactor/description  # Code restructuring
```

### Before submitting

1. `uvx ruff check .` — zero errors
2. `uvx ruff format --check .` — clean
3. `.venv/bin/python -m pytest -q` — all green
4. `/tmp/hermes-mobile-py39/bin/python -m pytest -q` — all green on 3.9
5. Test on desktop with `HERMES_MOBILE_LAYOUT=mobile` if UI changed

### PR description template

- **What** changed and **why**
- **How to test** (steps, not just "run tests")
- **Platforms tested** (e.g. macOS, Android emulator)
- Reference related issues

---

## License

By contributing, you agree that your contributions will be licensed
under the [MIT License](LICENSE).
