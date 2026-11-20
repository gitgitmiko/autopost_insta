# Skill Instagram (/ig-*)

Diambil dari https://github.com/Jakeschincariol/instagram-agent-skill
(commit d03c56b, lisensi MIT: `LICENSE-instagram-agent-skill`). Hanya skill yang relevan untuk
akun berita otomatis yang dipasang:

| Skill | Dipakai untuk |
|---|---|
| `/ig-caption` | cek caption hasil pipeline (`caption.py`); aturannya sudah diterapkan di `scraper/social/captions.py` |
| `/ig-human` | bersihkan teks (karakter tak terlihat, slop); pass karakter tak terlihat sudah otomatis di pipeline |
| `/ig-reel`, `/ig-carousel` | rancangan kartu/Reel: hook, safe zone, struktur slide |
| `/ig-viral` | riset reel yang sedang ramai di niche (rangking kelipatan views vs median akun) |
| `/ig-audit` | evaluasi post yang sudah tayang (outlier multiple, sends per reach) |
| `/ig-plan`, `/ig-profile` | rencana mingguan & skor profil/bio |

Tidak dipasang: `/ig-dm`, `/ig-story`, `/ig-comment`, `/ig-reply`, `/ig-repurpose` (kerja manual
interaksi, tidak cocok untuk akun otomatis).

Profil gaya bahasa yang dibaca semua skill: `~/.claude/instagram/voice.md`.
Perintah proyek yang mengadaptasi skill ini:

- `.venv/bin/python -m scraper.social lint <file|->`: linter caption Bahasa Indonesia (/ig-caption)
- `.venv/bin/python -m scraper.social audit --account game [--days 30]`: post terbaik/terlemah & pola per jam,
  jenis, format, sumber, hari, CTA (/ig-audit) → `data/reports/audit-*.md`
- `.venv/bin/python -m scraper.social viral --account game`: rangking post akun pesaing (`competitors` di
  social_accounts.json) → `data/reports/swipe-*.md`, lalu `/ig-viral` untuk menamai formula hook

`audit` memakai views/reach/saves/shares bila token punya izin `instagram_manage_insights`; tanpa izin itu
memakai like + komentar. `viral` wajib izin tersebut (business_discovery).
