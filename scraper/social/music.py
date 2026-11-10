"""Lagu latar sesuai suasana berita: pilih suasana, pilih lagu, render video berlagu (ffmpeg).

Instagram API tidak bisa memasang lagu dari pustaka musik Instagram, jadi lagu ditanam langsung ke MP4:
postingan Instagram jadi Reel 9:16 (kartu berganti + lagu), atau — untuk jenis konten di `feed_kinds` akun —
carousel feed biasa yang tiap slidenya video 4:5 diam + potongan lagu bersambung (carousel_videos()).
Lagu: Kevin MacLeod (incompetech.com), CC BY 4.0 — kredit wajib dicantumkan di caption (credit()).
"""
import json
import logging
import os
import random
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from . import settings

log = logging.getLogger(__name__)
MUSIC_DIR = os.path.join(settings.ROOT, "assets", "music")
MOODS = ("seru", "senang", "tenang", "sedih", "tegang")
FPS = 30
SINGLE_SECONDS = 15  # Reel satu kartu (rekap, berita tanpa slide tambahan)
COVER_SECONDS = 5  # cover berita (judul saja) sebelum slide isi
STEAM_SLIDE_SECONDS = 5  # tiap kartu promo Steam
VIDEO_MAX_SECONDS = 10  # potongan video artikel di Reel
FADE = 0.6  # transisi antar kartu di Reel
CAROUSEL_SECONDS = 15  # tiap slide gambar di carousel berlagu (Instagram mengulang video slide)

# Kata pemicu suasana (judul berbobot 2, awal isi berbobot 1). Huruf kecil, dicocokkan per kata (+ akhiran -nya/-kan).
# Sengaja tanpa "leak"/"bocor": di berita game itu bocoran yang ditunggu, bukan kabar menegangkan.
WORDS = {
    "sedih": ["meninggal", "meninggal dunia", "tewas", "wafat", "berpulang", "duka", "berduka", "dukacita",
              "korban jiwa", "bencana", "gempa", "banjir", "tsunami", "kebakaran", "kecelakaan", "tragedi",
              "tragis", "phk", "pemutusan hubungan kerja", "dirumahkan", "tutup permanen", "gulung tikar",
              "pensiun dari", "perpisahan", "selamat tinggal", "dihentikan", "dibatalkan",
              # bukan "dead"/"death"/"ditutup": judul game (Dead Space) & "IHSG ditutup menguat"
              "died", "dies", "passed away", "tragedy", "tragic", "mourn", "mourning",
              "layoff", "layoffs", "laid off", "shut down", "shuts down", "shutting down", "closure",
              "discontinued", "cancelled", "canceled", "farewell", "end of service", "sunset", "goodbye"],
    "tegang": ["konflik", "perang", "serangan", "menyerang", "demo", "demonstrasi", "unjuk rasa", "ricuh",
               "bentrok", "rusuh", "protes", "kecam", "mengecam", "polemik", "kontroversi", "skandal", "korupsi",
               "suap", "ditangkap", "tersangka", "ott", "kpk", "diperiksa", "digugat", "gugatan", "sanksi",
               "larangan", "dilarang", "diblokir", "ancaman", "mengancam", "krisis", "darurat", "memanas",
               "diretas", "peretasan", "kebocoran data", "penipuan", "anjlok", "ambruk", "rontok", "crash",
               "war", "attack", "attacks", "protest", "protests", "controversy", "backlash", "scandal",
               "lawsuit", "sued", "banned", "ban", "crackdown", "arrested", "hacked", "breach",
               "threat", "crisis", "plunge", "plunges", "tumble", "sell-off", "selloff"],
    "seru": ["rilis", "meluncur", "diluncurkan", "trailer", "teaser", "gameplay", "diumumkan", "resmi hadir",
             "gratis", "diskon", "promo", "juara", "menang", "kemenangan", "turnamen", "final", "grand final",
             "update", "patch", "event", "season", "hero baru", "agent baru", "map baru", "mode baru",
             "release", "released", "launch", "launches", "reveal", "revealed", "announced", "free", "sale",
             "champion", "champions", "wins", "victory", "tournament", "new hero", "new agent", "new map",
             "new season", "showcase", "early access", "beta"],
    "senang": ["rekor", "sukses", "berhasil", "penghargaan", "hadiah", "bonus", "terlaris", "laris", "terpopuler",
               "menguat", "melonjak", "meroket", "cuan", "optimis", "pulih",
               "membaik", "bantuan", "beasiswa", "apresiasi", "dukungan", "kolaborasi", "kerja sama",
               "record", "success", "award", "awards", "best-selling", "bestselling", "surge", "soar", "rally",
               "gain", "gains", "recovery", "milestone", "celebrate", "celebrates"],
}
_PATTERNS = {m: re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True))
                           + r")(?:nya|kan|lah)?(?![\w-])", re.IGNORECASE) for m, ws in WORDS.items()}
