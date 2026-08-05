---
layout: default
---

# Getting Started

## Install

**Option 1: Download the APK (easiest)**

Grab the latest APK from [GitHub Releases](https://github.com/plcunha/Hermes-Mobile/releases) and sideload it:

```bash
adb install Hermes-Mobile.apk
```

Or transfer the `.apk` to your phone and open it — Android will prompt you to install.

**Option 2: Run from source (desktop testing)**

```bash
git clone git@github.com:plcunha/Hermes-Mobile.git
cd hermes-mobile
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` with at least one provider API key, then:

```bash
HERMES_MOBILE_LAYOUT=mobile uv run --python 3.12 python main.py
```

**Option 3: Build the APK yourself**

See [Building from Source](building).

---

## First Run

1. Open the app. You'll see the Chat screen with a welcome message.
2. Tap **More (⋯) → Settings**.
3. Under the **Provider** tab, select your provider (OpenRouter is recommended).
4. Paste your API key in the API Key field.
5. Review your changes and tap **Save changes** to confirm.
6. Return to Chat and start a conversation.

The agent will use tools automatically — mention a file, a URL, a command, or a search, and it'll pick the right tool.

---

## Navigation

| Screen | How to reach | What it does |
|---|---|---|
| Chat | Bottom bar, tab 1 | Main conversation interface |
| Skills | Bottom bar, tab 2 | Browse and manage skills |
| Messaging | Bottom bar, tab 3 | Pair with Telegram or other platforms |
| Workspace | Bottom bar, tab 4 | Browse projects and files |
| Tools | More (⋯) | Browse available tool schemas |
| Memory | More (⋯) | View stored conversations and memories |
| Cron | More (⋯) | Manage scheduled jobs |
| Plugins | More (⋯) | Load and configure plugins |
| Terminal | More (⋯) | Raw shell access |
| Kanban | More (⋯) | Task board |
| Settings | More (⋯) | Configure providers, models, appearance |

---

## Changing Models

Open **Settings → Provider**. Change the **Default Model** dropdown. The model list refreshes from the provider's API when you tap **Refresh models**.

Switching providers:
1. Change the **Default Provider** dropdown
2. The model list reloads automatically
3. Enter the API key for the new provider
4. **Save changes**

No restart needed — the agent reconfigures on save.

---

## Setting up Telegram

1. Open **More (⋯) → Messaging**
2. Enable the gateway and follow the pairing flow
3. Send a message to your bot — the agent responds with the same tool-calling capabilities

Your phone's Hermes Mobile runtime becomes accessible from Telegram.
