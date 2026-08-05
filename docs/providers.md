---
layout: default
---

# Providers

Hermes Mobile supports 7 AI providers, all runtime-switchable. API keys are stored in an encrypted credential store — never in the plaintext settings file.

## Recommended: OpenRouter

[OpenRouter](https://openrouter.ai) gives you access to 300+ models through a single API key. It's the easiest way to get started:

1. Get a key at [openrouter.ai/keys](https://openrouter.ai/keys)
2. In Settings → Provider, select **OpenRouter**
3. Paste your key
4. Save changes
5. Choose any model from the dropdown — Claude, GPT-4, Gemini, Llama, etc.

## Available Providers

{% raw %}
| Provider | API Key | Setup |
|---|---|---|
| **OpenRouter** | `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **OpenAI** | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| **Google AI** | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| **Groq** | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |
| **Together AI** | `TOGETHER_API_KEY` | [together.ai](https://together.ai) |
| **DeepSeek** | `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |
| **xAI** | `XAI_API_KEY` | [x.ai](https://x.ai) |
{% endraw %}

## Environment Variables

If running from source (not the APK), set keys in `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
DEFAULT_PROVIDER=openrouter
DEFAULT_MODEL=anthropic/claude-3.5-sonnet
```

On Android, enter keys directly in Settings — they're stored encrypted in the app's private data directory.

## Switching Providers

1. Open Settings → Provider
2. Select a new provider from the dropdown
3. Enter the API key
4. Pick a model (auto-refreshed from the provider's catalog)
5. **Save changes**

The agent reconfigures immediately without restarting.

## Local Models (Ollama)

Ollama support is in the codebase but currently gated — the APK assumes `localhost:11434` which isn't available on stock Android. If you have Ollama on your local network, build from source and set `OLLAMA_HOST=http://<your-ip>:11434` in the environment.
