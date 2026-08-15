# Skema Memory & Harness — Hermes Mobile

> Dokumen ini berisi (1) skema memory + harness **yang sedang dipakai sekarang** di Hermes Mobile,
> (2) prompt siap-tempel untuk Claude agar ia bisa menganalisis dan merancang skema yang lebih baik,
> dan (3) tabel perbandingan dengan **hermes-agent by Nous Research**.

Semua tabel SQL dan detail di bawah diambil langsung dari kode (bukan perkiraan).

---

## 1. Skema Memory Saat Ini (Hermes Mobile)

Backend: **SQLite** (satu file `~/.hermes_mobile/memory.db`), semua kolom nilai teks dienkripsi
**Fernet** (key diturunkan dari PBKDF2 — device-specific atau user-provided). Tidak ada embedding:
pencarian relevansi memakai **keyword scoring sederhana**; pencarian sesi memakai `LIKE` (plaintext)
atau filter Python (saat terenkripsi).

### 1.1 Tabel `conversations` — riwayat pesan per sesi

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id           TEXT PRIMARY KEY,     -- uuid
    session_id   TEXT NOT NULL,        -- grouping percakapan
    role         TEXT NOT NULL,        -- system | user | assistant | tool
    content      TEXT NOT NULL,        -- isi pesan (terenkripsi)
    tool_calls   TEXT,                 -- JSON tool calls (bila role=assistant)
    tool_call_id TEXT,                 -- id tool result (bila role=tool)
    name         TEXT,                 -- nama tool / optional
    timestamp    TEXT NOT NULL,        -- ISO8601
    message_id   TEXT NOT NULL
);
CREATE INDEX idx_conversations_session   ON conversations(session_id);
CREATE INDEX idx_conversations_timestamp ON conversations(timestamp);
```

- Ditulis oleh `save_conversation()` di akhir tiap turn agent.
- Dibaca kembali oleh `get_conversation(session_id, limit=100)` saat sesi dilanjutkan.
- **Tanpa FTS5**, tanpa ringkasan LLM — pencarian lintas sesi (`search_sessions`) memakai
  `LOWER(content) LIKE '%kw%'` per kata kunci, atau filter Python bila data terenkripsi.

### 1.2 Tabel `memory_entries` — memori jangka panjang

```sql
CREATE TABLE IF NOT EXISTS memory_entries (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    content    TEXT NOT NULL,          -- fakta yang ingin diingat (terenkripsi)
    embedding  TEXT,                   -- KOLOM CADANGAN: selalu NULL (tidak ada embedding)
    metadata   TEXT,                   -- JSON opsional
    created_at TEXT NOT NULL,
    expires_at TEXT                    -- TTL (NULL = permanen)
);
CREATE INDEX idx_memory_session ON memory_entries(session_id);
CREATE INDEX idx_memory_created ON memory_entries(created_at);
```

- Ditulis via `add_memory_entry()`; dibaca via `get_relevant_context(query, limit=5)` yang
  **men-split query jadi kata kunci** lalu mencocokkan secara sederhana.
- `cleanup_expired()` menghapus baris `expires_at < now` (jalan via cron harian).

### 1.3 Tabel `skill_memory` — memori milik skill

```sql
CREATE TABLE IF NOT EXISTS skill_memory (
    id         TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE INDEX idx_skill_memory_skill ON skill_memory(skill_name);
```

- API: `set_skill_memory(skill, key, value, ttl)` / `get_skill_memory(skill, key)` —
  `INSERT OR REPLACE`, scoped per skill.

### 1.4 Tabel `kv_memory` — memori key/value untuk tool agent

```sql
CREATE TABLE IF NOT EXISTS kv_memory (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT
);
```

- API: `store_memory(key, value, ttl_days)` / `get_memory(key)` / `delete_memory(key)` /
  `list_memory()` / `search_memory(query, limit=10)`.
- Inilah backend dari tool agent `memory_tool` (lihat §2.3).

### 1.5 Permukaan tool memory (yang dilihat model)

| Tool | Aksi | Keterangan |
|---|---|---|
| `memory_tool` | `store` / `retrieve` / `search` / `list` / `delete` | KV key→value + pencarian `memory_entries` |
| `session_search_tool` | `search` | Cari pesan lama via LIKE (SQLite) / filter Python (terenkripsi) |
| `clarify_tool` | — | Minta klarifikasi ke user (bukan memory, tapi bagian harness interaktif) |

---

## 2. Harness Saat Ini (Hermes Mobile)

### 2.1 Loop agent (`core/agent.py` — `run_conversation`)

```
1. Tambah pesan user ke riwayat (conversation history)
2. Format pesan dengan caching (provider yang mendukung → cache breakpoint)
3. Cek ambang kompresi (needs_compression) → compress_messages bila melebihi max_context_tokens
4. Panggil model API (streaming atau non-streaming)
5. Ekstrak tool calls dari respons
6. Eksekusi tiap tool (built-in → skills)
7. Tambahkan hasil tool sebagai pesan (role=tool)
8. Ulangi dari langkah 2 sampai tidak ada tool call atau max_iterations tercapai
9. Persist percakapan ke memory provider
```

### 2.2 Kompresi konteks (`core/context_compressor.py`)

- Estimasi token sederhana (chars/4 heuristic, model-aware untuk beberapa provider).
- `SUMMARY_PLACEHOLDER = "[Previous conversation summarized]"` — **bagian lama percakapan
  dipotong dan diganti placeholder, tanpa summarisasi sungguhan**. Ini gap yang diketahui
  (lihat tabel perbandingan).

### 2.3 Prompt caching

- Breakpoints `cache_control` diterapkan pada system prompt + pesan awal (Anthropic/OpenRouter).
- Konsisten dengan pola "frozen snapshot": jangan mutasi pesan lama di tengah sesi.

### 2.4 Tool system

- **40 handler tool sungguhan** (aktif default saat startup) yang dipilih model tiap API call.
- Taksonomi **28 toolsets** (`toolsets.py`) = cermin desktop untuk dokumentasi; tool tanpa
  implementasi **tidak pernah dikirim ke model** (UI menampilkan "x/y" + disable).
- Eksekusi tool: `_builtin_tools` → skill fallback; hasil → `role=tool` message.

### 2.5 Skills (`skills/manager.py`)

- Python file/package + `skill.yaml` (JSON-schema args), hot-reloadable.
- Mempunyai `skill_memory` sendiri (tabel §1.3).

### 2.6 Gateway / remote

- Gateway: adapter platform (Telegram saat ini) → `PairingManager` (kode 8 karakter, rate-limit)
  → `GatewayStreamConsumer` → agent streaming → edit pesan.
- Remote: koneksi WebSocket JSON-RPC ke backend Hermes Desktop (mode berbeda dari local agent).

---

## 3. Prompt untuk Claude — rancang skema yang lebih baik

Tempel bagian berikut ke Claude (atau LLM lain) beserta dokumen ini:

```
Kamu adalah arsitek sistem memory & harness untuk AI agent mobile bernama "Hermes Mobile"
(Python, Flet, Android APK). Aku punya skema memory dan harness yang sedang berjalan sekarang —
lampirannya ada di dokumen ini (SQL lengkap, loop agent, tool system, kompresi konteks).

KONTEKS DAN BATASAN:
1. Berjalan di perangkat Android → RAM dan penyimpanan terbatas, offline-first.
2. Semua data pribadi harus terenkripsi-at-rest (Fernet, key per-device).
3. Agent dipakai sehari-hari: harus ingat preferensi user, fakta lingkungan, konvensi proyek,
   dan pelajaran dari sesi sebelumnya — tanpa menambah token secara permanen ke tiap prompt.
4. TIDAK BOLEH menambah dependensi berat (no vector DB server, no ML runtime besar).
   Embedding ringan (on-device, opsional) BOLEH dipertimbangkan jika ada library kecil
   yang sudah umum dipakai.
5. Provider model beragam (OpenRouter/OpenAI/Anthropic/Gemini/Ollama lokal) — skema tidak
   boleh bergantung pada satu vendor.
6. Prompt caching penting: system prompt harus stabil (frozen snapshot) supaya prefix cache
   tidak invalid di tengah sesi.

YANG AKU MINTA:
A. Analisis kelemahan skema sekarang (SQL + harness), urutkan berdasarkan dampak.
B. Rancang SKEMA MEMORI BARU yang lebih baik, minimal mencakup:
   - pemisahan memori "fakta stabil" vs "peristiwa/percakapan" vs "preferensi user";
   - mekanisme relevansi (keyword → embedding on-device opsional);
   - kapasitas terbatas + aturan konsolidasi/eviction (TTL, prioritas, dedup);
   - bagaimana memori masuk ke konteks (frozen snapshot di system prompt vs retrieval per-turn);
   - pencarian sesi yang baik tanpa FTS (karena data terenkripsi) ATAU argumen kapan FTS layak.
C. Rancang HARNESS yang ideal untuk agent harian: kapan menyimpan memori secara otomatis,
   kapan bertanya ke user, kapan mengkonsolidasi, dan bagaimana integrasinya dengan loop agent
   yang sudah ada (tool calls + streaming + kompresi).
D. Berikan DDL SQLite lengkap untuk skema baru + pseudo-code alur penyimpanan/retrieval.
E. Berikan rencana migrasi dari skema lama ke baru (data lama tetap terbaca).
F. Format jawaban: (1) ringkasan eksekutif, (2) kelemahan skema lama, (3) skema baru,
   (4) DDL, (5) alur, (6) migrasi, (7) trade-off & apa yang TIDAK perlu diubah.
```

> Tips: kirim juga isi `docs/ARCHITECTURE.md` dari repo ini sebagai konteks tambahan,
> karena memuat alur request end-to-end yang harus tetap kompatibel dengan skema baru.

---

## 4. Tabel Perbandingan — Hermes Mobile vs hermes-agent (Nous Research)

| Dimensi | **Hermes Mobile** (repo ini) | **hermes-agent by Nous** (referensi) |
|---|---|---|
| **Backend memory** | SQLite 1 file, 4 tabel (`conversations`, `memory_entries`, `skill_memory`, `kv_memory`) | **Flat file** `MEMORY.md` + `USER.md` di `~/.hermes/memories/` untuk memori aktif; **SQLite** (`~/.hermes/state.db`) untuk riwayat sesi |
| **Model memori aktif** | KV + entri jangka panjang dengan TTL, dipanggil on-demand via tool `memory_tool` | **Frozen snapshot** — memori aktif di-inject ke system prompt di awal sesi, tidak pernah berubah di tengah sesi (preserve prefix cache) |
| **Kapasitas memori aktif** | Tidak dibatasi (tergantung jumlah entri, diambil saat tool dipanggil) | **Dibatasi ketat**: `MEMORY.md` 2.200 char (~800 token), `USER.md` 1.375 char (~500 token); jika penuh, tool mengembalikan error dan agent mengkonsolidasi sendiri |
| **Pemilahan memori** | Satu namespace KV + `memory_entries` (tanpa semantik) | **2 target**: `memory` (fakta lingkungan/teknis) vs `user` (profil & preferensi user) — keduanya punya limit & format tampilan sendiri |
| **Aksi tool memory** | `store / retrieve / search / list / delete` (KV + keyword) | `add / replace / remove` — **tanpa read** (memori sudah otomatis di konteks); `replace/remove` pakai substring match + anti-duplikat |
| **Pencarian relevansi** | Keyword scoring sederhana (split query → match) | Embedding opsional (plugin komunitas: LanceDB, Mnemosyne, dll.) + FTS5 untuk sesi |
| **Pencarian sesi** | `LIKE` SQLite / filter Python (terenkripsi) — dasar | **FTS5 full-text** di SQLite + scroll maju/mundur dalam sesi; ~20ms query, tanpa LLM |
| **Keamanan** | Fernet enkripsi-at-rest (semua kolom nilai) | Scan keamanan saat menulis (anti prompt-injection, anti exfiltration, blokir invisible Unicode); **tanpa enkripsi bawaan** |
| **Konsolidasi memori** | TTL + `cleanup_expired()` (cron harian); tanpa konsolidasi konten | Agent sendiri yang mengkonsolidasi saat limit tercapai (merge/remove dalam turn yang sama); auto-dedup exact match |
| **Persistensi otomatis** | Manual via tool agent (harus dipanggil model) | **Otomatis**: background self-improvement review setelah turn + tool memory; bisa di-gate `write_approval` |
| **Learning journey / grafik** | Tidak ada | Ada: timeline "journey" — semua skill + memori sebagai node, bisa di-prune/edit/delete |
| **Kompresi konteks** | Placeholder `[Previous conversation summarized]` (tanpa summarisasi sungguhan) | Ringkasan LLM untuk sesi; memori aktif dipisah agar tidak ikut terpotong |
| **Prompt caching** | Cache breakpoints pada system prompt + pesan awal | Frozen-snapshot memory → prefix cache stabil (pola yang sama) |
| **Tool system** | 40 handler sungguhan, 28 toolsets taksonomi, tool mati disaring dari model | ~50+ tool lintas toolsets, skill system + kanban + computer use + voice |
| **Browser** | WebView engine (Android) + fetcher statis httpx/BS4; tool: navigate/snapshot/back/click/scroll/type/get_images | CDP-based (Chrome DevTools Protocol) full automation |
| **Multi-agent / kanban** | Plugin stub (kanban) | Kanban multi-agent + negotiation mode di agent loop |
| **Target** | **Android APK / mobile** (RAM & storage terbatas, offline-first, encrypted) | Desktop / server (Docker multi-arch), CLI + messaging gateway |
| **Dependensi memory** | stdlib SQLite + cryptography (Fernet) | stdlib + opsional (embedding, FTS5) |

### Kesimpulan singkat

- **Yang sudah baik di Hermes Mobile**: enkripsi-at-rest (keunggulan nyata vs desktop),
  pemisahan tabel per domain (conversations/memory/skill/kv), TTL, frozen-snapshot-compatible
  caching, dan tool memory ter-encrypted.
- **Gap terbesar** (target prompt Claude di §3): (a) tidak ada pemisahan semantik
  memori-vs-profil-user; (b) tidak ada batas kapasitas + konsolidasi otomatis; (c) relevansi
  keyword saja; (d) pencarian sesi tanpa FTS; (e) kompresi konteks placeholder; (f) persistensi
  memory tidak otomatis (bergantung model memanggil tool).

---

*Diperbarui: setelah penambahan WebView engine (`flet-webview`), view Browser, tool
`browser_scroll`/`browser_type`/`browser_click`, dan audit toolsets (40 handler aktif).
Skema memory tidak berubah pada iterasi itu.*
