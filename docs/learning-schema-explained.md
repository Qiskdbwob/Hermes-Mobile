# Skema Learning (Memory & Harness) — Dijelaskan Secara Visual

> Versi sederhana dari `docs/memory-harness-schema.md`, memakai panah `>` dan diagram
> alur supaya mudah dipahami. Data mengikuti kode aktual (`core/agent.py`,
> `memory/harness.py`, `memory/provider.py`, `memory/summarizer.py`).

---

## 1. Gambaran Besar: 3 Lapisan

```
┌─────────────────────────────────────────────────────────────┐
│  LAPISAN 3 — UI & Sesuatu yang Kamu Lihat                    │
│  Chat · Memory view · Cron view · Browser view               │
└───────────────┬─────────────────────────────┬───────────────┘
                │                             │
┌───────────────▼───────────────┐ ┌───────────▼───────────────┐
│  LAPISAN 2 — Harness (otak)   │ │  LAPISAN 1 — Penyimpanan  │
│  putuskan: simpan / tanya /   │ │  SQLite memory.db         │
│  buang · bangun snapshot      │ │  (terenkripsi Fernet)     │
└───────────────┬───────────────┘ └───────────┬───────────────┘
                │                             │
                └─────────────┬───────────────┘
                              │
                     ┌────────▼────────┐
                     │  Model AI (LLM) │
                     └─────────────────┘
```

---

## 2. Alur SATU Turn Percakapan (loop agent)

```
Kamu mengetik pesan
        │
        ▼
[1] Pesan user masuk → ditambah ke riwayat (messages)
        │
        ▼
[2] Snapshot memori dipastikan ada (hanya SEKALI per sesi)
        │        system prompt = system + MEMORY SNAPSHOT (frozen)
        ▼
[3] Model dipanggil (streaming)
        │
        ▼
[4] Apakah model minta TOOL? ──ya──▶ eksekusi tool
        │                             │      (web_search, terminal,
        │ no                          │       browser, dll)
        ▼                             ▼
[5] Balasan final ditampilkan ◀── hasil tool kembali ke model
        │
        ▼
[6] Simpan percakapan ke DB (conversations)
        │
        ▼
[7] Buat RINGKASAN SESSION (ekstraktif, tanpa LLM) → session_summaries
        │
        ▼
[8] Harness: periksa pesan user → apakah ada yang layak DIINGAT?
        │
        ▼
[9] Selesai → tunggu pesan berikutnya
```

**Kunci:** langkah 2 (snapshot) terjadi **sekali per sesi** dan tidak pernah berubah di
tengah sesi — ini menjaga prompt cache tetap stabil. Memori baru masuk ke snapshot
**pada sesi berikutnya**, bukan langsung.

---

## 3. Alur Learning Jangka Panjang (harness) — yang paling penting

```
PESAN USER (contoh: "Ingat bahwa proyek saya pakai Postgres")
        │
        ▼
[A] EKSTRAKSI  → deteksi penanda (Indonesia/Inggris):
        │        "ingat/tolong/saya lebih suka/please remember/i prefer"
        │
        ▼
[B] KANDIDAT MEMORI  → {isi: "...", confidence: 0.95, sensitivity, type}
        │
        ▼
[C] CEK DUPLIKAT → normalized_hash → sudah ada? ──ya──▶ BUANG (duplicate)
        │
        ▼ tidak
[D] POLICY (aturan sederhana 3 dimensi):
        │
        ├─ confidence ≥ 0.85 & eksplisit  ──▶ AUTO_SAVE (langsung simpan)
        ├─ confidence 0.5–0.85            ──▶ ASK (tanya user, bounded/timeout
        │                                      30s; tanpa balasan → pending)
        └─ confidence < 0.5 / sensitif    ──▶ IGNORE (buang)
        │
        ▼
[E] SIMPAN → tabel memory_items + memory_evidence (dari sesi mana)
        │
        ▼
[F] Sesi berikutnya → memory ikut masuk ke SNAPSHOT (bounded token)
```

