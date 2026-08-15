# Memory Harness v2 — Gap Analysis & Fix Request

**Status:** Review document — diberikan kepada AI pembuat skema untuk direvisi
**Yang direview:** Draft "Memory Harness v2" (schema SQL + desain harness, 55 section)
**Dasar review:** Implementasi aktual Hermes Mobile (`memory/provider.py`, `core/agent.py`, `core/context_compressor.py`, `core/prompt_caching.py`, `cron/`)
**Bahasa:** Dokument ini untuk dikonsumsi AI; istilah teknis dibiarkan dalam bahasa Inggris.

---

## 0. Ringkasan Eksekutif

Desain v2 secara prinsip **sudah benar**: pemisahan Memory ≠ Conversation, Observation ≠ Fact,
snapshot frozen, event-driven tanpa daemon, no-FTS5-on-ciphertext, migration bertahap.
**Jangan rombak ulang yang sudah benar** (lihat §6).

Masalah utama bukan pada arah desain, tetapi pada:

1. **Bug nyata di DDL/migration SQL** yang akan memblokir implementasi (§1).
2. **Scope terlalu besar untuk mobile** — beberapa bagian sebaiknya ditunda, bukan dihapus (§2).
3. **Keputusan desain yang terlalu kompleks** untuk nilai yang didapatnya (§3).
4. **Ketidakselarasan dengan API yang sudah ada** — desain harus didefinisikan terhadap fungsi nyata di codebase (§4).

Prioritas penyelesaian: **§1 wajib**, **§2–§4 direvisi**, §5 opsional.

---

## 1. 🔴 MUST-FIX — Bug yang memblokir implementasi

### GAP-1: Migration SQL melanggar NOT NULL constraint

**Problem:**
`messages.message_id TEXT NOT NULL`, tetapi INSERT Phase 2 (migrasi `conversations` → `messages`)
tidak mengisi kolom `message_id`. Semua baris legacy akan gagal dengan
`NOT NULL constraint failed: messages.message_id`.

**Fix yang diminta:**
- Buat `message_id` nullable, **atau** isi fallback `message_id = id` pada INSERT migrasi,
- Dan tambahkan kolom `sequence_no` yang terisi (sudah ada via `ROW_NUMBER()`) sebagai
  pengganti `message_id` untuk urutan.

**Acceptance:**
- Migration dari database dengan 100+ percakapan nyata selesai tanpa error,
  semua baris terbaca kembali, urutan pesan benar.

### GAP-2: `PRAGMA foreign_keys = ON` tidak cukup di DDL

**Problem:**
`PRAGMA foreign_keys` bersifat **per-connection** di SQLite (default OFF).
Menuliskannya di file DDL hanya berlaku untuk koneksi yang menjalankan DDL;
koneksi berikutnya yang dipakai aplikasi akan mengabaikan FK, sehingga
`ON DELETE CASCADE` pada `messages`/`memory_evidence` tidak akan bekerja.

**Fix yang diminta:**
- Sebutkan eksplisit bahwa setiap pembukaan koneksi harus menjalankan
  `PRAGMA foreign_keys = ON` (mis. via hook `connection.set_pragma` di repository layer),
- Jangan mengandalkan DDL saja.

**Acceptance:**
- Menghapus session menghapus `messages`-nya (terverifikasi via test),
  termasuk saat koneksi dibuat ulang.

### GAP-3: Migrasi data terenkripsi tidak boleh menyalin ciphertext antar format

**Problem:**
Draft §37 sudah mencatat ini ("perform migration through the existing repository layer"),
tetapi contoh SQL-nya (`INSERT ... FROM conversations`) menyalin kolom mentah.
Jika skema v2 mengubah cara enkripsi/wrapping, ciphertext lama tidak kompatibel
dengan reader baru.

**Fix yang diminta:**
- Migration **wajib** lewat repository layer: decrypt → re-encrypt ke format baru,
- Beri pseudocode migrasi di level repository, bukan hanya SQL mentah,
- Sertakan verifikasi pasca-migrasi: jumlah baris, sampel acak, nilai terdekripsi sama.

---

## 2. 🟠 REVISI SCOPE — Bagian yang sebaiknya ditunda (bukan dihapus)

Konteks: runtime ini adalah **aplikasi mobile Android**, bukan daemon desktop.
Tidak ada task executor persisten; cron = subprocess terjadwal.

