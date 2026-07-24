# Hermes Mobile 🤖

A mobile AI agent for Android, built with Python and Flet. Based on the Hermes Desktop architecture.

## Features

- 🤖 **AI Agent Core** - Full tool-calling agent with streaming responses
- 💬 **Chat Interface** - Beautiful mobile-first chat UI with markdown support
- 🔧 **Tool System** - Built-in tools (web search, file ops, shell commands) + extensible skills
- 🧠 **Memory** - SQLite-based conversation memory with encryption
- 📦 **Skills** - Plugin system for extending agent capabilities
- ⏰ **Scheduler** - Background cron jobs for automated tasks
- 🔔 **Notifications** - Push notifications for gateway messages
- 🎨 **Theming** - Light/dark/system theme support
- 🔐 **Security** - Encrypted storage, biometric auth support

## Architecture

```
hermes_mobile/
├── core/           # Agent core, tool execution
├── ui/             # Flet UI components
├── memory/         # SQLite memory provider
├── skills/         # Skill manager and loader
├── cron/           # Background scheduler
├── gateway/        # Messaging gateway (Telegram, etc.)
├── config/         # Configuration management
└── main.py         # Application entry point
```

## Quick Start

### Prerequisites

- Python 3.11+
- Android SDK (for building APK)
- Flet (`pip install flet`)

### Development

```bash
# Clone and setup
cd hermes_mobile
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Run on desktop (for testing)
flet run main.py

# Run on Android device (USB debugging enabled)
flet run main.py --target=android
```

### Building APK

```bash
# Install build dependencies
pip install ".[android]"

# Build APK
flet build apk

# Or with buildozer directly
buildozer -v android debug
```

## Configuration

Key settings in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key | - |
| `DEFAULT_PROVIDER` | AI provider (openrouter, openai, anthropic, gemini) | openrouter |
| `DEFAULT_MODEL` | Default model name | anthropic/claude-3.5-sonnet |
| `MEMORY_ENABLED` | Enable conversation memory | true |
| `ENCRYPT_MEMORY` | Encrypt memory database | true |
| `THEME` | UI theme (light, dark, system) | system |

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

## Project Structure

```
hermes_mobile/
├── main.py                 # App entry point
├── pyproject.toml          # Project config
├── .env.example            # Environment template
├── assets/                 # Icons, splash screen
├── hermes_mobile/
│   ├── config/
│   │   └── settings.py     # Pydantic settings
│   ├── core/
│   │   └── agent.py        # Mobile agent bridge
│   ├── memory/
│   │   └── provider.py     # SQLite memory
│   ├── skills/
│   │   └── manager.py      # Skill management
│   ├── ui/
│   │   ├── chat_view.py    # Chat interface
│   │   ├── settings_view.py
│   │   ├── skills_view.py
│   │   └── memory_view.py
│   └── cron/               # Background scheduler
```

## Hermes Desktop Compatibility

This mobile version shares concepts with Hermes Desktop:

- **Agent Core**: Adapted from `run_agent.py`
- **Tools**: Subset of desktop tools, mobile-optimized
- **Skills**: Compatible skill format
- **Memory**: SQLite instead of PostgreSQL
- **Gateway**: Simplified for mobile push notifications

## License

MIT License - See LICENSE file for details.

## Credits

Based on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.