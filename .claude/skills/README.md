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
Linter caption versi proyek (Bahasa Indonesia): `.venv/bin/python -m scraper.social lint <file|->`.
