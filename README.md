<p align="center">
  <img src="assets/hero.png" alt="Hermes Mobile — the Hermes Agent, on your phone" width="100%">
</p>

# Hermes Mobile ☤

<p align="center">
  <strong>The Hermes Agent, on your phone.</strong>
</p>

<p align="center">
  <a href="https://plcunha.github.io/Hermes-Mobile/"><img src="https://img.shields.io/badge/Docs-GitHub%20Pages-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
  <a href="https://github.com/NousResearch/hermes-agent"><img src="https://img.shields.io/badge/Based%20on-Hermes%20Agent-blueviolet?style=for-the-badge" alt="Based on Hermes Agent"></a>
  <a href="https://flet.dev/"><img src="https://img.shields.io/badge/Built%20with-Flet-0053FD?style=for-the-badge" alt="Built with Flet"></a>
</p>

---

## Why this exists

Hermes Agent is the best open-source AI agent. But it only runs on desktop machines
— laptops, VPS, servers. If you want your agent with you on the go, you're stuck
with a WebView wrapper or a Telegram bot that can't access your phone's tools.

Hermes Mobile ports the **entire architecture** to Android as a native APK. Same
streaming tool-calling loop, same encrypted memory, same JSON-RPC Remote protocol.
It's not a thin wrapper — it's the agent.

The core bet:

```
desktop architecture + Flet UI + native APK build = agent in your pocket
```

So you get the same capability whether you're at your desk or on your phone:

```
desktop → hermes
phone  → Hermes Mobile (same agent, smaller screen)
```

---

## What ships

| Area | Capability |
|---|---|
| **Agent Core** | Streaming tool-calling loop with 41 schema-verified handlers |
| **Providers** | 7 runtime-switchable providers with encrypted key store |
| **Chat** | Markdown rendering, tool call display, composer with model pill |
| **Settings** | 5-tab transactional UI — no accidental misconfiguration |
| **Hermes Remote** | JSON-RPC streaming backend client with session resume |
| **Memory** | SQLite with Fernet encryption and TTL-based expiration |
| **Skills** | Python file/package skills, hot-reloadable |
| **Sessions** | Browser with history, resume, and remote project hierarchy |
| **Workspace** | Local project files or Remote backend project tree |
| **Messaging** | Code-based pairing + Telegram bot adapter |
| **Cron** | JSON-backed scheduler with default jobs |
| **Petdex** | Animated mascot system with Remote pet gallery |
| **Plugins** | ABC registry with Achievements, Kanban, Security |
| **i18n** | English and Portuguese (pt-br) |
| **Theming** | Light / Dark / System, Nous color palette |

---

## Quick Start

```bash
git clone git@github.com:plcunha/Hermes-Mobile.git
cd hermes-mobile
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
cp .env.example .env
# Add at least one provider API key to .env

HERMES_MOBILE_LAYOUT=mobile uv run --python 3.12 python main.py
```

Or build the APK:

```bash
./scripts/build_android.sh
# APK lands at build/apk/hermes-mobile.apk
```

