# Memory Galaxy — Analisis Konsep (Ide Tersimpan)

> Status: **Konsep / design draft — BELUM diimplementasikan**
> Analisis ini berbasis struktur aktual repository (diverifikasi langsung dari kode), bukan asumsi.
> Tanggal analisis: setelah audit menyeluruh user-testing (browser, session search, cron).

Memory Galaxy adalah visualisasi interaktif memory & knowledge agent berbentuk graph/galaxy,
terinspirasi Graph View Obsidian — tetapi bukan salinan. Node = entitas memory (fact, project,
task, decision, preference, dst); Edge = relasi (related_to, depends_on, derived_from,
implements, contradicts, supersedes, belongs_to, references).

Dokumen ini mencatat konsep + analisis kelayakan. Keputusan implementasi ditunda sampai
arsitektur memory matang (lihat bagian Rekomendasi & Tahapan).

---

## 1. Kondisi Repository Saat Ini (fakta dari kode)

### 1.1 Arsitektur memory

- **Storage:** satu SQLite (`memory.db`), Fernet-encrypted (PBKDF2, key per-device).
- **Tabel aktual** (`hermes_mobile/memory/provider.py`):

| Tabel | Isi | Relevansi sebagai "node" graph |
|---|---|---|
| `memory_items` | Harness v1: `memory_type` (stable_fact/user_profile/learned_pattern/episodic), `scope_type` (global/user), `status` (candidate/pending_confirmation/active/superseded/expired/rejected), `confidence`, `importance`, `sensitivity`, `source_type`, `source_session_id`, `normalized_hash`, timestamps, **`supersedes_id`** | **Node utama — sudah 80% siap** |
| `memory_evidence` | `memory_id → evidence_type, session_id, evidence_text, verified` | Edge "berasal dari sesi X" (provenance) |
| `session_summaries` | `session_id, summary, summary_version` | Node "session" |
| `conversations` | transkrip sesi per-message | Sumber inferensi (mahal) |
| `memory_entries` | legacy, punya kolom `metadata` JSON (tidak ada caller yang mengisinya) | Sekunder |
| `kv_memory`, `skill_memory` | key/value | Tidak relevan untuk graph |

- **Proses:** `harness.py` — ekstraksi marker → policy `AUTO_SAVE/ASK/IGNORE` → persist +
  evidence → frozen snapshot per sesi. Dedup via `normalized_hash` (plaintext hash, karena
  konten terenkripsi).
- **Tidak ada FTS, tidak ada embedding** (kolom `embedding` di `memory_entries` berlabel
  cadangan: selalu NULL).

### 1.2 Relasi yang SUDAH ada (kunci analisis)

1. **`supersedes_id`** di `memory_items` + method `supersede_memory()` — edge "supersedes"
   sudah didesain, tapi **tidak ada satu pun caller produksi** (hanya test). Kolomnya kosong
   di praktik.
2. **`memory_evidence.memory_id → session_id`** — edge "berasal dari sesi X".
3. **Co-session** — dua memory dengan `source_session_id` sama (derivable, gratis).
4. **TIDAK ADA `memory_links`** — dan ini keputusan sadar: `docs/memory-harness-v2-gap.md`
   GAP-6 secara eksplisit menulis *"Hapus memory_links dari v1; tambahkan belakangan **bila
   ada kebutuhan navigasi/visualisasi memori**"*. Memory Galaxy justru adalah kebutuhan itu —
   repo sudah "menyiapkan kursi" untuk fitur ini.

---

## 2. Jawaban atas 15 Pertanyaan Kunci

1. **Arsitektur memory sekarang?** Harness v1 incremental: `memory_items` + evidence +
   summaries, di atas SQLite terenkripsi. Ringan, offline, tanpa daemon.
2. **Struktur data?** Tabel di atas; semua nilai teks terenkripsi; search = keyword scoring
   sederhana / LIKE.
3. **Sudah ada relationship/link antar-memory?** Hanya `supersedes_id` (kosong di produksi)
   dan evidence (memory→session). Tidak ada relasi antar-node memory yang diisi.
