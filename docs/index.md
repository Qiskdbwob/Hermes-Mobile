---
layout: default
---

# Hermes Mobile ☤

A mobile AI agent for Android. Port of [Hermes Agent](https://github.com/NousResearch/hermes-agent) by [Nous Research](https://nousresearch.com).

<img src="https://raw.githubusercontent.com/plcunha/Hermes-Mobile/main/assets/hero.png" alt="Hermes Mobile" width="100%">

---

## What is this?

Hermes Mobile puts a full AI agent on your phone. It's not a ChatGPT wrapper — it's the same streaming tool-calling loop from Hermes Desktop, running as a native Android APK. It can search the web, run terminal commands, read and write files, delegate tasks to subagents, load skills, execute cron jobs, and connect to a remote Hermes backend over JSON-RPC.

**Community port. Not affiliated with or endorsed by Nous Research.**

---

## Quick Start

1. [Install](getting-started) the APK or build from source
2. [Configure a provider](providers) — OpenRouter is the easiest (one key, 300+ models)
3. Start chatting. Tools activate automatically when needed.

---

## Pages

- [Getting Started](getting-started) — install, setup, first conversation
- [Providers](providers) — API keys, switching models
- [Hermes Remote](hermes-remote) — connect to a `hermes serve` backend
- [Building from Source](building) — compile your own APK
- [Screenshots](screenshots) — real APK screenshots, no mockups

---

## Highlights

- **41 tool handlers** with zero schema divergence — every tool the model can call has a real implementation
- **7 runtime-switchable providers** with encrypted credential store
- **Transactional Settings** — changes stay in draft until you explicitly save. No accidental misconfiguration.
- **Hermes Remote** — same JSON-RPC protocol as Hermes Desktop: create sessions, resume conversations, run tools on the backend
- **Offline support** — works with Ollama for local models
- **803 tests** on Python 3.12 and Python 3.9

[View on GitHub →](https://github.com/plcunha/Hermes-Mobile)
