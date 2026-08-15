# Hermes Mobile — Architecture & Request Flow

This document explains how Hermes Mobile is put together and what happens end-to-end when a request flows through the app. It is kept in sync with the code: the flows below (local chat, tool dispatch, gateway/messaging, remote backend, settings/secrets) are the paths that the currently maintained files live on.

- [High-level picture](#high-level-picture)
- [Module map](#module-map)
- [Runtime modes](#runtime-modes)
- [Request flows](#request-flows)
  - [1. Local chat turn (the core loop)](#1-local-chat-turn-the-core-loop)
  - [2. Tool dispatch & execution](#2-tool-dispatch--execution)
  - [3. Remote (Hermes Desktop backend) turn](#3-remote-hermes-desktop-backend-turn)
  - [4. Gateway / messaging (Telegram) flow](#4-gateway--messaging-telegram-flow)
  - [5. Settings & secrets](#5-settings--secrets)
  - [6. Background: cron & memory cleanup](#6-background-cron--memory-cleanup)
- [Storage & data layout](#storage--data-layout)
- [Security model](#security-model)
- [Concurrency & lifecycle notes](#concurrency--lifecycle-notes)
- [Files touched by recent work](#files-touched-by-recent-work)

---

## High-level picture

Hermes Mobile is a **Python + Flet** mobile AI agent (Android APK, also runs on desktop/web for testing). It embeds an OpenAI-compatible streaming tool-calling agent loop on-device, plus a messaging gateway (Telegram) that lets remote users chat with the same agent.

```
┌────────────────────────────────────────────────────────────────┐
│                        Flet UI (main.py)                        │
│  HermesMobileApp — page setup, nav shell, lifecycle             │
│                                                                │
│  Mobile shell:  AppBar + content_area + NavigationBar + Pet    │
│  Desktop shell: NavigationRail + content_area                  │
│  13 views (chat, sessions, skills, messaging, artifacts,       │
│  tools, memory, cron, gateway, plugins, terminal, kanban,      │
│  settings) — _switch_view builds only the active view          │
├────────────────────────────────────────────────────────────────┤
│  Agent core        core/agent.py  MobileAgent                  │
│  └─ run_conversation(): streaming tool-calling loop            │
│       ├─ tools → hermes_mobile/tools/*  (built-in)             │
│       ├─ skills → skills/manager.py     (hot-reloadable)       │
│       └─ providers → providers/__init__.py (9 profiles)        │
│                     openai client → chat.completions           │
├────────────────────────────────────────────────────────────────┤
│  Memory           memory/provider.py — SQLite + Fernet         │
│                   conversations / memory_entries /             │
│                   skill_memory / kv_memory                     │
│  Cron             cron/scheduler.py — JSON jobs + ticker       │
│  Plugins          plugins/__init__.py — registry               │
│  Gateway          gateway/mobile_gateway.py + telegram_adapter │
│  Remote           remote/client.py — WebSocket JSON-RPC client │
│  Settings         config/settings.py — pydantic + settings.json│
│  Secrets          remote/secrets.py — Fernet encrypted stores  │
└────────────────────────────────────────────────────────────────┘
```

There are **two chat runtimes** behind the same composer:

| | Local (default) | Remote (`runtime_mode=remote`) |
|---|---|---|
| Who runs the agent loop | `MobileAgent` in-process | a Hermes Desktop backend (`hermes serve`) |
| Transport | none (in-process) | WebSocket JSON-RPC (`remote/client.py`) |
| Streaming | async generator deltas | pushed events (`message.delta`, `tool.start`, …) |
| Tools | local built-in + skills | executed on the backend |

The **gateway** is a third entry path: instead of a UI composer, a platform adapter (Telegram) receives messages and drives the same local `MobileAgent` loop, streaming replies back by editing a chat message.

---

## Module map

```
main.py                             # ft.app entry → HermesMobileApp
hermes_mobile/
├── main.py                         # app shell, lifecycle, send_message, nav, remote event bridge
├── toolsets.py                     # 28 toolset taxonomies (UI browsing, mirrors desktop)
├── config/settings.py              # HermesMobileSettings (env → settings.json), atomic save
├── core/
│   ├── agent.py                    # MobileAgent: run_conversation, tool registry, 40+ handlers
│   ├── context_compressor.py       # token estimation + mid-conversation compression
│   ├── delegation.py               # subagent helpers (currently unused by the app)
│   └── prompt_caching.py           # cache_control breakpoints for Anthropic/OpenRouter
├── memory/provider.py              # SQLite + Fernet: conversations, memory, kv store
├── skills/manager.py               # skill discovery/loading/execution (file + YAML schema)
├── tools/
│   ├── agent_tools.py              # session_search, memory (kv), clarify
│   ├── browser_session.py          # shared BrowserSession (navigate/back/click/images)
│   ├── desktop_tools.py            # file ops, patch, search_files, execute_code
│   ├── kanban_tools.py             # kanban board CRUD (JSON-backed)
│   ├── media_tools.py              # vision_analyze, image_generate
│   ├── path_security.py            # validate_and_resolve_path (sandbox + traversal guard)
│   ├── process_tools.py            # terminal/process session registry (stderr, eviction)
│   ├── project_tools.py            # project list/create/switch (sets agent._workspace)
│   ├── security.py                 # AST-based safe math evaluator (no eval)
│   └── web_tools.py                # DDG search, web_extract, browser_* tools
├── providers/__init__.py           # ProviderProfile + 9 profiles (openrouter…ollama)
├── cron/                           # scheduler + 4 default jobs + scripts
├── gateway/
│   ├── mobile_gateway.py           # PairingManager, GatewayManager, StreamConsumer, BasePlatformAdapter
│   └── telegram_adapter.py         # Telegram long-polling adapter
├── plugins/__init__.py             # PluginRegistry, BasePlugin + built-ins
├── remote/
│   ├── client.py                   # RemoteHermesClient (WebSocket JSON-RPC)
│   └── secrets.py                  # ProviderSecretStore, RemoteSecretStore, GatewaySecretStore
├── locales/                        # en.json / pt-br.json + t() loader (dot-notation)
└── ui/                             # 13 views + common.py (snack/dialog helpers), theme.py,
                                    # composer_state.py, pet_view.py
```

---

## Runtime modes

- **Local** — everything runs in the APK process: agent, tools, skills, memory, gateway, cron.
- **Remote** — chat delegates to a Hermes Desktop backend over WebSocket. The UI projects backend events onto the transcript (see [flow 3](#3-remote-hermes-desktop-backend-turn)). Local services (memory, cron, gateway) keep working.

Mode is selected in Settings/Connections (`runtime_mode`), and remote connection details (`remote_url`, auth, profile) are configured there too.

---

## Request flows

### 1. Local chat turn (the core loop)

```
user taps Send
   │
   ▼
main.py: send_message(text)
   ├─ slash command? → _handle_slash_command (/model, /new, /stop, …) and return
   ├─ busy?          → _enqueue_message (persisted FIFO via ComposerStateStore)
   ├─ chat_view.set_busy(True); add user bubble
   │
   ▼
agent.run_conversation(text, stream=True)        # async generator
   │
   │  loop (max_iterations, default 20):
   │    add_user_message(text)
   │    api_messages = get_messages_for_api()    # prompt caching applied
   │    needs_compression? → _apply_compression()
   │    response = _call_model(stream=True)      # openai client, chat.completions
   │    for chunk in response:                   # streaming deltas
   │        yield content delta        ───────────────► chat_view.append_assistant_message(chunk)
   │        accumulate tool_call deltas          # index-keyed reconstruction
   │    add_assistant_message(content, tool_calls)
   │    if tool_calls: _execute_tool_calls() → continue loop (tool results are next messages)
   │    else: break
   │
   ▼
   memory_provider.save_conversation(session_id, messages)   # persist on every turn
   │
   ▼
main.py: finalize_assistant_message(); set_busy(False)
   ├─ pet flash ("wave")
   └─ drain persisted queue → send_message(next, from_queue=True)
```

Key invariants of the loop (do not break — `AGENTS.md` calls this "the heart"):

- Past messages are never mutated; the assistant message containing tool calls is added **before** the tool-result messages so the API history stays valid.
- Role alternation user → assistant → tool → assistant is preserved.
- Prompt caching (cache breakpoints) is only invalidated via `context_compressor`, never by hand.
- The turn is an async generator so the UI streams token-by-token; interruption works by cancelling the task (`interrupt_turn` → `_active_local_turn.cancel()`).

### 2. Tool dispatch & execution

```
_execute_tool(name, arguments)
   ├─ name in agent._builtin_tools  → handler(**arguments)
   └─ skill_manager.get_skill(name) → skill.execute(**arguments)
        (else raise ValueError → surfaced as tool error message)
```

- `_builtin_tools` is a property mapping tool name → bound handler (`web_search`, `read_file`, `terminal`, `memory`, `browser_*`, `vision_analyze`, `image_generate`, `kanban_*`, `delegate_*`, …). Handlers named `_tool_<name>` live in `core/agent.py` and delegate to the tool modules.
- **Schemas**: `get_tool_schemas()` builds the JSON-schema payload sent to the model. There is a test invariant that the advertised schema set equals the handler set — every tool the model can call has a working implementation (and `run_command`, the legacy duplicate of `terminal`, is deliberately not advertised).
- **Workspace sandbox**: file tools (`read_file`, `write_file`, `list_files`, `search_files`, `patch`) resolve paths through `path_security.validate_and_resolve_path` with `extra_dirs`/`base_dir` derived from `agent._workspace` (`_file_scope()`). Switching a project (`project_switch`) re-points relative paths; anything outside the workspace is rejected.
- **Browser**: all `browser_*` tools share one `BrowserSession` singleton (`tools/browser_session.py`) — navigate/back/click/images operate on the same tab and history, and every fetch goes through the SSRF guard (`_safe_get`: blocks private/loopback/metadata-cloud IPs, validates each redirect hop).
- **Media**: `vision_analyze` (local path or URL, 5 MiB cap, sandboxed path resolution, per-provider vision model map) and `image_generate` (key + base URL + model all from the **active** provider; PNG written to `<data_dir>/generated/`, path returned).

### 3. Remote (Hermes Desktop backend) turn

```
send_message (remote_mode)
   ├─ ensure connected: connect_remote() → RemoteHermesClient (WebSocket JSON-RPC)
   ├─ client.submit_prompt(text)
   │     ├─ resume stored session if no live session
   │     └─ session.create if none
   ▼
backend streams events over the socket → main.py _on_remote_event
   ├─ message.delta / message.interim → append_assistant_message (append-only)
   ├─ message.complete               → finalize bubble, unlock composer, drain queue
   ├─ tool.start / tool.complete     → chat_view.on_tool_call / on_tool_result
   ├─ clarify/approval/secret/sudo.request → chat_view.show_remote_request
   ├─ session.info / pet.changed     → app bar subtitle, pet refresh
   └─ error / background.complete    → transcript note, status
```

Remote sessions can be listed/resumed/forked/branched/renamed/deleted via `remote/client.py` (JSON-RPC methods + authenticated REST endpoints). The `sessions` view is the browser; the `artifacts`/`skills` views also proxy backend data when in remote mode.

### 4. Gateway / messaging (Telegram) flow

```
Telegram user sends message
   │
   ▼
telegram_adapter.py (long-polling getUpdates) → on_message callback
   │
   ▼
gateway/mobile_gateway.py: GatewayManager.handle_message(platform, chat_id, user_id, text)
   ├─ pairing_manager.is_user_authorized(platform, user_id)?
   │     NO  → request_pairing() → send 8-char code message (1h TTL,
   │            rate-limited, 5 failures → 1h lockout); user approves in-app
   │            (Messaging view) or via CLI → allowlist JSON updated → return
   │     YES ────────────────────────────────────────────────────────────────┐
   ▼                                                                          │
   GatewayStreamConsumer(adapter, chat_id, config)                            │
   async for chunk in agent.run_conversation(text, stream=True):              │
       consumer.on_delta(chunk)        # buffer deltas                        │
   consumer.finish(); await consumer.run()                                    │
       └─ adapter.edit_message(...)    # progressively edited reply           │
                                                                              │
   # adapter lifecycle: GatewayManager.start() → _start_platform("telegram")  │
   #   token = TELEGRAM_BOT_TOKEN env  →  GatewaySecretStore.get_token()      │
   #   (no token → warning + skip)                                            │
   # GatewayConfig comes from settings: enabled, port, platforms=            │
   #   settings.gateway_platforms (default ["telegram"])                      │
```

Notes:

- The gateway runs **inside the app process**; the app must stay alive. Telegram long-polling is outbound only — no inbound port needed.
- `GatewayStreamConsumer` batches deltas and edits the Telegram message in place (delta/tool/commentary callbacks); a background `_cleanup_loop` prunes expired pairing codes every 5 minutes.
- Adding a new platform = subclass `BasePlatformAdapter` (send/edit/delete/handle) and register it in `_start_platform`.

### 5. Settings & secrets

```
startup: HermesMobileSettings()
   ├─ env vars first (pydantic-settings, .env file)
   └─ load_persisted() overlays <data_dir>/config/settings.json
        (only _PERSISTED_FIELDS; legacy provider-key migration moves
         old keys into ProviderSecretStore)
   ├─ get_settings() / save_settings()   (atomic tmpfile + os.replace, 0o600)
   └─ Settings view edits a draft; Save commits → save_settings + reinit

secrets (never in settings.json):
   ├─ ProviderSecretStore  → per-provider API keys (Fernet, namespace providers/)
   ├─ RemoteSecretStore    → remote token/password (namespace remote/)
   └─ GatewaySecretStore   → Telegram bot token entered in the Messaging view
                              (namespace gateway/) — the APK has no .env, so
                              this is how the token gets on-device
```

The agent reads its key via `_get_api_key()` from the active provider's secret store; `_init_client()` builds the OpenAI-compatible client from `base_url` + key of the **selected** provider profile (non-`chat_completions` providers are excluded from the UI and rejected with a clear message).

### 6. Background: cron & memory cleanup

```
startup: ensure_default_jobs() (4 jobs) + start_ticker()
   └─ ticker thread (60s) → run due jobs → jobs.json (advisory fcntl lock)
      + run history JSONL in cron/output/
gateway _cleanup_loop → pairing codes expiry (every 5 min)
memory cleanup → cleanup_expired() TTL pruning (also a cron job)
```

---

## Storage & data layout

Root: `settings.get_data_dir()` — on Android `FLET_APP_STORAGE_DATA` (`/data/data/<pkg>/files/data`); elsewhere `~/.hermes_mobile` or cwd fallback.

| Path | Content |
|---|---|
| `data/memory.db` | SQLite: `conversations`, `memory_entries`, `skill_memory`, `kv_memory` (all Fernet-encrypted when `encrypt_memory=true`) |
| `data/config/settings.json` | persisted settings (atomic write) |
| `data/secrets/*` | Fernet-encrypted secret stores (providers / remote / gateway) |
| `data/skills/` | user skills (package + `skill.yaml`) |
| `data/projects/` | workspace projects (`project_switch` re-points file-tool scope) |
| `data/generated/` | `image_generate` PNG output |
| `data/cron/jobs.json`, `data/cron/output/*.jsonl` | cron jobs + run history |
| `data/gateway/` | pairing codes + platform allowlists (JSON) |

---

## Security model

- **File sandbox** — `validate_and_resolve_path` rejects `..` traversal and symlink escapes; only the workspace root (+ `extra_dirs`) and platform-documents roots are writable. Vision reads go through the same resolver.
- **SSRF guard** — browser/web fetches block private/loopback/metadata-cloud destinations, validated on every redirect hop (max 3).
- **Safe eval** — `calculate` uses an AST walker, never `eval()`.
- **Encryption** — memory DB values and secret stores are Fernet-encrypted (PBKDF2-derived key, device/user-provided).
- **Gateway pairing** — 8-char codes, 1h TTL, rate limit (1 per 10 min per user), 3 pending max per platform, 5 failures → 1h lockout.
- **Credentials** — API keys never live in settings.json; they are stored encrypted and read server-side only (env or secret store).

---

## Concurrency & lifecycle notes

- All agent/UI work is asyncio on one event loop; blocking work (cron run-now, process polling, ticker) is pushed to worker threads and results marshalled back onto the loop (`asyncio.to_thread`, `threading.Event`).
- `_active_local_turn` tracks the in-flight turn so Stop can cancel it; the composer locks while busy and queues follow-ups (persisted, so they survive restarts).
- Terminal view polls its background session every 150 ms, batches output into one frame push, and skips pushes when the view is not active; Stop kills the process tree.
- Pet animation pushes one frame update per frame (remote mode only).
- SnackBars are bounded to one on `page.overlay` (Flet never auto-removes them) to avoid control-tree creep.

---

## Files touched by recent work

The flows above correspond to the files that have been under active maintenance:

| Area | Files | What changed |
|---|---|---|
| Gateway wiring | `main.py`, `config/settings.py`, `gateway/mobile_gateway.py`, `remote/secrets.py`, `remote/__init__.py`, `ui/gateway_view.py` | `gateway_platforms` setting; `GatewaySecretStore` + in-app Telegram token field; `_start_platform` env→store fallback |
| Tool correctness | `core/agent.py`, `tools/browser_session.py`, `tools/web_tools.py`, `tools/process_tools.py`, `tools/desktop_tools.py`, `tools/media_tools.py`, `tools/agent_tools.py`, `tools/kanban_tools.py`, `tools/path_security.py`, `ui/terminal_view.py` | unified browser session + SSRF guard; honest terminal streaming/cancel/stderr; `execute_code` via `sys.executable`; `run_command` de-advertised; workspace-scoped file tools; working `memory` kv actions; vision sandbox + per-provider model; consistent `image_generate` |
| UI/UX hardening | `ui/common.py`, `ui/chat_view.py`, `ui/pet_view.py`, `ui/terminal_view.py`, `ui/gateway_view.py`, `locales/*` | bounded snackbars, full i18n sweep (en + pt-br parity), token draft preservation, hidden-view polling guard, single frame push per pet frame, Clear actually updates |

The tests that pin these flows: `tests/test_process_tools.py`, `tests/test_web_tools.py`, `tests/test_browser_session.py`, `tests/test_terminal_view.py`, `tests/test_memory_kv.py`, `tests/test_path_scope.py`, `tests/test_workspace_tools.py`, `tests/test_media_tools.py`, `tests/test_delegation.py`, `tests/test_gateway_secrets.py`, `tests/test_common.py`, `tests/test_views_smoke.py`.