4. **Natural direpresentasikan sebagai graph?** Sebagian ya, sebagian tidak. `memory_items`
   natural sebagai node. Tapi yang membuat Graph View Obsidian menarik adalah **backlink
   eksplisit**; repo ini tidak punya relasi eksplisit yang diisi. Tanpa itu, satu-satunya
   "related" yang bisa dihitung sekarang adalah **keyword overlap** — graph yang menyesatkan:
   dua memory yang kebetulan share kata "project" bukan berarti berhubungan.
5. **Entity/metadata/tag/relation/embedding/vector/semantic?** Ada `memory_type`, `scope_type`,
   `status`, `confidence`, `importance`, `sensitivity`, `source_type`, `source_session_id`,
   `normalized_hash`. Tidak ada tag bebas, tidak ada relation table, tidak ada embedding/vector.
6. **Sumber data terbaik untuk Memory Galaxy?** `memory_items` (node) + `memory_evidence`
   (provenance edge) + `session_summaries` (node session). `conversations` hanya sebagai
   sumber inferensi on-demand (mahal untuk di-scan penuh).
7. **Cocok dengan arsitektur?** Cocok **bila** dibangun sebagai lapisan query di atas
   `memory_items` + link table baru, dengan visualisasi lokal sebagai jendela kecil. Tidak
   cocok bila dibuat "galaxy global" yang menuntut precompute embedding/vector.
8. **Dampak Android low-end?** Rendering ribuan node = beban GPU/RAM. `flet.canvas`
   (Canvas/Circle/Line/Text/Path) + `ft.InteractiveViewer` (pan/zoom) tersedia di Flet 0.86
   tanpa dependensi baru — renderer 2D sederhana cukup. Graph global ribuan node di layar
   kecil = tidak berguna secara UX; local graph (≤ 50 node) = murah dan berguna.
9. **Library graph?** Tidak ada (no networkx/d3/vis). Karena aturan repo melarang dep tanpa
   justifikasi (tiap dep menambah ukuran APK), **renderer sendiri di atas `flet.canvas`
   lebih baik** untuk MVP. Networkx (pure-python) boleh dipertimbangkan belakangan hanya
   untuk layout force-directed, bukan rendering.
10. **Graph global vs lokal?** **Lokal.** Graph global = kosmetik mahal + performa buruk di
    low-end. Local graph (node di sekitar memory yang sedang dibuka, expandable hop-by-hop)
    = informatif, murah, dan natural untuk layar sentuh.
11. **Progressive rendering?** 3 lapis: (a) query hanya node dalam radius N hop; (b) virtualize
    — hanya render node di viewport + cap total node (mis. 50-80) dengan indikator "+N di
    luar"; (c) lazy layout — posisi dihitung on-demand, cache hasil layout per node.
12. **Visualization layer saja?** **Ya, mutlak.** Database/memory layer tetap sumber kebenaran.
    Graph hanya view (read-only) atas query graph. Tidak boleh ada jalur tulis melalui graph.
13. **Baca relasi existing atau schema baru?** Keduanya: **baca** `supersedes_id` +
    co-session + evidence dulu (gratis), **tambah schema relasi baru** (`memory_links`) hanya
    bila kebutuhan navigasi/visualisasi benar-benar ada — GAP-6 memang menunggu kebutuhan ini.
    Relasi yang ditambahkan harus **verified** (user atau agent dengan konfirmasi), bukan
    asumsi keyword-overlap.
14. **Interaksi dengan AI agent?** Ini nilai tambah terbesar:
    - agent menjelaskan alasan dua memory berhubungan (dari evidence + session context);
    - agent menemukan cluster/topik (hierarchical clustering sederhana di atas teks memory —
      tanpa embedding, pakai keyword/Jaccard);
    - agent mendeteksi kontradiksi (dua memory aktif yang saling bertentangan — bisa jadi
      sumber `contradicts` edge);
    - agent menemukan chain Research → Decision → Task → Implementation (via `source_session_id`
      + urutan waktu + type);
    - user pilih node → minta agent analisis konteks (retrieval session + evidence terkait).
    Semua ini adalah **query surface** — tidak menuntut precompute.
