"""Sale besar game (bukan diskon harian): Steam (jadwal resmi Valve) dan Xbox region Indonesia & Turki.

Postingan "Promo Steam" / "Promo Xbox" hanya dibuat saat ada event sale besar:
- Steam: Seasonal Sale (Spring/Summer/Autumn/Winter) + jendela Black Friday, dibaca dari halaman resmi
  "Upcoming Steam Events" (partner.steamgames.com), disimpan di cache harian.
- Xbox: tidak ada jadwal publik, jadi event dideteksi dari data toko: bila ratusan game populer berdiskon dengan
  tanggal berakhir yang SAMA, berarti sedang ada sale besar (Black Friday, Countdown, dst.).
"""
import base64
import io
import json
import logging
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PIL import Image

from .. import net
from ..db import SocialPost
from ..media import IMAGE_DIR
from . import settings

log = logging.getLogger(__name__)
PT = ZoneInfo("America/Los_Angeles")
CACHE_DIR = os.path.join(settings.ROOT, "data", "cache")
STEAM_EVENTS_URL = "https://partner.steamgames.com/doc/marketing/upcoming_events"
XBOX_BROWSE = "https://emerald.xboxservices.com/xboxcomfd/browse?locale={locale}"
XBOX_MARKETS = {"ID": {"locale": "id-ID", "currency": "IDR", "label": "Indonesia", "flag": "🇮🇩"},
                "TR": {"locale": "tr-TR", "currency": "TRY", "label": "Turki", "flag": "🇹🇷"}}
MONTHS = {m: i for i, m in enumerate(("january february march april may june july august september october "
                                      "november december").split(), 1)}

MIN_DISCOUNT = 50          # Xbox: diskon minimal untuk masuk daftar
XBOX_PAGES = 12            # 25 game per halaman, diurutkan "paling populer"
XBOX_EVENT_MIN = 80        # minimal jumlah game populer yang berakhir di tanggal yang sama untuk dianggap event
NOT_A_GAME = re.compile(r"soundtrack|\bost\b|\bpack\b|\bdlc\b|season pass|upgrade|artbook|demo|add-on|"
                        r"\bcoins?\b|points|currency|virtual|\bvc\b|bonus|expansion|\bkit\b|costume|skin", re.I)


@dataclass
class SaleEvent:
    name: str                  # "WINTER SALE", "BLACK FRIDAY"
    end: datetime              # UTC aware
    start: datetime = None     # UTC aware (Xbox: tidak diketahui)

    def days_left(self, now):
        return max(0, (self.end.astimezone(settings.TZ).date() - now.astimezone(settings.TZ).date()).days)

    def day_number(self, now):
        return (now - self.start).days + 1 if self.start else None


@dataclass
class Deals:
    store: str                 # steam | xbox
    region: str                # ID | TR
    currency: str              # IDR | TRY
    event: SaleEvent
    captured_at: datetime      # UTC naive (konsisten dengan kolom DB)
    items: list                # [{id, title, final, orig, disc, rating, reviews, image}]
    key: str = ""
    idr_rate: float = None     # kurs 1 unit currency -> IDR (untuk TRY)
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------------------------- utilitas
def _cache(name, max_age_h, fetch):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_h * 3600
    if not fresh:
        try:
            data = fetch()
            with open(path, "w") as f:
                json.dump(data, f, ensure_ascii=False)
            return data
        except Exception as e:
            log.warning("ambil %s gagal, memakai cache lama: %s", name, e)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def idr_rate(currency):
    if currency == "IDR":
        return 1.0
    data = _cache(f"fx_{currency}.json", 12, lambda: net.get(f"https://open.er-api.com/v6/latest/{currency}").json())
    try:
        return float(data["rates"]["IDR"])
    except Exception:
        return None


def remote_image(url, w=600):
    """Unduh gambar (sampul Xbox) ke IMAGE_DIR/xbox; return path relatif atau None."""
    key = re.sub(r"[^A-Za-z0-9]", "", url.rsplit("/", 1)[-1])[-60:]
    rel = os.path.join("xbox", f"{key}_{w}.jpg")
    path = os.path.join(IMAGE_DIR, rel)
    if os.path.exists(path):
        return rel
    try:
        data = net.get(url + ("&" if "?" in url else "?") + f"w={w}", timeout=30).content
        Image.open(io.BytesIO(data)).verify()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return rel
    except Exception as e:
        log.debug("gambar %s gagal: %s", url, e)
        return None


def recent_ids(db, kind, days=3):
    since = datetime.utcnow() - timedelta(days=days)
    used = set()
    for (key,) in db.query(SocialPost.content_key).filter(
            SocialPost.content_type == kind, SocialPost.status.in_(("posted", "prepared")),
            SocialPost.created_at >= since):
        used.update((key or "").split(","))
    return used


def franchise(title):
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower().split(":")[0].split("/")[0].split("™")[0]).split()
    words = [w for w in words if not w.isdigit() and w not in {"the", "a", "of"}]
    return " ".join(words[:2])


# ----------------------------------------------------------------------------------------------- Steam
def _pt(day, month, year, hour=10):
    return datetime(year, month, day, hour, tzinfo=PT).astimezone(timezone.utc)


