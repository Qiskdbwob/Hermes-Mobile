# Hermes Mobile

A mobile AI agent for Android, built with Python and Flet. Ports the Hermes Desktop architecture (Nous Research) to mobile form factors.

## Features

- **AI Agent Core** - Full tool-calling agent with streaming responses (14 built-in tools)
- **Chat Interface** - Material 3 mobile-first UI with markdown, tool call display, and streaming
- **9 AI Providers** - OpenRouter, OpenAI, Anthropic, Google/Gemini, Groq, Together, DeepSeek, xAI, Ollama
- **Memory** - SQLite-based conversation memory with Fernet encryption and TTL expiration
- **Skills** - Plugin system for extending capabilities (Python file or package skills)
- **28 Toolsets** - Categorized tool groupings mirroring Hermes Desktop
- **Gateway** - Code-based pairing + Telegram bot adapter for remote access
- **Scheduler** - Cron job system for automated tasks (cleanup, backup, sync, updates)
- **i18n** - English and Portuguese (pt-br) with dot-notation translation
- **Prompt Caching** - Cost savings via cache breakpoints (~90% on system prompt)
- **Theming** - Light/dark/system theme, adjustable font size
- **Security** - Encrypted memory, path traversal protection, AST-based safe evaluation

## Quick Start

```bash
# Setup
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with OPENROUTER_API_KEY or OPENAI_API_KEY

# Desktop testing
flet run main.py

# Android device (USB debugging)
flet run main.py --target=android
```

## Architecture

```
main.py                         # Flet entry point (ft.app)
hermes_mobile/
├── main.py                     # HermesMobileApp - orchestrator + lifecycle
├── toolsets.py                 # 28 toolset definitions
├── config/settings.py          # Pydantic settings from .env
├── core/
│   ├── agent.py                # MobileAgent - streaming tool-calling loop
│   ├── context_compressor.py   # Token estimation + summarization
│   ├── delegation.py           # Parallel subagent execution
│   └── prompt_caching.py       # Cache breakpoints (Anthropic/OpenRouter)
├── memory/provider.py          # SQLite + Fernet encrypted memory
├── skills/manager.py           # Skill discovery, loading, execution
├── tools/                      # Built-in tool implementations
├── providers/                  # 9 ProviderProfile configurations
├── cron/                       # Scheduler + 4 default jobs
├── gateway/                    # Pairing, Telegram adapter, platform adapters
├── plugins/                    # ABC-based plugin registry
├── locales/                    # en.json, pt-br.json i18n
└── ui/                         # 8 Flet views
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | - | Primary AI provider key |
| `DEFAULT_PROVIDER` | openrouter | AI provider |
| `DEFAULT_MODEL` | anthropic/claude-3.5-sonnet | Model name |
| `ENCRYPT_MEMORY` | true | Encrypt SQLite database |
| `THEME` | system | light, dark, system |
| `LANGUAGE` | en | en or pt-br |

## Building APK

```bash
pip install ".[android]"
flet build apk
# or
buildozer -v android debug
```

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

## License

MIT - Based on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research. Built with [Flet](https://flet.dev/).