# suasana bawaan bila tidak ada kata pemicu
DEFAULT = {"game": "seru", "politik": "tenang", "saham": "tenang", "crypto": "tenang"}


@dataclass
class Track:
    title: str
    file: str  # relatif ke MUSIC_DIR
    mood: str

    @property
    def path(self):
        return os.path.join(MUSIC_DIR, self.file)


@lru_cache(maxsize=1)
def _library():
    try:
        with open(os.path.join(MUSIC_DIR, "tracks.json")) as f:
            tracks = [Track(**t) for t in json.load(f)["tracks"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("pustaka lagu tidak terbaca: %s", e)
        return {}
    lib = {}
    for t in tracks:
        if os.path.exists(t.path):
            lib.setdefault(t.mood, []).append(t)
    return lib


def _scores(text, weight):
    return {m: weight * len(p.findall(text or "")) for m, p in _PATTERNS.items()}


def news_mood(item):
    """Suasana berita dari kata pemicu di judul/awal isi + sentimen pasar (saham/crypto)."""
    a = item.article
    s = dict.fromkeys(MOODS, 0)
    for text, weight in ((a.title, 2), ((item.body or "")[:500], 1)):
        for m, v in _scores(text, weight).items():
            s[m] += v
    sent = item.sentiment
    if a.category in ("saham", "crypto") and sent and sent.method != "skipped":
        # berita pasar: turun = tegang (bukan sedih), naik = senang
        s["senang" if sent.label == "positif" else "tegang" if sent.label == "negatif" else "tenang"] += 2
    if a.category != "game":
        s["seru"] = 0  # lagu hype khusus game ("rilis"/"update" di berita lain bukan alasan)
    if s["sedih"] >= 2:  # duka mengalahkan semuanya: jangan sampai berita duka dapat lagu ceria
        return "sedih"
    best = max(("tegang", "seru", "senang", "tenang"), key=s.get)
    if s[best] < 2:  # satu kata di isi saja belum cukup (mis. "perang" di berita game Call of Duty)
        return DEFAULT.get(a.category, "tenang")
    if best in ("senang", "tenang") and a.category == "game":
        return "seru"  # kabar baik dunia game → lagu seru
    return best


def market_mood(change_pct):
    return "senang" if change_pct >= 0.5 else "tegang" if change_pct <= -0.5 else "tenang"


def pick(mood, seed):
    """Lagu untuk suasana (bergantian sesuai seed). None bila pustaka kosong."""
    lib = _library()
    tracks = lib.get(mood) or lib.get("tenang") or next(iter(lib.values()), None)
    return random.Random(seed).choice(tracks) if tracks else None


def credit(track):
    return f'🎵 Musik: "{track.title}" — Kevin MacLeod (incompetech.com) · CC BY 4.0' if track else None


# ---------------------------------------------------------------- render
def _ffmpeg(cmd):
    from ..media import FFMPEG
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *cmd], check=True, capture_output=True, text=True,
                   timeout=900)


def _audio_args(track, seconds, index):
    """Lagu diulang bila Reel lebih panjang dari lagunya (lagu di pustaka dipotong 75 detik)."""
    fade_out = max(0.0, seconds - 2.0)
    return (["-stream_loop", "-1", "-i", track.path],
            f"[{index}:a]atrim=0:{seconds:.2f},asetpts=N/SR/TB,afade=t=in:d=0.8,afade=t=out:st={fade_out:.2f}:d=2,"
            "aformat=sample_rates=44100:channel_layouts=stereo[aout]")


