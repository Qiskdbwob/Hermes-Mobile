# Hermes Mobile - Development Guide

Hermes Mobile is a mobile AI agent for Android, built with Python and Flet. It ports the Hermes Desktop architecture (Nous Research) to mobile form factors, keeping the core agent loop, tool system, and skill/memory infrastructure while adding mobile-native UI, Android APK builds, and a streamlined gateway for push notifications.

---

## Project Overview

Hermes Mobile runs the same agent core concept as Hermes Desktop — an OpenAI-compatible chat loop with tool-calling — adapted for mobile:

- **Flet UI** — Material 3 interface with NavigationBar (mobile) / NavigationRail (desktop), 8 views
- **Agent Core** — Streaming tool-calling loop via OpenRouter/OpenAI/Anthropic/Gemini
- **14 Built-in Tools** — web search, file ops, shell, browser, memory, delegation, calculation
- **SQLite Memory** — Encrypted conversation + long-term memory with TTL-based expiration
- **28 Toolsets** — Mirrors Hermes Desktop toolset organization (web, terminal, file, browser, vision, etc.)
- **Skill System** — Python file/package skills with YAML schema, hot-reloadable
- **9 Provider Profiles** — OpenRouter, OpenAI, Anthropic, Google, Groq, Together, DeepSeek, xAI, Ollama
- **Gateway System** — Code-based pairing flow, Telegram bot adapter, extensible platform adapters
- **Plugin System** — ABC-based plugin registry with discovery, config schemas
- **Cron Scheduler** — JSON-backed job persistence, ticker-based execution, 4 default jobs
- **i18n** — English and Portuguese (pt-br) locale system, dot-notation key lookup
- **Context Compression** — Token estimation + mid-conversation summarization (placeholder-based)
- **Prompt Caching** — Anthropic/OpenRouter cache breakpoints for cost savings (~90% on system prompt)
- **Path Security** — Directory traversal prevention, sandboxed file access
- **Safe Evaluation** — AST-based math expression evaluation (no `eval()`)

---

## Architecture

```
main.py                         # Flet entry point (ft.app target)
hermes_mobile/
├── __init__.py                  # Package version
├── main.py                      # HermesMobileApp — page setup, component init, nav, lifecycle
├── toolsets.py                  # Toolset definitions (28 toolsets, mirroring desktop)
├── config/
│   └── settings.py              # Pydantic-based HermesMobileSettings (.env + defaults)
├── core/
│   ├── agent.py                 # MobileAgent — conversation loop, tool execution, streaming
│   ├── context_compressor.py    # Token estimation + mid-conversation compression
│   ├── delegation.py            # Subagent spawning for parallel task execution
│   └── prompt_caching.py        # Cache breakpoints for Anthropic/OpenRouter
├── memory/
│   └── provider.py              # MobileMemoryProvider — SQLite + Fernet encryption
├── skills/
│   └── manager.py               # MobileSkillManager — discovery, loading, execution
├── tools/
│   ├── agent_tools.py           # session_search, memory, clarify tools
│   ├── path_security.py         # Traversal protection, allowed directory sandbox
│   ├── security.py              # AST-based safe math evaluator
│   └── web_tools.py             # DuckDuckGo search, web extract, lightweight browser
├── providers/
│   └── __init__.py              # ProviderProfile ABC + 9 built-in provider configs
├── cron/
│   ├── scheduler.py             # CronJob, CronScheduler ticker, JSON persistence
│   ├── backup_data.py           # Daily backup cron script
│   ├── check_updates.py         # Daily update check cron script
│   ├── cleanup_memory.py        # Daily memory cleanup cron script
│   └── sync_conversations.py    # Conversation sync cron script (TODO)
├── gateway/
│   ├── mobile_gateway.py        # GatewayManager, PairingManager, StreamConsumer, BasePlatformAdapter
│   └── telegram_adapter.py      # Telegram long-polling bot adapter
├── plugins/
│   └── __init__.py              # PluginRegistry, BasePlugin, Achievements/Kanban/Security plugins
├── locales/
│   ├── __init__.py              # i18n loader, t() function, locale switching
│   ├── en.json                  # English translations (160 keys)
│   └── pt-br.json               # Portuguese translations
└── ui/
    ├── chat_view.py             # Chat interface — markdown rendering, tool call display
    ├── settings_view.py         # Provider, agent, appearance, advanced settings
    ├── tools_view.py            # Toolset browser by category
    ├── skills_view.py           # Skill list, create, install, toggle
    ├── memory_view.py           # Stats, conversations/memory/skill tabs
    ├── cron_view.py             # Job list, ticker status, add/edit/run/del
    ├── gateway_view.py          # Gateway toggle, pairing code management
    └── plugins_view.py          # Plugin list, load/unload
```

