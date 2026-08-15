# Audit Tools — Hermes Mobile

> Audit berbasis kode aktual (bukan asumsi). Data diverifikasi langsung dari
> `core/agent.py` (registry handler + schema), `toolsets.py` (taksonomi), dan
> modul `tools/*.py` (implementasi).

---

## 1. Ringkasan Eksekutif

| Angka | Nilai |
|---|---|
| Tool dengan handler + schema (dikirim ke model) | **43** |
| Tool di taksonomi toolsets TANPA handler (mati) | **19** |
| Toolset terdefinisi (`toolsets.py`) | **28** (termasuk 7 komposit) |
| Tool yang butuh persetujuan user saat dipanggil | `terminal`, `process` (via `approval_callback`) |
| Tool yang di-block untuk subagent (delegation) | `delegate_task`, `delegate_tasks`, `clarify`, `cronjob`, `memory` |
| Tool fallback skill | Semua skill terpasang (file/package Python + `skill.yaml`) |

**Aturan penting:** taksonomi toolsets (`toolsets.py`) mencerminkan Hermes Desktop dan
**bukan** daftar tool yang benar-benar berjalan. Tool tanpa handler **tidak pernah**
dikirim ke model — UI Tools view menampilkan "x/y" + disable. Hanya 43 handler di
`_builtin_tools` yang dikirim.

---

## 2. 43 Tool Aktif (dikirim ke model)

Dikelompokkan per kategori, dengan catatan keamanan/implementasi.

### 2.1 Web & Riset
| Tool | Fungsi | Catatan |
|---|---|---|
| `web_search` | DuckDuckGo HTML search (tanpa API key) | max 10 hasil; SSRF-safe (hanya search endpoint publik) |
| `web_extract` | Ekstrak teks dari 1-5 URL | SSRF guard per hop redirect; max 8000 char |

### 2.2 Browser (sesi stateful)
| Tool | Fungsi | Catatan |
|---|---|---|
| `browser_navigate` | Buka URL → snapshot halaman | Sesi tunggal per proses (cookies + history) |
| `browser_snapshot` | Snapshot bersih (title/content/links) | alias navigate + rapi |
| `browser_current_page` | Baca halaman **saat ini** tanpa re-navigate | **Baru** — fix "harus ekstraks dulu" |
| `browser_back` | Kembali ke halaman sebelumnya | history sesi |
| `browser_click` | Klik link (href) atau elemen (CSS selector) | selector butuh WebView |
| `browser_scroll` | Scroll WebView (up/down/top/bottom) | butuh WebView mounted |
| `browser_type` | Ketik ke form field (CSS selector) | butuh WebView; via JS |
| `browser_get_images` | Daftar gambar halaman saat ini | refetch URL saat ini |

### 2.3 Terminal & Proses
| Tool | Fungsi | Catatan |
|---|---|---|
| `terminal` | Jalankan shell command (foreground/background) | **Butuh persetujuan user**; timeout 180s |
| `process` | Kontrol proses background (list/poll/log/wait/kill/write/close) | Registry per-agent, max 32 sesi |

### 2.4 File (sandboxed)
| Tool | Fungsi | Catatan |
|---|---|---|
| `read_file` | Baca file | Path traversal protection; sandbox dir |
| `write_file` | Tulis file | sandbox + `extra_dirs` workspace |
| `patch` | Patch baris dalam file | sandbox |
| `list_files` | Daftar file di direktori | sandbox |
| `search_files` | Cari teks dalam file | sandbox |

### 2.5 Code & Kalkulasi
| Tool | Fungsi | Catatan |
|---|---|---|
| `execute_code` | Jalankan Python di **subproses terpisah** | ⚠️ Bukan sandbox keamanan — hak setara app. Pakai interpreter app (`sys.executable`) |
| `calculate` | Evaluasi ekspresi matematika | **AST-based, tanpa `eval()`** — aman |
| `get_time` | Waktu sekarang (ISO) | — |

### 2.6 Kecerdasan Agent (memory/session)
| Tool | Fungsi | Catatan |
|---|---|---|
| `session_search` | Cari sesi percakapan lampau | Kini mengembalikan `summary` + snippet terbaik |
| `memory` | store/retrieve/search/list/delete (KV) | backend `kv_memory` + `memory_entries` |
| `clarify` | Saran pertanyaan klarifikasi | statis (tidak interaktif) |
| `todo` | Task list sederhana (add/update/remove/list) | JSON store |

