"""Pengaturan posting media sosial. Akun & jadwal: social_accounts.json. Lingkungan: .env."""
import json
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TZ = ZoneInfo("Asia/Jakarta")
FONT_DIR = os.path.join(ROOT, "assets", "fonts")
OUTBOX_DIR = os.path.join(ROOT, "data", "outbox")
ACCOUNTS_FILE = os.getenv("SOCIAL_ACCOUNTS_FILE", os.path.join(ROOT, "social_accounts.json"))

# Gambar postingan ditulis ke folder yang disajikan nginx "media" milik stack n8n (URL publik untuk Instagram).
N8N_DIR = os.getenv("N8N_PROJECT_DIR", "/home/gitgitmiko/github-repos/n8n")
MEDIA_DIR = os.getenv("SOCIAL_MEDIA_DIR", os.path.join(N8N_DIR, "media", "public", "social"))
MEDIA_BASE_URL = os.getenv("SOCIAL_MEDIA_BASE_URL", "https://media.gitgitmiko.my.id/media/social").rstrip("/")
MEDIA_KEEP_DAYS = int(os.getenv("SOCIAL_MEDIA_KEEP_DAYS", "14"))

# API lokal yang dipanggil workflow n8n. Default: IP gateway jaringan Docker n8n (tidak terbuka ke internet).
API_HOST = os.getenv("SOCIAL_API_HOST", "172.18.0.1")
API_PORT = int(os.getenv("SOCIAL_API_PORT", "8791"))
API_KEY = os.getenv("SOCIAL_API_KEY", "")
API_URL = os.getenv("SOCIAL_API_URL", f"http://{API_HOST}:{API_PORT}")  # alamat API dilihat dari container n8n

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v26.0")
GRAPH_BASE = os.getenv("SOCIAL_GRAPH_BASE", f"https://graph.facebook.com/{GRAPH_VERSION}")

N8N_CONTAINER = os.getenv("N8N_CONTAINER", "n8n-instagram-n8n-1")
N8N_DB_CONTAINER = os.getenv("N8N_DB_CONTAINER", "n8n-instagram-postgres-1")
DOCKER_CMD = os.getenv("DOCKER_CMD", "sudo docker").split()

NEWS_MAX_AGE_HOURS = int(os.getenv("SOCIAL_NEWS_MAX_AGE_HOURS", "18"))
MAX_ATTEMPTS = 3


@dataclass
class Account:
    key: str
    category: str
    enabled: bool = True
    brand_name: str = "Kabar"
    brand_handle: str = ""
    ig_user_id: str = ""
    page_id: str = ""
    facebook: bool = False
    use_article_photo: bool = False
    max_extra_slides: int = 3  # gambar dari isi artikel sebagai slide carousel tambahan (butuh use_article_photo)
    bio_slug: str = ""  # halaman "link di bio": https://media.gitgitmiko.my.id/l/<bio_slug>/
    comment_overflow: bool = False  # isi yang tak muat di caption IG dilanjutkan di komentar (izin instagram_manage_comments)
    music: bool = True  # lagu latar sesuai suasana berita (video slide pertama / Reel) — lihat music.py
    feed_kinds: list = field(default_factory=list)  # jenis konten yang di IG jadi carousel feed berlagu, bukan Reel
    languages: list = field(default_factory=lambda: ["id", "en"])
    hashtags: list = field(default_factory=list)
    schedule: list = field(default_factory=list)  # [{"time": "08:00", "kind": "news"}]

    def slot_at(self, hhmm, tolerance_min=5):
        """Entri jadwal terdekat (±tolerance) dari jam pemicu → dict entri jadwal atau None.

        Entri: {"time": "09:30", "kind": "news", "topic": "valorant" (opsional), "max_age_hours": 48 (opsional)}"""
        h, m = map(int, hhmm.split(":"))
        best = None
        for s in self.schedule:
            sh, sm = map(int, s["time"].split(":"))
            diff = abs((h * 60 + m) - (sh * 60 + sm))
            if diff <= tolerance_min and (best is None or diff < best[0]):
                best = (diff, s)
        return best[1] if best else None

    @property
    def platforms(self):
        return ["instagram"] + (["facebook"] if self.facebook else [])


def _read():
    with open(ACCOUNTS_FILE) as f:
        return json.load(f)


def load_accounts():
    """Dibaca ulang setiap dipanggil, jadi perubahan file langsung berlaku tanpa restart."""
    known = set(Account.__dataclass_fields__)
    return {a["key"]: Account(**{k: v for k, v in a.items() if k in known}) for a in _read()["accounts"]}


def get_account(key):
    accounts = load_accounts()
    if key not in accounts:
        raise KeyError(f"Akun '{key}' tidak ada di {ACCOUNTS_FILE}. Pilihan: {', '.join(accounts)}")
    return accounts[key]


def update_account(key, **values):
    data = _read()
    for a in data["accounts"]:
        if a["key"] == key:
            a.update(values)
            break
    else:
        raise KeyError(key)
    tmp = ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, ACCOUNTS_FILE)


def slot_name(entry):
    """Nama slot unik per jadwal, mis. "09:30-news-valorant"."""
    return f"{entry['time']}-{entry['kind']}" + (f"-{entry['topic']}" if entry.get("topic") else "")