---

## Contribution Rubric

### What We Want

- **Fix real bugs, well.** A good fix targets an actual symptom, fixes the whole bug class — sibling call paths included — and is verified.
- **Expand provider support.** New provider profiles in `hermes_mobile/providers/__init__.py` are welcome. Follow the existing `ProviderProfile` pattern with proper `env_vars`, `base_url`, and `fallback_models`.
- **New platform adapters.** Add a `*Adapter` class inheriting `BasePlatformAdapter` in the gateway module.
- **Refactor god-files into clean modules.** The core agent (`agent.py` at ~800 lines) is a candidate.
- **Keep the core narrow.** New *model tools* are expensive — every tool ships on every API call. Prefer: extend existing code -> skill -> plugin -> new core tool.
- **Tests.** Keep the pytest suite green and add regression coverage for every agent-loop, storage, entrypoint, tool, and Android lifecycle fix. The current suite has 700+ tests; never assume a UI-only change is safe without running it.
- **Mobile-native polish.** Flet views should feel native on Android — NavigationBar, bottom sheets, snack bars, proper keyboard handling.

### What We Don't Want

- **Adding deps without justification.** Every dependency increases APK size and Android build complexity. Before adding a package, check if the stdlib or existing deps cover it.
- **Breaking the agent loop.** The conversation loop (`run_conversation` in `agent.py`) is the heart. Don't mutate past messages, break role alternation, or invalidate prompt caching mid-conversation (except via `context_compressor`).
- **Desktop-only patterns.** Avoid patterns that assume a keyboard+mouse, large screen, or filesystem structure that doesn't exist on Android.

### Design Principles

1. **Mobile-first, Desktop-compatible.** The Flet UI adapts between mobile (NavigationBar) and desktop (NavigationRail). All logic must work in both.
2. **Config is external, not hardcoded.** Everything from provider selection to encryption keys lives in `.env` or `HermesMobileSettings`, not in module-level constants.
3. **Graceful degradation.** If a provider key is missing, the app should show a helpful message, not crash.
4. **Security is not optional.** Path traversal protection, AST-based evaluation, encrypted memory, and the pairing code system are load-bearing.
5. **Cron is self-contained.** The scheduler uses JSON files and advisory file locks — no external database or supervisor. Keep it that way.

---

## Footprint Ladder (how to add capability)

When adding new functionality, prefer options in this order:

1. **Extend existing code** — Add a function to an existing module
2. **CLI script + cron job** — A standalone Python script in `hermes_mobile/cron/`
3. **Skill** — A Python file or package in the skills directory (no core changes)
4. **Plugin** — A plugin package with `plugin.yaml` manifest (discovered at runtime)
5. **Platform adapter** — A gateway adapter class for a new messaging platform
6. **New core tool** — Last resort. Every tool ships on every API call. Only if the capability is genuinely core (like `web_search` or `read_file`).

---

## Key Implementation Details

### Agent Loop (`core/agent.py`)

```
1. Add user message to conversation history
2. Format messages with caching (supports_caching -> apply_cache_control)
3. Check compression threshold (needs_compression -> compress_messages)
4. Call model API (streaming or non-streaming)
5. Extract tool calls from response
6. Execute each tool (built-in -> skills)
7. Add tool results as messages
8. Repeat from step 2 until no tool calls or max_iterations reached
9. Persist conversation to memory provider
```