_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high", "-level", "4.1",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]


def read_seconds(words, lo=6, hi=14):
    """Lama tampil slide berteks di Reel: ±3 kata/detik + 3 detik untuk melihat gambarnya."""
    return max(lo, min(hi, round(3 + words / 3)))


def reel_video(segments, path, track):
    """Kartu 4:5 → Reel 1080x1920: kartu di tengah, latar kartu yang diburamkan, transisi fade, lagu.

    segments: [(path, detik)] — path .mp4 (slide video artikel) ikut diputar tanpa suara aslinya."""
    n = len(segments)
    total = sum(sec for _, sec in segments) - FADE * (n - 1)
    inputs, parts = [], []
    for i, (p, sec) in enumerate(segments):
        if p.endswith(".mp4"):  # video lebih pendek dari durasinya: bingkai terakhir ditahan
            inputs += ["-t", str(sec), "-i", p]
            src = f"[{i}:v]tpad=stop_mode=clone:stop_duration={sec},trim=duration={sec},setpts=PTS-STARTPTS,"
        else:
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(sec), "-i", p]
            src = f"[{i}:v]"
        parts.append(f"{src}fps={FPS},split[b{i}][f{i}];"
                     f"[b{i}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                     f"boxblur=40:2,eq=brightness=-0.18[bg{i}];"
                     f"[f{i}]scale=1080:1350,setsar=1[fg{i}];"
                     f"[bg{i}][fg{i}]overlay=0:285,setsar=1,format=yuv420p[s{i}]")
    last, offset = "s0", 0.0
    for i in range(1, n):  # rantai xfade: tiap kartu mulai FADE detik sebelum kartu sebelumnya habis
        offset += segments[i - 1][1] - FADE
        out = f"x{i}"
        parts.append(f"[{last}][s{i}]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[{out}]")
        last = out
    a_in, a_filter = _audio_args(track, total, n)
    parts.append(a_filter)
    _ffmpeg([*inputs, *a_in, "-filter_complex", ";".join(parts), "-map", f"[{last}]", "-map", "[aout]",
             "-t", f"{total:.2f}", *_ENC, path])
    return path


def carousel_videos(slides, track, out_path):
    """Carousel feed berlagu: tiap slide jadi MP4 1080x1350 (gambar diam / video artikel tanpa suara aslinya)
    dengan potongan lagu yang bersambung dari slide ke slide. slides: [{"path", "type"}] → list path MP4."""
    from ..media import probe_video
    base, _ = os.path.splitext(out_path)
    base = base[:-2] if base.endswith("-1") else base
    out, start = [], 0.0
    for i, sl in enumerate(slides, start=1):
        p = sl["path"]
        dest = f"{base}-{i}-lagu.mp4"
        if sl["type"] == "video":  # Instagram: video carousel 3–60 detik
            sec = max(3.0, min(60.0, probe_video(p)[2] or CAROUSEL_SECONDS))
            v_in = ["-t", f"{sec:.2f}", "-i", p]
            v_filter = f"[0:v]tpad=stop_mode=clone:stop_duration={sec:.2f},trim=duration={sec:.2f},setpts=PTS-STARTPTS,"
        else:
            sec = CAROUSEL_SECONDS
            v_in = ["-loop", "1", "-framerate", str(FPS), "-t", str(sec), "-i", p]
            v_filter = "[0:v]"
        fade_out = max(0.0, sec - 1.0)
        parts = [f"{v_filter}fps={FPS},scale=1080:1350,setsar=1,format=yuv420p[v]",
                 f"[1:a]atrim={start:.2f}:{start + sec:.2f},asetpts=N/SR/TB,afade=t=in:d=0.5,"
                 f"afade=t=out:st={fade_out:.2f}:d=1,aformat=sample_rates=44100:channel_layouts=stereo[aout]"]
        _ffmpeg([*v_in, "-stream_loop", "-1", "-i", track.path, "-filter_complex", ";".join(parts),
                 "-map", "[v]", "-map", "[aout]", "-t", f"{sec:.2f}", *_ENC, dest])
        out.append(dest)
        start += sec
    return out