def parse_steam_events(page_html):
    """Daftar event sale besar Steam dari halaman Upcoming Steam Events → [{name, start, end}] (ISO UTC)."""
    import html as htmllib
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", page_html, flags=re.S)
    lines = [l.strip() for l in htmllib.unescape(re.sub(r"<[^>]+>", "\n", text)).splitlines() if l.strip()]
    events = []
    for i, line in enumerate(lines[:-1]):
        m = re.fullmatch(r"(Spring|Summer|Autumn|Winter|Lunar New Year|Halloween|Black Friday)( Sale)? (\d{4})", line)
        nxt = lines[i + 1]
        d = re.search(r"(\d{1,2}) (\w+),? (\d{4})\s*-\s*(\d{1,2}) (\w+),? (\d{4})", nxt)
        if m and d and d.group(2).lower() in MONTHS and d.group(5).lower() in MONTHS:
            start = _pt(int(d.group(1)), MONTHS[d.group(2).lower()], int(d.group(3)))
            end = _pt(int(d.group(4)), MONTHS[d.group(5).lower()], int(d.group(6)))
            events.append({"name": f"{m.group(1).upper()} SALE", "start": start.isoformat(), "end": end.isoformat()})
    # Black Friday: "From November 26th 10AM PT through November 30th 10AM PT"
    bf = re.search(r"Black Friday (\d{4}).{0,600}?From (\w+) (\d{1,2})\w* 10AM PT through (\w+) (\d{1,2})\w* 10AM PT",
                   " ".join(lines), re.S)
    if bf and bf.group(2).lower() in MONTHS and bf.group(4).lower() in MONTHS:
        y = int(bf.group(1))
        events.append({"name": "BLACK FRIDAY", "start": _pt(int(bf.group(3)), MONTHS[bf.group(2).lower()], y).isoformat(),
                       "end": _pt(int(bf.group(5)), MONTHS[bf.group(4).lower()], y).isoformat()})
    return events


def steam_events():
    def fetch():
        ev = parse_steam_events(net.get(STEAM_EVENTS_URL, params={"l": "english"}, timeout=30,
                                           headers={"Accept-Language": "en-US,en;q=0.9"}).text)
        if not ev:
            raise ValueError("tidak ada event terbaca (format halaman berubah?)")
        return ev
    data = _cache("steam_events.json", 24, fetch) or []
    # gabung dengan event lama yang sudah lewat dari halaman (halaman hanya memuat event mendatang)
    hist_path = os.path.join(CACHE_DIR, "steam_events_all.json")
    allev = {}
    if os.path.exists(hist_path):
        with open(hist_path) as f:
            allev = {e["name"] + e["start"]: e for e in json.load(f)}
    allev.update({e["name"] + e["start"]: e for e in data})
    with open(hist_path, "w") as f:
        json.dump(list(allev.values()), f)
    return [SaleEvent(e["name"], datetime.fromisoformat(e["end"]), datetime.fromisoformat(e["start"]))
            for e in allev.values()]


def current_steam_event(now=None):
    now = now or datetime.now(timezone.utc)
    live = [e for e in steam_events() if e.start <= now < e.end]
    return min(live, key=lambda e: e.end) if live else None


def next_steam_event(now=None):
    now = now or datetime.now(timezone.utc)
    up = [e for e in steam_events() if e.start > now]
    return min(up, key=lambda e: e.start) if up else None


# ----------------------------------------------------------------------------------------------- Xbox
TITLE_NOISE = re.compile(
    r"\s*[-–—:]?\s*(Dijital Versiyon|Standart Sürüm|Standard Edition|Standart Edition|Digital Version)\b.*$"
    r"|\s*\((Xbox One|Xbox Series|Windows|PC)[^)]*\)"
    r"|\s+(XBOX One ve XBOX Series X\|S|for Xbox One|Xbox One & Xbox Series X\|S|Xbox Series X\|S)\s*$"
    r"|[™®]", re.I)


def clean_title(title):
    t = TITLE_NOISE.sub("", title or "").strip(" -–—:")
    return re.sub(r"\s+", " ", t) or title


def _xbox_page(locale, ct=None):
    filt = base64.b64encode(json.dumps({"orderby": {"id": "orderby", "choices": [{"id": "MostPopular desc"}]}})
                            .encode()).decode()
    body = {"Filters": filt, "ReturnFilters": False, "ChannelKeyToBeUsedInResponse": "X", "EncodedCT": ct,
            "ChannelId": "DynamicChannel.GameDeals"}
    r = net.session.post(XBOX_BROWSE.format(locale=locale), json=body, timeout=40, headers={
        "x-ms-api-version": "1.1", "ms-cv": uuid.uuid4().hex[:16] + ".0",
        "Origin": "https://www.xbox.com", "Referer": "https://www.xbox.com/"})
    r.raise_for_status()
    j = r.json()
    return j.get("productSummaries") or [], (j.get("channels", {}).get("X") or {}).get("encodedCT")


