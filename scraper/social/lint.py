"""Linter caption Instagram (adaptasi caption.py dari instagram-agent-skill, MIT) untuk caption Bahasa Indonesia.

Mengecek hal yang menentukan apakah caption "berhenti di-scroll": apa yang terlihat sebelum "... selengkapnya"
(±125 karakter), jumlah hashtag (maks. 5 sejak Des 2025), satu ajakan interaksi, link mati, emoji berlebihan,
dan karakter tak terlihat. Dipakai oleh `python -m scraper.social lint` dan `preview`.
"""
import re
import textwrap

from .captions import IG_MAX, IG_MAX_TAGS, _INVISIBLE

TRUNCATE = 125
HASHTAG_RE = re.compile(r"(?:^|\s)(#\w+)")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
CONCRETE_RE = re.compile(r"\d|(?<!^)\b[A-Z][a-zA-Z]{2,}\b", re.MULTILINE)
ASKS = [
    (re.compile(r"(?i)\b(?:tulis|sampaikan|jawab)\b[^.\n]{0,40}\bkomentar\b|\bkomen(?:tar)?\s+(?:di bawah|ya)\b"),
     "komentar"),
    (re.compile(r"(?i)\bsimpan\b[^.\n]{0,12}\b(?:postingan|post|rekap|ini)\b|\bsave\s+(?:this|post)"), "simpan"),
    (re.compile(r"(?i)\b(?:bagikan|share)\b[^.\n]{0,20}\bke\s+teman"), "bagikan"),
    (re.compile(r"(?i)\btag\s+teman"), "tag teman"),
    (re.compile(r"(?i)\bfollow\b|\bikuti\b"), "follow"),
]
FILLER_TAGS = {"#viral", "#fyp", "#explore", "#explorepage", "#foryou", "#foryoupage", "#trending", "#instagood",
               "#follow", "#like4like", "#reels", "#reelsinstagram", "#viralreels", "#instadaily", "#fypシ"}


def analyse(text, platform="instagram", cut=TRUNCATE):
    text = (text or "").strip()
    first = text.split("\n", 1)[0].strip()
    window = text[:cut]
    tags = HASHTAG_RE.findall(text)
    links = LINK_RE.findall(text)
    asks = [name for rx, name in ASKS if rx.search(text)]
    filler = [t for t in tags if t.lower() in FILLER_TAGS]
    emoji = EMOJI_RE.findall(text)
    checks = []

    def add(name, status, detail):
        checks.append((status, name, detail))

    add("PANJANG", "FAIL" if len(text) > IG_MAX else "PASS", f"{len(text)} / {IG_MAX} karakter")
    if not first:
        add("BARIS PERTAMA", "FAIL", "caption diawali baris kosong")
    elif first.startswith(("#", "@")):
        add("BARIS PERTAMA", "FAIL", "diawali hashtag/mention: posisi paling berharga terbuang")
    elif len(first) > cut:
        add("BARIS PERTAMA", "WARN", f"{len(first)} karakter, terpotong di {cut}")
    else:
        add("BARIS PERTAMA", "PASS", f"{len(first)} karakter, tampil utuh")
    add("HOOK KONKRET", "PASS" if CONCRETE_RE.search(window) else "WARN",
        "ada angka/nama di bagian yang terlihat" if CONCRETE_RE.search(window)
        else "tidak ada angka/nama sebelum dipotong")
    if len(tags) > IG_MAX_TAGS:
        add("HASHTAG", "FAIL", f"{len(tags)} tag, batas IG {IG_MAX_TAGS}: tag ke-{IG_MAX_TAGS + 1} dst. tidak dihitung")
    elif filler:
        add("HASHTAG", "WARN", f"tag generik tidak menjelaskan apa-apa: {' '.join(filler)}")
    else:
        add("HASHTAG", "PASS", f"{len(tags)} tag" + (f": {' '.join(tags)}" if tags else ""))
    if any(t in window for t in tags):
        add("POSISI TAG", "WARN", "hashtag masuk area yang terlihat sebelum dipotong")
    if platform == "instagram" and links:
        add("LINK", "WARN", f"{len(links)} link di caption IG tidak bisa diklik: pindah ke bio")
    if len(asks) == 1:
        add("SATU AJAKAN", "PASS", asks[0])
    elif not asks:
        add("SATU AJAKAN", "WARN", "tidak ada ajakan komentar/simpan/bagikan")
    else:
        add("SATU AJAKAN", "WARN", f"{len(asks)} ajakan ({', '.join(asks)}): dua ajakan sama dengan tidak ada")
    density = len(emoji) * 100 / max(len(text), 1)
    add("EMOJI", "WARN" if density > 4 else "PASS", f"{len(emoji)} emoji, {density:.1f} per 100 karakter")
    invisible = len(_INVISIBLE.findall(text))
    add("KARAKTER TAK TERLIHAT", "FAIL" if invisible else "PASS", f"{invisible} ditemukan")

    fails = sum(c[0] == "FAIL" for c in checks)
    warns = sum(c[0] == "WARN" for c in checks)
    return {"visible": window, "truncated": len(text) > cut, "checks": checks,
            "verdict": "PERBAIKI" if fails else "TINJAU" if warns else "SIAP"}


def render(result, width=52):
    out = ["  YANG TERLIHAT DI FEED", "  +" + "-" * (width + 2) + "+"]
    lines = []
    for raw in result["visible"].split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    out += [f"  | {line:<{width}} |" for line in lines[:8]]
    tail = "... selengkapnya" if result["truncated"] else "(muat semua)"
    out.append("  +" + "-" * (width - len(tail)) + f" {tail} " + "+")
    out += [f"  {s:<5} {n:<22} {d}" for s, n, d in result["checks"]]
    out.append(f"  HASIL  {result['verdict']}")
    return "\n".join(out)