15. **Manfaat praktis vs daftar/search biasa?** Ya, tapi terbatas: chain/contradiction
    discovery dan "kenapa memory ini ada" (provenance visual) adalah hal yang tidak bisa
    dilakukan daftar biasa. Selebihnya, search tetap jalan utama; graph adalah pelengkap.

---

## 3. Klasifikasi: A / B / C

### A. Bisa dibuat dengan arsitektur sekarang (tanpa perubahan besar)

- **Local graph read-only** dari data yang sudah ada:
  - node: `memory_items` aktif (+ session node dari `session_summaries`);
  - edge: `supersedes_id`, co-session (`source_session_id` sama), evidence → session;
  - layout: renderer `flet.canvas` + `InteractiveViewer`, cap node, virtualisasi viewport.
- **Agent analysis on-demand** (tanpa schema baru): minta agent jelaskan hubungan/chain
  dengan retrieval session + evidence terkait; hasil ditampilkan sebagai teks di chat —
  belum jadi edge permanen.
- **Contradiction detection ad-hoc**: agent scan memory aktif (jumlah kecil) + laporkan
  kandidat kontradiksi di chat.

### B. Butuh perubahan schema / memory layer

- **`memory_links` table** (from_memory_id, to_memory_id, relation_type, verified,
  created_by, evidence_ref, timestamps) — sesuai GAP-6, ditambah **belakangan** ketika
  kebutuhan navigasi terbukti. Bounded: hanya relasi verified.
- **Tag/entity ringan** di `memory_items` (kolom `tags` JSON / tabel `memory_tags`) untuk
  klasterisasi dan filter. (Opsional; bisa ditunda.)
- **`normalized_keywords`** (plaintext) di `memory_items` untuk clustering Jaccard tanpa
  decrypt massal. (Opsional; konsisten dengan pola `normalized_hash` yang sudah ada.)

### C. Ditunda sampai arsitektur memory matang

- **Embedding / vector search** — mahal di APK, butuh on-device model; tidak diperlukan
  untuk MVP lokal graph.
- **Global galaxy** (ribuan node) — precompute + performa + UX tidak layak di low-end.
- **Auto-linking dari keyword overlap** — menghasilkan edge palsu; menyesatkan.
- **Memory Galaxy sebagai produk utama** — visualisasi bukan produk; relasi memory yang
  terisi + query surface adalah produknya.

---

## 4. Rekomendasi Arsitektur

```
┌─────────────────────────────────────────────────────────────┐
│  Memory layer (sumber kebenaran, TIDAK berubah)              │
│  SQLite: memory_items · memory_evidence · session_summaries  │
│          (+ memory_links di fase B — hanya relasi verified)   │
└──────────────────────────┬──────────────────────────────────┘
                           │ query graph (read-only)
┌──────────────────────────▼──────────────────────────────────┐
│  Graph query layer (baru, kecil)                             │
│  · get_local_graph(memory_id, radius=1..2, cap=60)          │
│  · edges: supersedes | co-session | evidence | links(verified)│
│  · cluster hints (Jaccard ringan, on-demand)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ render
┌──────────────────────────▼──────────────────────────────────┐
│  Visualization layer (view saja)                             │
│  · flet.canvas + InteractiveViewer (pan/zoom)                │
│  · local graph ≤ 60 node, virtualisasi viewport              │
│  · tap node → detail (memory + evidence + sesi sumber)       │
│  · CTA: "minta agent analisis node ini" → chat               │
└─────────────────────────────────────────────────────────────┘
```

Aturan kunci (dari skema v2):
- **Memory != Conversation; Frozen Snapshot != Mutable Database** — graph hanya view.
- **Candidate != Verified Memory** — relasi dari agent = kandidat; butuh konfirmasi user
  sebelum jadi edge permanen.
- **Bounded everything** — cap node, cap hop, lazy layout.

---