Contoh konkret:

```
"Ingat bahwa proyek saya pakai Postgres"   (confidence 0.95, eksplisit)
        │
        ▼ AUTO_SAVE
memory_items: {content: "proyek saya pakai Postgres",
               type: stable_fact, scope: global,
               status: active, confidence: 0.95}
        │
        ▼
evidence: {memory_id → session_id: "s3",
           evidence_type: user_explicit, verified: true}

"Ingat bahwa proyek saya pakai Postgres"   (diucapkan lagi nanti)
        │
        ▼ duplicate (hash sama) → IGNORE, tidak double-save
```

---

## 4. Siklus Hidup Memory Item (status)

```
                 ┌──────────┐
   ekstraksi ──▶ │ candidate│
                 └────┬─────┘
                      │ policy
        ┌─────────────┼──────────────┐
        ▼             ▼              ▼
   AUTO_SAVE       ASK          IGNORE (dibuang)
        │             │
        ▼             ▼
   active ◀── user konfirmasi (pending_confirmation)
        │
        ├── superseded (diganti fakta baru via supersedes_id)
        ├── expired (TTL lewat → cleanup_expired() tiap hari via cron)
        └── rejected (user tolak)
```

---

## 5. Ringkasan Sesi (session_summaries) — untuk "tadi kita bahas apa?"

```
Akhir turn → ringkasan ekstraktif dibuat (tanpa LLM):
        │
        ▼
"Topic: validasi browser · Exchanges: 3 · Keywords: webview, scroll,
 click · Tools: browser_navigate, browser_scroll · Latest: coba scroll"
        │
        ▼
disimpan di session_summaries (encrypted)
        │
        ▼
Saat user tanya "apa yang saya bahas tadi?"
        │
        ▼
session_search → cari keyword → kembalikan SUMMARY + snippet pesan
        │
        ▼
Model membaca summary → bisa menjawab dengan benar
```

---

## 6. Kenapa "Frozen Snapshot" itu Penting

```
SESI 1                          SESI 2
────────                        ────────
system prompt                   system prompt
  + SNAPSHOT A (fakta 1,2,3)      + SNAPSHOT B (fakta 1,2,3,4,5 — ada yang baru)
  (tidak berubah selama sesi 1)   (di-rebuild saat sesi 2 dimulai)

Kamu: "ingat fakta 4"  ──▶ disimpan ke DB, TAPI snapshot A tetap
                          Sesi 2 baru melihat fakta 4
```

Manfaat: prompt cache provider (Anthropic/OpenRouter) tidak invalid di tengah sesi →
biaya turun ±90% di system prompt.

---

## 7. Peta File (siapa melakukan apa)

```
core/agent.py            → loop turn: snapshot, model, tool, simpan, ringkas
memory/harness.py        → ekstraksi → policy → simpan memory_items + evidence
memory/summarizer.py     → ringkasan sesi ekstraktif (tanpa LLM)
memory/provider.py       → SQLite + Fernet: conversations, memory_items,
                           memory_evidence, session_summaries, kv_memory
cron/cleanup_memory.py   → hapus memory expired (TTL) tiap hari
cron/scheduler.py        → ticker 60 detik, jalankan job terjadwal
```

---

## 8. Analogi Sederhana

Bayangkan agent punya **3 buku catatan**:

1. **Buku harian percakapan** (`conversations`) — semua yang pernah dibicarakan, apa adanya.
2. **Buku catatan kecil** (`memory_items`) — fakta penting yang layak diingat; isinya
   disaring oleh aturan (harness). Setiap catatan diberi stempel: dari sesi mana,
   seberapa yakin, penting/tidak, sensitif/tidak.
3. **Daftar isi per hari** (`session_summaries`) — ringkasan singkat tiap sesi, supaya
   "tadi kita bahas apa?" bisa dijawab cepat tanpa membaca seluruh buku harian.

Setiap pagi (cron), catatan yang sudah kedaluwarsa dibuang (`cleanup_expired`).