### GAP-4: Task state machine + checkpoint/recovery penuh (§29–32)

**Problem:**
`task_store` + `checkpoint` per tool-call + `recover_tasks()` mengasumsikan
proses yang bisa di-restart di tengah tugas. App ini tidak punya mekanisme itu;
"resume" hanya berarti sesi chat baru.

**Fix yang diminta:**
- Turunkan menjadi **session state sederhana**: simpan status sesi
  (`active/completed/failed`) + timestamp, tanpa per-iteration checkpoint,
- Recovery cukup: sesi `active` saat startup → tandai `paused`,
- Hapus `task_id`/`checkpoint` dari pseudocode `run_conversation()`; cukup catat
  observasi tool (lihat GAP-5).

### GAP-5: Observation + Verification layer per-tool (full pipeline)

**Problem:**
Menuntut 40 tool handler yang ada mengekspos verifier = kerja besar dengan
nilai tidak merata. "A tool result saying success is not verification" benar,
tetapi menerapkannya ke semua tool memblokir rilis.

**Fix yang diminta:**
- Verifier hanya untuk tool **side-effect tinggi**: `write_file`, `patch`,
  `cronjob`/scheduler, `memory` save, gateway send,
- Tool lain cukup dicatat sebagai observation tanpa verifier,
- Field `verification_status` di observation boleh nullable/absent.

### GAP-6: `memory_links` (graph supports/contradicts/duplicates)

**Problem:**
Relasi antar-memori bisa didapat via query langsung (mis. `supersedes_id` pada
`memory_items`, pencocokan `normalized_content`); tabel graph menambah kompleksitas
dan maintenance tanpa kebutuhan jelas di rilis pertama.

**Fix yang diminta:**
- Pertahankan `memory_items.supersedes_id` (sudah ada, bagus),
- **Hapus `memory_links` dari v1**; tambahkan belakangan bila ada kebutuhan
  navigasi/visualisasi memori,
- `memory_events` cukup untuk audit trail.

### GAP-7: Migrasi `conversations` → `sessions` + `messages`

**Problem:**
Duplikasi storage (transkrip penuh di dua tempat) + risiko migrasi untuk
nilai yang kecil. Sesi chat bisa tetap disimpan di tabel `conversations` yang ada.

**Fix yang diminta:**
- **Jangan migrasi `conversations` di v1.** Pertahankan sebagai session store,
- v2 cukup **menambah** `memory_items`, `memory_evidence`, `session_summaries`
  (+ opsional `memory_snapshot`),
- Compatibility provider (§41) membaca `conversations` langsung untuk
  `search_sessions`, dan `memory_entries` untuk memori lama.

### GAP-8: `memory_snapshot` menyimpan teks penuh per session

**Problem:**
`snapshot_text` diduplikasi untuk setiap session; snapshot bisa direkomputasi
dari `memory_items`.

**Fix yang diminta:**
- Simpan hanya `content_hash` + `memory_ids` + `token_estimate` (perlu teks untuk
  cache-stability debug? simpan di file log bukan DB),
- Atau buat snapshot **satu baris global** (bukan per-session) yang menunjuk ke
  hash snapshot aktif.

---

## 3. 🟠 REVISI DESAIN — Penyederhanaan

### GAP-9: Skor kandidat 6 dimensi terlalu banyak tuning

**Problem:**
Formula `0.25*explicitness + 0.20*stability + 0.15*recurrence + 0.20*usefulness
+ 0.20*confidence` dengan penalty `0.20*sensitivity + 0.20*contradiction` —
6 parameter tanpa data empiris. Hasilnya sulit diuji dan rentan "magic number".

**Fix yang diminta:**
- v1 cukup **3 dimensi**: `explicitness`, `confidence`, `sensitivity`,
- Aturan sederhana: marker eksplisit (remember / I prefer / from now on) +
  `confidence >= 0.85` dan `sensitivity < 0.5` → AUTO_SAVE;
  `0.50 <= confidence < 0.85` → ASK; sisanya IGNORE,
- Simpan formula penuh sebagai **evolusi lanjutan** (dengan data dari test).

### GAP-10: Dedup berbasis "keyword similarity" tidak reliable

**Problem:**
Similarity kata-kunci menghasilkan false positive (memori berbeda tapi mirip
leksikal) dan false negative (konten sama, kata berbeda).

