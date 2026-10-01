# FORK-NOTES — `diluviumm/hermes-agent`

> **Catatan fork aktif** — ini fork `NousResearch/hermes-agent` yang dipakai sebagai
> *mirror sinkron* + pangkalan kontribusi untuk satu instalasi Hermes pribadi.
> Dokumen ini MILIK FORK (commit di `main`) dan sengaja dijaga agar sinkronisasi
> upstream tetap aman. Panduan operator lengkap ada di bawah — `tata cara` ada di §8.

---

## 1. Status ringkas (per 1 Okt 2026)

| Item | Nilai |
|---|---|
| Fork | `diluviumm/hermes-agent` ← `NousResearch/hermes-agent` (public, MIT) |
| Sinkronisasi | `main` di-ff/merge otomatis tiap hari **05:20** (cron `hermes-agent-fork-sync`) |
| Branch milik fork | `FORK-NOTES.md` (file ini), cabang PR (`fix/*`, `feat/*`) |
| CI di fork | **Dimatikan** (semua 52 workflow `disabled_manually`) — lihat §7 |

**PR terbuka ke upstream:**

| PR | Judul | Status |
|---|---|---|
| [#124474](https://github.com/NousResearch/hermes-agent/pull/124474) | `fix(plugins): skip .muse-plugin foreign-harness manifests like its siblings` | OPEN · MERGEABLE |
| [#129938](https://github.com/NousResearch/hermes-agent/pull/129938) | `fix(tui): fall back to case/whitespace-insensitive session title lookup` | OPEN · MERGEABLE |
| [#129940](https://github.com/NousResearch/hermes-agent/pull/129940) | `feat(whatsapp): forward owner-typed messages from allowlisted groups (opt-in)` | OPEN · MERGEABLE |

Status PR dipantau harian 10:00 oleh cron `fork-pr-monitor` (change-gated → notifikasi
WhatsApp **hanya** saat ada perubahan).

---

## 2. Dua salinan lokal — peran berbeda, JANGAN tertukar

| | `~/.hermes/hermes-agent` | `~/me/hermes-agent` |
|---|---|---|
| Peran | **Runtime** — yang dijalankan Hermes (`pip install -e`) | **Clone fork** — sync upstream, kerja PR |
| Remote | origin = `NousResearch/hermes-agent` | origin = `diluviumm/hermes-agent`, upstream = `NousResearch` |
| Isi working-tree | **2 patch lokal** (lihat §4) — dijaga guard | Bersih / cabang PR |
| Disentuh otomatis? | `hermes-tarball-sync` 05:30 | `hermes-agent-fork-sync` 05:20 |
| Rollback | `hermes-restore-preupdate.sh` (§9) | `git reset --hard origin/main` |

---

## 3. Pipeline update (alur resmi)

```
                 ┌────────────────────────────────────────────────────┐
                 │ upstream NousResearch/hermes-agent (main)          │
                 └───────────────┬────────────────────────────────────┘
                                 │ codeload tarball (git fetch terblokir DPI)
        05:30 tiap hari          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ hermes-tarball-sync.sh                                                       │
│  1. backup config.yaml + source → ~/.hermes/backups/                         │
│     hermes-agent-src-preupdate.tar.gz (+ .sha)   ← PERSISTEN, awet reboot    │
│  2. unduh tarball (3 percobaan)  3. rsync (protect .git/venv/.env)           │
│  4. git reset --hard origin/main (bila jaringan)  5. pip install -e          │
│  6. hermes-patch-guard.sh → PATCH-GUARD-OK?  →  sukses/gagal + log           │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │ guard menulis ULANG 2 patch lokal bila hilang
                               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Runtime patched: bridge.js (WA group-owner) + methods_session.py (resume)    │
└──────────────────────────────────────────────────────────────────────────────┘

        05:20 tiap hari (terpisah)
┌──────────────────────────────────────────────────────────────────────────────┐
│ hermes-agent-fork-sync.sh → fetch upstream (SSH, timeout 90) → fork main:    │
│   behind>0 & ahead=0 → ff-only · ahead>0 → merge --no-edit (fork SELAMAT)     │
│   konflik → ABORT + errors.log (tak pernah memaksa) · push origin             │
│   behind=0 & main ≠ origin/main → DORONG commit lokal (push gap tertutup)     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Patch lokal runtime (2) & cara kerja auto-heal

| Patch | File | Fungsi | Skrip apply |
|---|---|---|---|
| `HERMES-PATCH-WA-GROUP-OWNER` | `scripts/whatsapp-bridge/bridge.js` | Pesan owner **di grup** diteruskan (mode `bot` + `WHATSAPP_FORWARD_OWNER_MESSAGES` + gate allowlist grup) — sebelumnya semua `fromMe` di grup dibuang. Echo `/send` tetap terpotong oleh cek `agent_echo` (anti-loop). | `apply-whatsapp-group-fix.py` (menerima path target opsional untuk uji di copy) |
| `_session_by_title` fallback | `tui_gateway/methods_session.py` | `/resume <judul>` & `session.list {title}` match case/spasi-insensitif setelah exact-match miss (dulu 4007). | `apply-resume-title-fallback.py` |

**Jaring pengaman (4 lapis, semuanya terjadwal):**

| Lapis | Mekanisme | Jadwal |
|---|---|---|
| 1 | `hermes-tarball-sync` memanggil `hermes-patch-guard.sh` tepat setelah update | 05:30 harian |
| 2 | `cron-selfheal.sh` memanggil `hermes-patch-guard.sh` | tiap 30 menit |
| 3 | `rules-guard.sh` memanggil `hermes-patch-guard.sh` | tiap jam (`:00`) |
| 4 | `verify-local-patches.sh` — detektor independen (8 cek patch + 5 cek otomasi/backup/dok, exit 1 → alert WhatsApp) | 04:45 harian |

Bukti uji (1 Okt 2026): file pristine `git show HEAD:` → kedua skrip apply → **byte-identical**
dengan file live → run ulang = no-op idempoten. Artinya skrip apply terbukti memulihkan
patch dari nol persis seperti yang terjadi saat update.

---

## 5. Otomasi terkait fork (cron `~/.hermes/cron/jobs.json`)

| Job | ID | Jadwal | Fungsi |
|---|---|---|---|
| `hermes-agent-fork-sync` | `a6e2bff1d755` | `20 5 * * *` | ff/merge fork main ← upstream, push (script: `hermes-agent-fork-sync.sh`) |
| `hermes-tarball-sync` | `1542acd1ca6f` | `30 5 * * *` | Update runtime via tarball (script: `hermes-tarball-sync.sh`) |
| `hermes-local-patch-guard` | `d455f4d42376` | `45 4 * * *` | `verify-local-patches.sh` → alert jika ada yang hilang |
| `fork-pr-monitor` | `aa72379429a4` | `0 10 * * *` | Monitor status 3 PR (change-gated; `fork-pr-monitor.sh`) |
| `fork-npm-audit` | `f50a79bd9388` | `0 6 1 * *` | Audit dependensi JS fork (change-gated; `fork-npm-audit.sh`) |
| `fork-freshness-sync` | `c867ba3aceb8` | `15 4 */2 * *` | Kesegaran semua fork (script: `fork-freshness.sh`) |
| `cron-selfheal` / `rules-guard` | — | 30m / tiap jam | Bawaan guard patch runtime (lihat §4) |

---

## 6. Tata cara penggunaan (how-to operator)

**A. Cek kesehatan semua (sekali jalan):**
```bash
bash ~/.hermes/scripts/verify-local-patches.sh        # 13 cek; rc=0 = sehat
bash ~/.hermes/scripts/hermes-patch-guard.sh          # guard patch runtime
```

**B. Sinkronkan fork sekarang juga (jangan tunggu cron):**
```bash
bash ~/.hermes/scripts/hermes-agent-fork-sync.sh      # ff/merge + push; senyap bila sudah sinkron
```

**C. Update runtime di luar jadwal:**
```bash
bash ~/.hermes/scripts/hermes-tarball-sync.sh         # auto-backup dulu, patch-guard di akhir
# Setelah update sukses: restart gateway via SHELL (dilarang di cron — policy #30719)
```

**D. ROLLBACK bila update rusak:**
```bash
bash ~/.hermes/scripts/hermes-restore-preupdate.sh --dry-run   # validasi dulu (tanpa menyentuh apa pun)
bash ~/.hermes/scripts/hermes-restore-preupdate.sh             # eksekusi:
#  snapshot mundur → rsync balik dari backup → git reset ke .sha backup
#  → pip install -e → patch-guard re-apply patch → lapor OK
```

**E. Menambah patch lokal BARU (resep aman):**
1. Ubah file di `~/.hermes/hermes-agent` (runtime).
2. Buat skrip apply idempoten di `~/.hermes/scripts/apply-<nama>.py`
   (pattern: deteksi MARKER → sudah terpasang = no-op; anchor tidak cocok = gagal jujur,
   jangan pernah menulis file kalau pola tidak persis).
3. Daftarkan ke `hermes-patch-guard.sh` (fungsi `apply_source_patches` + check baru).
4. Tambahkan cek pola di `verify-local-patches.sh`.
5. Uji: `git show HEAD:<file>` ke scratch → jalankan apply → bandingkan byte-identik.

**F. Mengirim PR baru ke upstream:**
```bash
cd ~/me/hermes-agent && git fetch upstream && git checkout -b <tipe>/<slug> upstream/main
# kerja + tambah tes → commit (Conventional Commits, gitleaks jalan otomatis)
git push -u origin <tipe>/<slug>
gh pr create --repo NousResearch/hermes-agent --head "diluviumm:<tipe>/<slug>" \
  --base main --title "<scope>: <subjek>" --body-file <file-template>
```
Wajib: baca `CONTRIBUTING.md` + `AGENTS.md` repo, **search duplikat dulu**
(`gh search prs --repo NousResearch/hermes-agent "<kata kunci>"`), pakai template PR,
tes di area dampak. Checklist `pytest tests/ -q` penuh = milik CI.

**G. Menyalakan kembali CI fork** (untuk percobaan lokal):
```bash
gh api -X POST repos/diluviumm/hermes-agent/actions/workflows/<id>/enable   # per workflow
gh api 'repos/diluviumm/hermes-agent/actions/workflows?per_page=100' --jq '.workflows[].id'  # daftar id
```

**H. Remote & autentikasi (berlaku sejak 1 Okt 2026):**

| Item | Status |
|---|---|
| Protokol remote clone fork | **SSH** — `git@github.com:diluviumm/hermes-agent.git` (origin) + `git@github.com:NousResearch/hermes-agent.git` (upstream). Alasan: fetch/push HTTPS ke GitHub kadang terhambat DPI jaringan; SSH stabil dan tidak butuh kredensial `gh`. |
| Anti-hang | `core.sshCommand = ssh -o BatchMode=yes -o ConnectTimeout=15 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=6` (repo-local; matikan stall setelah koneksi terbuka) + `timeout 90` pada fetch & push di `hermes-agent-fork-sync.sh` → cron tidak pernah menggantung; gagal jaringan = alert, bukan hang. |
| Autentikasi `gh` (dipakai `fork-pr-monitor`, `gh pr create`, dll.) | Token ada di `~/.hermes/.env` (`GITHUB_TOKEN`). Bila suatu saat `gh auth status` bilang belum login (keyring kosong), pulihkan **tanpa pernah mencetak token**: `gh auth login --hostname github.com --git-protocol https --with-token <<< "$(grep '^GITHUB_TOKEN=' ~/.hermes/.env \| cut -d= -f2-)"` |
| Verifikasi | `gh auth status` (harus `✓ Logged in … diluviumm`) · `git ls-remote origin main` (harus keluar hash, ±3 detik) |

---

## 7. Keputusan konfigurasi di fork ini

| Keputusan | Alasan |
|---|---|
| **52 GitHub Actions workflow DIMATIKAN** (`disabled_manually`) | Tiap push sinkronisasi memicu CI penuh upstream (Docker build, Nix, auto-fix — 3 run sempat gagal) dan run terjadwal yang tidak relevan untuk mirror. Fork tidak punya kode sendiri selain dokumentasi. Repo-level API 404 (scope token) → dimatikan per-workflow. Re-enable: lihat §6-G. |
| `FORK-NOTES.md` = **satu-satunya file yang di-commit ke `main`** | Dokumentasi harus terlihat di halaman GitHub fork. Sinkron tetap aman karena sync script kini `merge --no-edit` (bukan ff-only) dan konflik → abort + lapor. File lain jangan ditambahkan ke `main` tanpa memperbarui daftar ini di header `hermes-agent-fork-sync.sh`. |
| Backup update **persisten**, bukan `/tmp` | `/tmp` mati saat reboot (insiden 1 Okt: backup hilang). Kini satu slot di `~/.hermes/backups/` + `.sha`. |
| npm audit **tidak di-mass-fix di fork** | 10-11 vuln = warisan upstream; memperbaikinya di fork membuat diff sinkronisasi melebar. Jalur benar: PR ke upstream. Dipantau bulanan oleh `fork-npm-audit`. |

---

## 8. Riwayat insiden (pelajaran)

| Tanggal | Insiden | Perbaikan permanen |
|---|---|---|
| 29 Sep 2026 | Audit menemukan fork tertinggal **1.589 commit** — tidak ada otomasi sync sama sekali | `hermes-agent-fork-sync` (cron harian) |
| 1 Okt 2026 | Update `46bcd94 → 12e4d3e2` men-stash **929 perubahan lokal** tak kembali; **2 patch source hilang**, backup `/tmp` tak andal, HEAD tak sejajar (4019 file "modified" palsu) | Skrip apply idempoten + guard 4 lapis (§4) · backup persisten + `.sha` (§9) · `verify-local-patches.sh` |
| 1 Okt 2026 | Fork kalah 19 commit saat jam kerja; CI fork menembak tiap push | Sync + guard `STALE` 27 jam · CI fork dimatikan (§7) |

---

## 9. Peta file penting

```
~/.hermes/scripts/
├── hermes-tarball-sync.sh        # update runtime (backup → tarball → rsync → guard)
├── hermes-restore-preupdate.sh   # ROLLBACK (--dry-run untuk cek)
├── hermes-agent-fork-sync.sh     # sync fork (ff/merge + push)
├── hermes-patch-guard.sh         # tulis-ulang + verifikasi patch (panggilan: tarball/selfheal/rules)
├── verify-local-patches.sh       # detektor 13 cek (cron 04:45, alert WA)
├── apply-whatsapp-group-fix.py   # apply patch WA (argv[1] = target scratch)
├── apply-resume-title-fallback.py# apply patch resume
├── fork-pr-monitor.sh            # monitor PR (deterministik)
└── fork-npm-audit.sh             # audit npm fork (deterministik)

~/.hermes/backups/
├── hermes-agent-src-preupdate.tar.gz      # snapshot source pre-update (1 slot)
├── hermes-agent-src-preupdate.tar.gz.sha  # HEAD saat backup (untuk reset)
└── config/config.yaml.sync-<ts>           # backup config tiap update
```

Log: `~/.hermes/logs/tarball-sync.log` · `~/.hermes/logs/restore-preupdate.log` ·
`~/.hermes/logs/errors.log` (grep `cron-hermes-agent-fork-sync` / `MERGE KONFLIK`).