## 5. Rekomendasi UX/UI Mobile

- **Entry point:** dari detail memory (Memory view) — tombol "Lihat relasi" → local graph
  sheet (bottom sheet penuh, bukan halaman baru).
- **Gestur:** tap node = detail; drag = pan; pinch = zoom; tap tombol "+1 hop" = expand;
  long-press = "analisis oleh agent".
- **Warna edge:** supersedes = merah, co-session = biru, evidence = abu, link verified = hijau.
- **Label:** memory text dipotong 40-60 char; node session ikon kecil terpisah.
- **Tanpa legenda global** — pakai tooltip per edge.

---

## 6. Strategi Performa Low-End

1. **Local graph, bukan global** — query radius 1-2 hop, cap 60 node.
2. **Virtualisasi viewport** — hanya render node yang terlihat; cache posisi.
3. **Lazy layout** — layout force-directed sederhana (atau radial) dihitung sekali per
   query, bukan per frame.
4. **Decrypt bounded** — hanya decrypt node yang dirender (pola `_SEARCH_WINDOW` yang sudah
   ada di provider).
5. **Tanpa embedding** — clustering Jaccard atas `normalized_keywords`/teks terbatas.
6. **Read-only query** — tidak ada tulis lewat graph → tidak ada konflik lock/tulis.

---

## 7. Tahapan Implementasi (MVP → Matang)

**Fase 0 (sekarang, tanpa kode baru):**
- [ ] Pastikan `memory_items` + evidence + summaries sehat (audit data aktual user).
- [ ] Generate session summary sungguhan (fix session_search — lihat audit user-testing).

**Fase 1 — Query surface (inti nilai):**
- [ ] `get_local_graph(memory_id)` — node aktif + edge supersedes/co-session/evidence.
- [ ] Agent analysis on-demand: pilih node → agent jelaskan relasi/chain di chat.
- [ ] Session summary + snippet di `session_search` (sudah diperbaiki — lihat audit).

**Fase 2 — Visualisasi lokal (jendela kecil):**
- [ ] Renderer `flet.canvas` + `InteractiveViewer` di Memory view (bottom sheet).
- [ ] Virtualisasi + cap node + expand hop.
- [ ] Tap node → detail (memory + evidence + sesi sumber).

**Fase 3 — Relasi permanen (schema, sesuai GAP-6):**
- [ ] `memory_links` (verified only) + method `link_memories()` / `unlink_memory()`.
- [ ] Agent mengusulkan link → ASK user → persist verified.
- [ ] Contradiction detection terjadwal (cron) → kandidat `contradicts` menunggu konfirmasi.

**Fase 4 — Matang (opsional, ditunda):**
- [ ] Clustering/topic ringan (Jaccard) di memory view sebagai "cluster galaxy".
- [ ] Embedding on-device opsional — hanya bila terbukti dibutuhkan dan ada library kecil.

---

## 8. Hal yang TIDAK Dibuat di Tahap Awal

- ❌ Global galaxy ribuan node.
- ❌ Auto-link dari keyword overlap (edge palsu).
- ❌ Embedding / vector DB.
- ❌ Graph yang bisa menulis/mengubah memory (graph = view).
- ❌ Force-directed layout real-time per frame (mahal).
- ❌ `memory_links` sebelum Fase 3 (GAP-6: tambahkan bila ada kebutuhan nyata — kebutuhan
  itu belum terbukti sampai local graph dipakai user).

---

## 9. Kesimpulan

**Dimodifikasi, lalu diteruskan.** Ide dasarnya bagus dan repo sudah menyiapkan fondasinya
(GAP-6 menunggu kebutuhan ini). Tapi bentuknya harus diubah: bukan "galaxy visual" sebagai
produk, melainkan **relasi memory sebagai query surface yang bisa dipakai user dan agent,
dengan visualisasi lokal sebagai jendela kecil ke permukaan itu**. Visualisasi tanpa relasi
yang diisi = kosmetik mahal. Mulai dari sisi query + local graph; tunda galaxy global dan
semantic layer.