**Fix yang diminta:**
- v1 dedup **hanya exact match** pada `normalized_content` + `scope_type` +
  `scope_id`,
- Kontradiksi ditangani via `supersedes_id` dengan konfirmasi user (sudah benar),
- Similarity/embedding = fase lanjutan, bukan v1.

### GAP-11: ASK tidak boleh menggantung turn

**Problem:**
Alur ASK memakai `clarify_tool` (interaksi user). Jika user tidak menjawab
(sesi via gateway, app di background), turn menggantung.

**Fix yang diminta:**
- ASK punya **timeout** (default 30–60s) → fallback **IGNORE** + catat
  `memory_events` (`ask_requested` tanpa `approved/rejected`),
- Di konteks tanpa UI interaktif (gateway), default **IGNORE** kecuali
  konfigurasi eksplisit mengizinkan ASK,
- `pending_confirmation` TTL 14 hari sudah benar — pastikan cleanup-nya jalan.

### GAP-12: Normalisasi content untuk dedup

**Problem:**
`normalized_content` untuk dedup — lowercase merusak konten yang case-sensitive
(hanya untuk dedup sih boleh), tetapi whitespace/punctuation normalization
belum dispesifikasikan.

**Fix yang diminta:**
- Spesifikasikan normalisasi eksplisit: `lowercase → strip → collapse spaces →
  strip trailing punctuation`,
- Simpan `content` asli terpisah (sudah ada — bagus); `normalized_content`
  hanya untuk lookup/dedup,
- Tambahkan kolom hash (`normalized_hash`) untuk lookup O(1) tanpa FTS.

---

## 4. 🟡 SELARASKAN DENGAN KODE YANG ADA

### GAP-13: Compatibility provider harus didefinisikan terhadap fungsi nyata

**Problem:**
Draft §41 memberikan nama method generik, tetapi codebase punya API konkret
yang harus tetap jalan (tool `memory` memanggilnya):

```
MobileMemoryProvider.store_memory(key, value, ttl_days)
MobileMemoryProvider.get_memory(key)
MobileMemoryProvider.get_relevant_context(query, limit)   # keyword scoring
MobileMemoryProvider.search_sessions(query, limit)         # LIKE saat ini
MobileMemoryProvider.cleanup_expired()                     # dipanggil cron harian
```

**Fix yang diminta:**
- Definisikan `MemoryProviderV2` dengan **signature yang sama persis** dengan
  method di atas (bukan nama baru),
- `memory_tool`, `session_search_tool`, `get_relevant_context` tetap memanggil
  nama yang sama — hanya implementasi internal yang berubah,
- Mapping eksplisit: method lama → method v2.

### GAP-14: Consolidation harus reuse cron yang sudah ada

**Problem:**
Draft §19 menyebut "scheduled maintenance if the app already has a scheduler" —
app ini **punya**: cron job `cleanup_memory` (harian 03:00) memanggil
`cleanup_expired()`, plus ticker 60s.

**Fix yang diminta:**
- Consolidation dipicu dari **`cleanup_expired()`** (jangan buat scheduler baru),
- Trigger lain: sesi start (jika `has_pending_consolidation`), sesi end,
  request eksplisit user, ambang kapasitas,
- Tulis ini eksplisit di §19 supaya implementer tidak membuat daemon.

### GAP-15: Token budget snapshot harus punya default & kait dengan konfigurasi

**Problem:**
`build_snapshot(token_budget=config.memory_snapshot_tokens)` tidak memberi
default; codebase punya `max_context_tokens` (default 128000) dan kompresi
di `context_compressor`.

**Fix yang diminta:**
- Beri default eksplisit: **snapshot 600–1200 token** (budget kecil, stabil,
  cache-friendly),
- Nyatakan interaksi: snapshot masuk region stable prefix; per-turn retrieval
  masuk region mutable setelahnya (konsisten dengan §48),
- Tentukan apa yang terjadi jika snapshot + summary + recent melebihi
  `max_context_tokens` (urutan drop: retrieval → recent lama → summary).

### GAP-16: Session search — spesifikasikan desain bounded-decrypt

**Problem:**
Keputusan "no FTS5 on ciphertext" benar. Tapi §46 masih samar tentang
pemeringkatan.