### 2.7 Skills
| Tool | Fungsi |
|---|---|
| `skills_list` | Daftar skill terpasang |
| `skill_view` | Lihat metadata + schema skill |
| `skill_manage` | enable/disable/remove/install skill (dari URL) |

### 2.8 Cron
| Tool | Fungsi |
|---|---|
| `cronjob` | list/create/delete/run/pause/resume job | **`create` + `delete` baru** — termasuk oneshot `run_at` |

### 2.9 Kanban
| Tool | Fungsi |
|---|---|
| `kanban_list` / `kanban_create` / `kanban_show` | Lihat/buat/detail task |
| `kanban_move` / `kanban_complete` | Pindah kolom / selesai |
| `kanban_block` / `kanban_unblock` | Blokir / buka blokir |
| `kanban_comment` | Tambah komentar |

Backend: JSON board file (`_board_file()`), lock via `_save_board`.

### 2.10 Proyek (workspace)
| Tool | Fungsi |
|---|---|
| `project_list` | Daftar project/workspace |
| `project_create` | Buat project baru |
| `project_switch` | Aktifkan workspace → perluas sandbox file |

### 2.11 Media & Vision
| Tool | Fungsi | Catatan |
|---|---|---|
| `vision_analyze` | Analisis gambar via model vision aktif | butuh client + provider vision |
| `image_generate` | Generate gambar via endpoint provider | butuh provider mendukung |

### 2.12 Delegasi (subagent)
| Tool | Fungsi | Catatan |
|---|---|---|
| `delegate_task` | Subagent tunggal untuk satu tugas | max 1 |
| `delegate_tasks` | Subagent paralel (max 3, timeout 60s) | child agent meng-*block* `delegate_*`, `clarify`, `cronjob`, `memory` |

---

## 3. 19 Tool Taksonomi TANPA Handler (tidak dikirim ke model)

| Toolset | Tool mati | Status |
|---|---|---|
| `x_search` | `x_search` | ❌ belum ada backend X/Twitter |
| `browser` | `browser_press`, `browser_vision`, `browser_console`, `browser_cdp`, `browser_dialog` | ❌ sebagian butuh CDP (desktop-only) |
| `video` / `video_gen` | `video_analyze`, `video_generate` | ❌ belum ada pipeline video |
| `speech` | `text_to_speech` | ❌ belum ada TTS on-device |
| `smart_home` | `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service` | ❌ belum ada client Home Assistant |
| `computer_use` | `computer_use` | ❌ butuh driver CUA (desktop-only) |
| `kanban` | `kanban_heartbeat`, `kanban_link`, `kanban_attach`, `kanban_attach_url`, `kanban_attachments` | ⚠️ multi-agent link/attach belum |

UI Tools view menampilkan toolset ini sebagai "x/y implementable" + teks "n tools have no
implementation in this build".

---

## 4. 28 Toolsets — Kondisi Nyata

| Toolset | Tools aktif | Mati | Status |
|---|---|---|---|
| `web` | web_search, web_extract | — | ✅ penuh |
| `search` | web_search | — | ✅ penuh |
| `x_search` | — | x_search | ❌ mati total |
| `vision` | vision_analyze | — | ✅ penuh |
| `video` | — | video_analyze | ❌ mati total |
| `image_gen` | image_generate | — | ✅ penuh |
| `video_gen` | — | video_generate | ❌ mati total |
| `terminal` | terminal, process | — | ✅ penuh |
| `file` | read_file, write_file, patch, search_files | — | ✅ penuh (list_files bonus) |
| `browser` | navigate, snapshot, click, type, scroll, back, get_images (+ current_page) | press, vision, console, cdp, dialog | ⚠️ 8/13 |
| `browser_lite` | subset browser | — | ✅ (subset) |
| `skills` | skills_list, skill_view, skill_manage | — | ✅ penuh |
| `planning` | todo, memory | — | ✅ penuh |
| `speech` | — | text_to_speech | ❌ mati total |
| `code` | execute_code, delegate_task | — | ✅ penuh |
| `cron` | cronjob | — | ✅ penuh |
| `smart_home` | — | ha_* (4) | ❌ mati total |
| `kanban` | list, create, show, move, complete, block, unblock, comment | heartbeat, link, attach, attach_url, attachments | ⚠️ 8/13 |
| `computer_use` | — | computer_use | ❌ mati total |
| `session` | session_search | — | ✅ penuh |
| `clarify` | clarify | — | ✅ penuh |
| `research` | komposit: web+browser+vision+planning | — | ✅ (komposit) |
| `development` | komposit: terminal+file+code+browser_lite+web | — | ✅ (komposit) |
| `creative` | komposit: image_gen+vision+web | — | ✅ (komposit) |
| `automation` | komposit: terminal+file+browser+computer_use+cron+smart_home | computer_use, ha_* | ⚠️ sebagian |
| `safe` | komposit besar | speech, smart_home, kanban ekstra | ⚠️ sebagian |
| `minimal` | komposit: search | — | ✅ |
| `full_stack` | komposit semua | banyak | ⚠️ sebagian |

