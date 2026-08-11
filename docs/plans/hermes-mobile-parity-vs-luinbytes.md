# Hermes Mobile Parity Plan vs luinbytes/hermes-android

**Goal:** close the practical Desktop/mobile parity gap using luinbytes/hermes-android as a benchmark, while preserving Hermes Mobile's Python/Flet local-agent strengths.

**Benchmark evidence:** luinbytes/hermes-android is native Kotlin/Compose, ~44k LOC, 213 Kotlin files, 105 test files, release APK/AAB/provenance pipeline, and implements deep Hermes Remote management surfaces. Hermes Mobile is Python/Flet with local runtime/tools/skills plus Remote client; it is faster to iterate but heavier and less Android-native.

## Classification

### P0 / daily-use correctness
1. **Composer durability:** drafts, queue, and composer history must survive process restart and reconnect; busy send should queue text, not silently stop the turn.
2. **Remote session lifecycle:** reconnect must rehydrate authoritative session state, prevent duplicate/new sessions, and surface failures without transcript loss.
3. **Slash command parity:** catalogue/autocomplete should eventually come from Hermes backend where available; local curated fallback remains.
4. **Model/provider switching:** model picker and `/model` must alter the active runtime path and visible chrome.

### P1 / mobile-native capability
5. **Attachments:** SAF file/image/PDF picker, bounded local read, MIME/path validation, Remote attach when backend advertises it.
6. **Voice:** press-to-talk transcription through Hermes `/api/audio/transcribe`, plus reply read-aloud via `/api/audio/speak`.
7. **Workspace/files:** managed Remote workspace browser with text/image/PDF preview and safe export/share.
8. **Usage/providers/MCP/toolsets:** server-owned management surfaces, capability-gated, no fake controls.
9. **Markdown/message actions:** GFM/code blocks, copy/share, stable tool rows, reasoning/status disclosure.

### P2 / polish/release maturity
10. **Secure screen/biometric re-entry:** platform privacy gates if Flet can expose Android flags or via native plugin.
11. **Widget/share target:** New Chat Android widget and share target; likely requires native Android wrapper work.
12. **APK size:** payload audit and exclusion, consider long-term Kotlin/Compose rewrite for 8 MB-class APK.
13. **CI/release provenance:** checksum, artifact contract, SBOM/provenance evidence.

## Execution sequence

### Phase 1 — Composer durability (start now)
- Add `ComposerStateStore` under `hermes_mobile/ui/composer_state.py`.
- Store JSON in `settings.get_config_dir()/composer-state.json` with 0600 permissions.
- Key by runtime/backend/profile/stored-session/local-session.
- Persist draft on text change.
- While busy: text + send queues; empty + send stops.
- Drain queue FIFO only after current turn completes.
- Tests: queue/draft persistence and busy-send behavior.

### Phase 2 — Remote rehydration hardening
- On reconnect/resume, load queue/draft by durable stored session id.
- Surface reconnect state in composer status.
- Add regression around reconnect + queued submit.

### Phase 3 — Message/action polish
- Improve copy/share behavior without layout jumps.
- Tool rows expand/collapse with stable identity.
- Final markdown renderer audit.

### Phase 4 — Attachments and workspace
- Capability-detect Remote attachment/file endpoints.
- Add file picker and bounded reader.
- Add preview/export surface.

### Phase 5 — Voice/TTS
- Probe Flet/platform recording support.
- If insufficient, implement native bridge or postpone to Kotlin/Compose track.

### Phase 6 — Management surfaces
- Usage, provider accounts, MCP, toolsets, billing only when backend advertises safe contracts.

## Acceptance gates
- Affected focused tests first, then full suite on Python 3.12/Flet current and Python 3.9/Flet legacy.
- Ruff check and format check.
- Android APK build on Mac only.
- APK copied to `~/Downloads/Hermes-Mobile.apk` and uploaded to GitHub Release.
- No backend Hermes source modifications unless explicitly authorized separately.

## Execution log

### 2026-08-11 — Phase 1 completed

- Added `ComposerStateStore` with atomic `composer-state.json` persistence.
- Drafts persist by runtime/backend/profile/session key.
- Pending-message queue persists and drains FIFO after Local/Remote completion.
- Busy composer semantics corrected: non-empty text queues; empty composer stops.
- Added `/queue` and `/queue clear` for visible queue inspection/control.

### 2026-08-11 — Phase 2 partial completed

- Added safe lightweight chat attachments.
- Text/code/markdown/json/csv-style files are inlined with strict size limits.
- Images and binaries are copied to app-private storage and referenced by local path for agent tools such as `vision_analyze`.
- Dangerous executable/package extensions are rejected.
- The chat model pill now opens the quick model picker instead of navigating away.

### Remaining hard boundaries

These are intentionally not faked in Hermes Mobile Flet:

- **Voice/STT/TTS:** requires Android recording/playback lifecycle and Hermes `/api/audio/*` contracts exposed in the selected backend. The current mic remains disabled rather than pretending voice works.
- **MCP/Usage/Billing provider-account surfaces:** require capability-gated REST/RPC clients and server-owned contracts. Implement only after probing live backend support; do not invent values or local-only controls.
- **Secure screen, biometrics, widget, share target:** require native Android integration or a Flet/native plugin layer. They are not ordinary Python/Flet UI work.
- **APK size parity:** Flet/Python packaging will remain much larger than Kotlin/Compose. Reducing from ~226 MB requires payload audit and/or a native rewrite track.