📖 **[Full documentation →](https://plcunha.github.io/Hermes-Mobile/)**

---

## Architecture

```
main.py                         # Flet entry point
hermes_mobile/
├── main.py                     # HermesMobileApp — shell, nav, lifecycle
├── config/settings.py          # Pydantic settings (.env + JSON persistence)
├── core/
│   ├── agent.py                # MobileAgent — streaming tool-calling loop
│   ├── context_compressor.py   # Token estimation + summarization
│   ├── delegation.py           # Parallel subagent execution
│   └── prompt_caching.py       # Cache breakpoints (Anthropic/OpenRouter)
├── memory/provider.py          # SQLite + Fernet encrypted memory
├── skills/manager.py           # Skill discovery, loading, execution
├── tools/                      # 41 built-in tool handlers
├── providers/                  # 7 ProviderProfile configurations
├── cron/                       # Scheduler + default jobs
├── gateway/                    # Pairing, Telegram adapter, platform adapters
├── remote/                     # REST/auth/WebSocket Hermes Remote client
├── plugins/                    # ABC-based plugin registry
├── locales/                    # en.json, pt-br.json i18n
└── ui/                         # 12 Flet views
```

---

## Design principles

1. **Mobile-first, Desktop-compatible.** NavigationBar on phones, NavigationRail on desktop. Same code, two shells.
2. **Config is external.** Provider keys, model choices, and preferences live in `.env` or the encrypted credential store — never hardcoded.
3. **Graceful degradation.** Missing API key? The app opens anyway and shows a helpful message instead of crashing.
4. **Security is not optional.** Path traversal protection, AST-based safe evaluation, encrypted memory, and an encrypted provider key store are load-bearing — not checkboxes.
5. **Transactional settings.** Every change stays in draft until you explicitly review and save. Nothing mutates the live agent, theme, locale, or credentials by accident.
6. **Measured, not claimed.** "41 tool handlers" means 41 schemas with zero handler divergence — verified at runtime. "7 providers" means the exact list `list_local_providers()` returns.

---

## Providers

7 runtime-switchable providers. Keys are stored in an encrypted `ProviderSecretStore` (Fernet) — never in the persisted settings JSON.

| Provider | API Key | Setup |
|---|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **OpenAI** | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| **Google AI** | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| **Groq** | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| **Together AI** | `TOGETHER_API_KEY` | [together.ai](https://together.ai) |
| **DeepSeek** | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |
| **xAI** | `XAI_API_KEY` | [x.ai](https://x.ai) |

Anthropic (native Messages API) and Ollama (local models) profiles exist in the
codebase but are currently gated — Anthropic needs a second HTTP client path, and
Ollama's `localhost` assumption doesn't hold on stock Android. Both are on the
roadmap.

---

## Security model

Hermes Mobile inherits the same trust model as Hermes Agent: **the only security
boundary against an adversarial LLM is the operating system.** In-process
heuristics (command approval, path sandbox, output redaction) are accident-
prevention, not containment.

- **API keys** live in an encrypted Fernet store in the app-private sandbox, never in plaintext settings JSON.
- **Hermes Remote** requires HTTPS for public hosts. Plain HTTP is accepted only for loopback, private LAN, and Tailscale addresses.
- **Settings** are transactional — no credential or route change applies without explicit review and confirmation.
- **Gateway** adapters require operator-configured authorization before dispatching agent work.

Read the full policy: [SECURITY.md](SECURITY.md)

---

## Build & Test

```bash
# Full suite (Python 3.12, current Flet)
.venv/bin/python -m pytest -q

# Legacy gate (Python 3.9, Flet 0.28.x)
/tmp/hermes-mobile-py39/bin/python -m pytest -q

# Lint
uvx ruff check .
uvx ruff format --check .
```

CI runs on every push and PR against `main` with a dual Python 3.9 + 3.12 matrix
and read-only permissions.

---

## Contributing

PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup,
the footprint ladder (skill → plugin → core tool), and the PR checklist.

Quick gates before submitting:

```bash
uvx ruff check .              # zero errors
uvx ruff format --check .     # clean
.venv/bin/python -m pytest -q # all green
```

Security issues: [SECURITY.md](SECURITY.md). Do not open public issues for
vulnerabilities.

---

## Status

Hermes Mobile is an active community port. It's not feature-complete against
Hermes Desktop (~80% tool parity, missing native Anthropic and some desktop-only
tools), but what ships works: 803 tests, cold start under 1 second, zero fatal
logcat entries on Android. It's ready for daily use.

Things that ship next: Ollama un-gating, more providers (Perplexity, Mistral,
Fireworks), and an Anthropic Messages API client path.

---

## License

MIT — see [LICENSE](LICENSE).

Based on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by
[Nous Research](https://nousresearch.com). Built with [Flet](https://flet.dev).

**Community port. Not affiliated with or endorsed by Nous Research.**
