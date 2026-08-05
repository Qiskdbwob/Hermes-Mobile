<p align="center">
  <img src="assets/hero.png" alt="Hermes Mobile" width="100%">
</p>

# Hermes Mobile ☤

<p align="center">
  <strong>The mobile AI agent for Android — Hermes Desktop, on your phone.</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img src="https://img.shields.io/badge/Based%20on-Hermes%20Agent-blueviolet?style=for-the-badge" alt="Based on Hermes Agent"></a>
  <a href="https://flet.dev/"><img src="https://img.shields.io/badge/Built%20with-Flet-0053FD?style=for-the-badge" alt="Built with Flet"></a>
</p>

Hermes Mobile is a serious AI agent for Android phones, built with Python
and [Flet](https://flet.dev). It ports the Hermes Desktop architecture
([Nous Research](https://github.com/NousResearch/hermes-agent)) to mobile
form factors — the same agent loop, tool system, skill infrastructure, and
provider routing, redesigned for a phone screen.

It is not a thin wrapper or a ChatGPT clone. It's an agent with
file operations, terminal access, web search, browser automation, parallel
delegation, skill loading, cron scheduling, encrypted memory, and a
streaming tool-calling loop — all running on Android.

---

## Why Hermes Mobile

- **Chat-completions wire protocol** — the agent speaks OpenAI tool-calling
  natively. Switch providers with a dropdown — no code changes, no lock-in.
- **Runs on your phone** — full APK via `flet build apk`. Python + Flet,
  not a WebView. Works offline with local models (Ollama).
- **Hermes Remote** — connect to a full `hermes serve` backend over
  Tailscale or private network. Same JSON-RPC streaming protocol as
  Hermes Desktop: create sessions, resume conversations, run tools on
  the backend.
- **Transactional settings** — changes stay in draft until you explicitly
  review and save them. Nothing mutates your provider, API keys, or theme
  by accident.
- **41 tool handlers with zero schema divergence** — every tool the model
  can call has a real implementation behind it.
- **Dual-Flet compatibility** — the same codebase builds and runs under
  Flet 0.86.5 (Python 3.12, current APK line) and Flet 0.28.x (Python
  3.9, CI legacy line). No forked views.

---

## Quick Start

### Desktop (for testing)

```bash
git clone git@github.com:plcunha/Hermes-Mobile.git
cd hermes-mobile
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
cp .env.example .env
# Edit .env with at least one provider API key
HERMES_MOBILE_LAYOUT=mobile uv run --python 3.12 python main.py
```

### Android (USB debugging)

```bash
flet run main.py --target=android
```

### Build a release APK

```bash
./scripts/build_android.sh
# APK lands at build/apk/hermes-mobile.apk
```

---

## Providers

7 selectable providers, all runtime-switchable:

| Provider | API Key | API Mode |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | chat_completions |
| OpenAI | `OPENAI_API_KEY` | chat_completions |
| Google AI | `GEMINI_API_KEY` | chat_completions |
| Groq | `GROQ_API_KEY` | chat_completions |
| Together AI | `TOGETHER_API_KEY` | chat_completions |
| DeepSeek | `DEEPSEEK_API_KEY` | chat_completions |
| xAI | `XAI_API_KEY` | chat_completions |

Keys are stored in an encrypted `ProviderSecretStore` (Fernet), never in
the persisted settings JSON.

---

## Architecture

```
main.py                         # Flet entry point
hermes_mobile/
├── main.py                     # HermesMobileApp — shell, nav, lifecycle
├── toolsets.py                 # 28 toolset definitions
├── config/settings.py          # Pydantic settings (.env + JSON persistence)
├── core/
│   ├── agent.py                # MobileAgent — streaming tool-calling loop
│   ├── context_compressor.py   # Token estimation + mid-conversation summarization
│   ├── delegation.py           # Parallel subagent execution
│   └── prompt_caching.py       # Cache breakpoints (Anthropic/OpenRouter)
├── memory/provider.py          # SQLite + Fernet encrypted memory
├── skills/manager.py           # Skill discovery, loading, execution
├── tools/                      # Built-in tool implementations (41 handlers)
├── providers/                  # 7 ProviderProfile configurations
├── cron/                       # Scheduler + default jobs
├── gateway/                    # Pairing, Telegram adapter, platform adapters
├── remote/                     # REST/auth/WebSocket Hermes Remote client
├── plugins/                    # ABC-based plugin registry
├── locales/                    # en.json, pt-br.json i18n
└── ui/                         # 12 Flet views (Chat, Settings, Sessions, etc.)
```

---

## Features

| Area | Capability |
|---|---|
| **Agent Core** | Streaming tool-calling loop with 41 schema-verified handlers |
| **Providers** | 7 providers, runtime-switchable, encrypted key store |
| **Chat** | Markdown rendering, tool call display, composer with model pill |
| **Settings** | 5-tab transactional UI — Provider, Agent, Memory, Appearance, Advanced |
| **Hermes Remote** | JSON-RPC streaming backend client with session resume |
| **Memory** | SQLite with Fernet encryption and TTL-based expiration |
| **Skills** | Python file/package skills, hot-reloadable |
| **Sessions** | Session browser with history, resume, and remote project hierarchy |
| **Workspace** | Local project files or Remote backend project tree |
| **Messaging** | Code-based pairing + Telegram bot adapter |
| **Cron** | JSON-backed scheduler with 4 default jobs |
| **Petdex** | Animated mascot system with Remote pet gallery |
| **Plugins** | ABC registry with Achievements, Kanban, Security |
| **i18n** | English and Portuguese (pt-br), dot-notation key lookup |
| **Prompt Caching** | Anthropic/OpenRouter cache breakpoints (~90% cost savings) |
| **Theming** | Light / Dark / System, Nous color palette |

---

## Hermes Remote

Open **Connections → Hermes Remote**, switch to **Remote**, and point the
client at a running Hermes backend:

1. `GET /api/status` — discover version and auth providers
2. Basic login → one-time WebSocket ticket
3. `/api/ws` — JSON-RPC streaming for session create / list / resume / submit / interrupt

Passwords and tokens live in the app-private encrypted credential store.
HTTPS is required for public hosts; plain HTTP is accepted for loopback,
private LAN, and Tailscale addresses.

**Hermes Remote** and **Messaging Gateway** are separate: Remote makes the
phone a client of a full backend; Messaging Gateway exposes the phone's
local runtime to chat platforms.

---

## Build & Test

```bash
# Run the full suite (current Flet)
.venv/bin/python -m pytest -q

# Run on Python 3.9 / Flet 0.28.x (CI gate)
/tmp/hermes-mobile-py39/bin/python -m pytest -q

# Lint and format
uvx ruff check .
uvx ruff format --check .
```

---

## Skills

Create skills in `~/.hermes_mobile/skills/`:

```python
# my_skill/main.py
async def execute(query: str) -> str:
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

## Contributing

PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development
setup, design principles, the footprint ladder, and the PR process.

Quick gates before submitting:

```bash
uvx ruff check .        # zero errors
uvx ruff format --check .  # clean
.venv/bin/python -m pytest -q  # all green (Python 3.12)
/tmp/hermes-mobile-py39/bin/python -m pytest -q  # all green (Python 3.9)
```

Security issues: see [SECURITY.md](SECURITY.md). Do not open public issues
for vulnerabilities.

---

## License

MIT — see [LICENSE](LICENSE).

Based on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by
[Nous Research](https://nousresearch.com). Built with
[Flet](https://flet.dev).