### Memory Provider (`memory/provider.py`)

- SQLite with 3 tables: `conversations`, `memory_entries`, `skill_memory`
- Fernet encryption via PBKDF2-derived key (device-specific or user-provided)
- Simple keyword-based relevance scoring (no embeddings yet)
- TTL-based expiration with `cleanup_expired()`

### Provider Profiles (`providers/__init__.py`)

Each provider is a `ProviderProfile` dataclass with:
- `api_mode`, `base_url`, `env_vars`, `auth_type`
- Vision support flags
- `fallback_models` tuple
- Provider-specific hooks: `prepare_messages`, `build_extra_body`, `build_api_kwargs_extras`
- 9 built-in profiles from OpenRouter to Ollama

### Gateway System (`gateway/mobile_gateway.py`)

- **PairingManager**: Code-based authorization with rate limiting (5 failures -> 1h lockout)
- **GatewayManager**: Async lifecycle with platform adapter management, health-check loop
- **GatewayStreamConsumer**: Streaming response consumer with delta/tool/commentary callbacks
- **BasePlatformAdapter**: Abstract base for messaging platform adapters (send/edit/delete/handle)

### Cron Scheduler (`cron/scheduler.py`)

- JSON-backed `jobs.json` with advisory `fcntl` file locks
- Background ticker thread (60s interval)
- Supports cron expressions via `croniter` (optional, graceful fallback) and "oneshot" schedules
- Run-history stored as JSONL in `cron/output/`
- 4 default jobs: cleanup memory (daily 3am), sync conversations (every 15min), check updates (daily noon), backup data (daily 4am)

---

## Current Issues & Gaps vs Hermes Desktop

| Area | Hermes Desktop | Hermes Mobile | Status |
|------|---------------|---------------|--------|
| Agent Core | Full `run_agent.py` with negotiation mode | Simplified `MobileAgent`, no negotiation | OK for mobile |
| Tools | ~50+ tools (terminal, browser, kanban, etc.) | 14 built-in tools, 28 toolset definitions | Partial |
| Browser | CDP-based browser automation | httpx+BS4 lightweight navigation | Minimal |
| Voice | TTS/STT in gateway | Not implemented | Gap |
| Computer Use | macOS CUA driver | Not implemented | Gap |
| Desktop App | Electron app | Flet desktop mode | OK |
| Tests | Extensive pytest suite | 700+ pytest tests | Good coverage |
| Docker | Multi-arch, Docker Compose | Not implemented | Gap |
| Kanban | Multi-agent kanban board | Plugin stub only | Gap |
| Smart Home | Home Assistant integration | Tool gating only | Gap |
| Session Search | FTS5 + LLM summarization | SQLite LIKE only | Basic |

---

## Build & Run

```bash
# Development (editable install)
pip install -e ".[dev]"

# Run on desktop (for testing)
flet run main.py

# Run on Android device (USB debugging enabled)
flet run main.py --target=android

# Build a release APK (uses Flet 0.86 and excludes development payload)
./scripts/build_android.sh
```

### Prerequisites

- Python 3.9+
- Android SDK (for building APK)
- Flet (`pip install flet`)

### Environment

Copy `.env.example` to `.env` and set at least one API key:
- `OPENROUTER_API_KEY` (recommended — access to 300+ models)
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`

---

## Skills

Create custom skills in `~/.hermes_mobile/skills/`:

```python
# my_skill/main.py
async def execute(query: str) -> str:
    """Your skill logic here"""
    return f"Processed: {query}"
```

```yaml
# my_skill/skill.yaml
name: my_skill
description: "My custom skill"
schema:
  type: object
  properties:
    query:
      type: string
      description: "Input query"
  required: [query]
```

---

## License

MIT License — See LICENSE file for details.

Based on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.