**Fix yang diminta:**
- Spesifikasikan pipeline konkret: `query → tokenize (Python) → filter session
  by metadata/recency (SQL) → decrypt bounded window (mis. 40 pesan terakhir
  per session kandidat) → keyword score → top-K`,
- Batas kandidat default (mis. 20 session) dan batas decrypt per session,
- Sertakan fallback: jika decrypt gagal → skip session (tidak crash).

---

## 5. 🟡 OPSIONAL — Catatan kecil

### GAP-17: Migration default confidence 0.70
Reasonable. Tambahkan `source_type = 'imported'` + evidence `imported` (sudah
ada di draft — pertahankan).

### GAP-18: Bahasa contoh dalam dokumen
Contoh memakai Bahasa Indonesia ("Saya lebih suka jawaban dalam Bahasa
Indonesia"). Tidak masalah untuk isi, tetapi pastikan classifier/template
**locale-agnostic** (marker di Level 1 sebaiknya multilingual atau
dikonfigurasi).

### GAP-19: Observability
Daftar event §50 bagus. Tambahkan satu aturan: **event payload tidak pernah
berisi teks memori/snapshot mentah** (cukup id + type + hash).

---

## 6. ✅ Yang SUDAH BENAR — Jangan diubah

Agar AI pembuat skema tidak membuang waktu mengulang:

1. **Pemisahan konseptual** Memory ≠ Conversation ≠ Permission ≠ Verification.
2. **Frozen snapshot immutable per-session** + `pending_snapshot` — konsisten
   dengan prompt-cache breakpoints yang sudah ada.
3. **No FTS5 pada ciphertext** — keputusan benar; arah bounded-decrypt benar.
4. **`skill_memory` & `kv_memory` tidak disentuh** — API tetap.
5. **`memory_items.status` state machine** (candidate → active/superseded/
   expired/rejected) — benar.
6. **TTL per kelas memori** dengan default (profile: no TTL, episodic: 7–90d) —
   benar; tinggal diikat ke `cleanup_expired()`.
7. **Kapasitas per kelas + urutan eviction** (expired → low-confidence →
   low-importance → episodic lama) — benar.
8. **Evidence model** (`memory_evidence` + source type) — inti nilai desain ini;
   pertahankan.
9. **Migration bertahap + dual read + tidak menghapus tabel lama** — benar.
10. **Tidak ada daemon/embedding wajib/vector DB** — pertahankan sebagai
    non-goal.

---

## 7. Urutan Implementasi yang Direkomendasikan (untuk AI pembuat skema)

Revisi schema harus mendukung urutan ini — v1 jangan mendesain untuk v5:

- **Phase A (nilai tinggi, effort kecil):** summarization nyata menggantikan
  placeholder + frozen snapshot + hash.
- **Phase B:** `memory_items` + `memory_evidence` + `session_summaries`
  (tanpa migrasi conversations; tanpa memory_links; tanpa memory_snapshot per
  session).
- **Phase C:** candidate extraction Level 1 (marker) + policy
  AUTO_SAVE/ASK/IGNORE (3 dimensi) + ASK timeout + dedup exact-normalized +
  TTL/kapasitas di `cleanup_expired()`.
- **Phase D (lanjutan):** bounded-decrypt search, observability, skor penuh,
  embeddings opsional.

## 8. Acceptance untuk Skema Revisi

Skema v2 revisi dianggap selesai jika:

- [ ] GAP-1 & GAP-2 & GAP-3 tertutup (migrasi jalan tanpa error, FK per-koneksi,
      migrasi via repository layer).
- [ ] GAP-4 & GAP-5 & GAP-6 & GAP-7 & GAP-8: scope dipotong sesuai (tidak ada
      task state machine penuh, verifier hanya side-effect tinggi, tanpa
      memory_links, tanpa migrasi conversations, snapshot tanpa teks duplikat).
- [ ] GAP-9 & GAP-10 & GAP-11 & GAP-12: skor 3 dimensi, dedup exact-normalized,
      ASK punya timeout, normalisasi dispesifikasikan.
- [ ] GAP-13 & GAP-14 & GAP-15 & GAP-16: compatibility provider berkontrak ke
      method nyata, consolidation via cron yang ada, token budget punya default,
      bounded-decrypt search dispesifikasikan.
- [ ] §6 (yang sudah benar) tidak berubah.