**Ringkas:** 14 toolset penuh, 7 komposit (sebagian besar penuh), 4 mati total
(`x_search`, `video`, `video_gen`, `speech`, `smart_home`, `computer_use`), 2 sebagian
(`browser`, `kanban`).

---

## 5. Gating & Keamanan

1. **Approval user** — `terminal` & `process` tidak pernah jalan tanpa persetujuan
   (bila `approval_callback` terpasang); ditolak → `PermissionError` → tool hasil
   "not approved", tidak ada yang dieksekusi.
2. **Blocked tools** — subagent mem-block `delegate_*`, `clarify`, `cronjob`, `memory`
   agar tidak rekursif/menyimpang dari tujuan delegasi.
3. **SSRF guard** — semua fetch (web_extract, browser navigate) memvalidasi host per hop;
   loopback/private/link-local ditolak.
4. **Path security** — file tools memakai `validate_and_resolve_path` (anti traversal) +
   sandbox allowed-dir (bisa diperluas saat workspace aktif).
5. **Safe eval** — `calculate` memakai AST, bukan `eval()`.
6. **`execute_code` bukan sandbox** — subproses dengan hak setara app; dokumentasi sudah
   menyatakannya. Ini risiko nyata di perangkat user — perlu disadari.
7. **Proses background** — registry per-agent (max 32, retention 300s), tidak bocor antar
   sesi.

---

## 6. Sistem Pendukung (bukan tool model)

| Sistem | Status |
|---|---|
| **Skills** | `skills/manager.py` — file/package Python + `skill.yaml` (JSON-schema args), hot-reload, `skill_memory` sendiri |
| **Plugins** | `plugins/__init__.py` — ABC registry; `AchievementsPlugin`, `KanbanPlugin`, `SecurityGuidancePlugin` bawaan; discovery otomatis |
| **Delegation** | `core/delegation.py` — subagent via provider aktif, web_search saja untuk child, max 3 paralel |
| **Cron** | JSON `jobs.json` + ticker 60s, output JSONL di `cron/output/` |
| **Gateway** | Telegram adapter + pairing code (bukan tool model) |

---

## 7. Temuan & Rekomendasi

### Prioritas tinggi (dampak user nyata)
1. **`browser_press`** (Enter/Escape/Tab) — WebView engine sudah punya `press_key()` di
   `webview_engine.py`, tinggal expose tool. Sering dibutuhkan untuk form login.
2. **`kanban_heartbeat`** — kecil; sinkronisasi multi-agent akan butuh ini.
3. **`x_search`** — hanya bila ada rencana integrasi X API; jangan sekarang (footprint ladder).

### Prioritas sedang
4. **`video_analyze`/`video_generate`/`text_to_speech`** — butuh pipeline media on-device;
   tunda sampai kebutuhan terbukti (footprint ladder: extend → skill → plugin → tool).
5. **`smart_home`** — Home Assistant client; bisa jadi plugin/skill dulu, bukan core tool.

### Tidak disarankan
6. **`browser_cdp`/`computer_use`** — desktop-only (CDP, CUA driver); bertentangan dengan
   prinsip mobile-first. Jangan dipaksa di APK.

### Catatan desain
- Setiap tool baru = +1 schema di **setiap** API call (biaya token). Gunakan footprint
  ladder: extend existing → skill → plugin → adapter → core tool.
- UI Tools view sudah benar: tool mati tidak pernah dikirim ke model. Pertahankan.