def xbox_scan(region):
    """Game Xbox berdiskon paling populer di region → list dict (urut popularitas)."""
    m = XBOX_MARKETS[region]
    out, ct = [], None
    for _ in range(XBOX_PAGES):
        prods, ct = _xbox_page(m["locale"], ct)
        for p in prods:
            pr = ((p.get("specificPrices") or {}).get("purchaseable") or [])
            if not pr or p.get("productKind") != "Game":
                continue
            x = pr[0]
            img = (p.get("images") or {})
            poster = (img.get("poster") or img.get("boxArt") or {}).get("url")
            hero = (img.get("superHeroArt") or img.get("titledHeroArt") or {}).get("url")
            try:
                end = datetime.strptime(x["endDateUtc"], "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                end = None
            out.append({"id": p["productId"], "title": clean_title(p.get("title")),
                        "final": float(x.get("listPrice") or 0), "orig": float(x.get("msrp") or 0),
                        "disc": int(round(x.get("discountPercentage") or 0)), "end": end,
                        "rating": p.get("averageRating"), "reviews": p.get("ratingCount") or 0,
                        "image": poster, "hero": hero,
                        "url": f"https://www.xbox.com/{m['locale']}/games/store/x/{p['productId']}"})
        if not ct:
            break
    return out


XBOX_EVENT_NAMES = [  # (bulan-hari mulai, bulan-hari akhir, nama) berdasarkan tanggal berakhir sale (WIB)
    ((11, 10), (12, 10), "BLACK FRIDAY"),
    ((12, 11), (1, 20), "COUNTDOWN SALE"),
    ((1, 21), (2, 28), "LUNAR NEW YEAR"),
    ((3, 1), (4, 30), "SPRING SALE"),
    ((6, 15), (8, 10), "ULTIMATE GAME SALE"),
]


def xbox_event_name(end):
    d = end.astimezone(settings.TZ)
    md = (d.month, d.day)
    for a, b, name in XBOX_EVENT_NAMES:
        if (a <= md <= b) if a <= b else (md >= a or md <= b):
            return name
    return "MEGA SALE"


def detect_xbox_event(items):
    ends = Counter(i["end"] for i in items if i["end"] and i["disc"] > 0)
    if not ends:
        return None
    end, n = ends.most_common(1)[0]
    if n < XBOX_EVENT_MIN or n < 0.3 * len(items):
        return None
    return SaleEvent(xbox_event_name(end), end)


# ----------------------------------------------------------------------------------------------- pemilihan
def _pick(pool, n, used):
    chosen, seen = [], set()
    for i in [x for x in pool if x["id"] not in used] + [x for x in pool if x["id"] in used]:
        fk = franchise(i["title"])
        if fk in seen:
            continue
        seen.add(fk)
        chosen.append(i)
        if len(chosen) == n:
            break
    return chosen


def xbox_deals(db, region, kind, n=16, now=None):
    """Deals Xbox untuk region saat ada event besar. Return (Deals, None) atau (None, alasan)."""
    items = xbox_scan(region)
    if not items:
        return None, "data toko Xbox kosong"
    ev = detect_xbox_event(items)
    if not ev:
        return None, "tidak ada sale besar Xbox saat ini (diskon harian tidak diposting)"
    pool = [i for i in items if i["disc"] >= MIN_DISCOUNT and i["end"] == ev.end and i["image"]
            and not NOT_A_GAME.search(i["title"])]
    # popularitas toko sudah jadi urutan; game dengan banyak ulasan & rating bagus sedikit didahulukan
    for rank, i in enumerate(pool):
        i["score"] = rank - min(40, (i["reviews"] or 0) / 10) - (10 if (i["rating"] or 0) >= 4.3 else 0)
    pool.sort(key=lambda i: i["score"])
    picks = _pick(pool, n, recent_ids(db, kind))
    if len(picks) < 4:
        return None, f"sale Xbox {region} berjalan tapi game berdiskon ≥{MIN_DISCOUNT}% terlalu sedikit"
    m = XBOX_MARKETS[region]
    return Deals("xbox", region, m["currency"], ev, datetime.utcnow(), picks, ",".join(i["id"] for i in picks),
                 idr_rate(m["currency"])), None


def steam_sale_deals(db, legacy, now=None):
    """Bungkus pilihan promo Steam (content.steam_deals) jadi Deals bila sedang ada event besar Steam."""
    ev = current_steam_event(now)
    if not ev:
        nxt = next_steam_event(now)
        why = "tidak ada sale besar Steam saat ini (diskon harian tidak diposting)"
        if nxt:
            why += f"; berikutnya {nxt.name.title()} mulai {nxt.start.astimezone(settings.TZ):%d-%m-%Y}"
        return None, why
    if not legacy:
        return None, "data promo Steam belum ada"
    items = [{"id": i["appid"], "title": i["title"], "final": i["final"], "orig": i["orig"], "disc": i["disc"],
              "rating": i["rating"], "reviews": i["reviews"], "image": None,
              "url": f"https://store.steampowered.com/app/{i['appid']}/"} for i in legacy.items]
    return Deals("steam", "ID", "IDR", ev, legacy.captured_at, items, legacy.key, 1.0), None
