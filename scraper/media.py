"""Unduh gambar utama berita ke disk + lengkapi image_url yang kosong dari og:image halaman artikel."""
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import time
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from PIL import Image

from . import net
from .db import Article, ArticleImage, ArticleYoutube, utcnow

log = logging.getLogger(__name__)
IMAGE_DIR = os.getenv("IMAGE_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "images"))
MAX_BYTES = 15 * 1024 * 1024
EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif", "AVIF": "avif"}


def _recent(db, days):
    return db.query(Article).filter(Article.scraped_at >= utcnow() - timedelta(days=days),
                                    ~Article.url.like("https://news.google.com/%"))


def find_og_image(url):
    soup = BeautifulSoup(net.get(url).text, "lxml")
    for attrs in ({"property": "og:image"}, {"name": "og:image"}, {"name": "twitter:image"},
                  {"property": "twitter:image"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").startswith("http"):
            return tag["content"].strip()
    return None


def fill_missing_image_urls(db, days=3, limit=100, delay=0.5):
    """Artikel tanpa gambar di RSS: ambil og:image dari halamannya. '' = sudah dicoba, tidak ada."""
    rows = _recent(db, days).filter(Article.image_url.is_(None)).order_by(Article.id.desc()).limit(limit).all()
    found = 0
    for a in rows:
        try:
            a.image_url = (find_og_image(a.url) or "")[:1000]
        except Exception as e:
            log.debug("og:image gagal %s: %s", a.url, e)
            a.image_url = ""
        found += bool(a.image_url)
        db.commit()
        time.sleep(delay)
    log.info("og:image: %d/%d artikel mendapat gambar", found, len(rows))
    return found


def download_image(url):
    """Return dict info file yang tersimpan di IMAGE_DIR."""
    r = net.get(url, stream=True)
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("gambar terlalu besar")
    img = Image.open(io.BytesIO(data))
    img.verify()
    fmt = img.format or "JPEG"
    sha = hashlib.sha256(data).hexdigest()
    rel = os.path.join(utcnow().strftime("%Y/%m/%d"), f"{sha[:32]}.{EXT.get(fmt, 'img')}")
    path = os.path.join(IMAGE_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    w, h = Image.open(io.BytesIO(data)).size
    return {"file_path": rel, "sha256": sha, "mime": Image.MIME.get(fmt, fmt), "width": w, "height": h,
            "bytes": len(data)}


def download_images(db, days=3, limit=200, delay=0.3):
    rows = (_recent(db, days).outerjoin(ArticleImage, ArticleImage.article_id == Article.id)
            .filter(ArticleImage.id.is_(None), Article.image_url.isnot(None), Article.image_url != "")
            .order_by(Article.id.desc()).limit(limit).all())
    ok = 0
    for a in rows:
        rec = ArticleImage(article_id=a.id, kind="main", source_url=a.image_url)
        try:
            for k, v in download_image(a.image_url).items():
                setattr(rec, k, v)
            rec.status = "ok"
            ok += 1
        except Exception as e:
            rec.status, rec.error = "failed", str(e)[:500]
        db.add(rec)
        db.commit()
        time.sleep(delay)
    log.info("Gambar diunduh: %d/%d", ok, len(rows))
    return ok


def image_abspath(rel):
    return os.path.join(IMAGE_DIR, rel)


def process_images(db):
    fill_missing_image_urls(db)
    return download_images(db)


def ensure_image(db, article):
    """Path relatif gambar utama artikel; unduh sekarang bila belum ada. None jika tidak tersedia.

    Bila gambar dari RSS gagal (mis. ternyata link embed video), coba sekali gambar og:image halaman artikel.
    """
    rec = db.query(ArticleImage).filter_by(article_id=article.id, kind="main").one_or_none()
    if rec and (rec.status == "ok" or (rec.error or "").startswith("[og]")):
        return rec.file_path if rec.status == "ok" else None
    if rec is None:
        if not article.image_url:
            return None
        rec = ArticleImage(article_id=article.id, kind="main", source_url=article.image_url)
        db.add(rec)
        try:
            for k, v in download_image(article.image_url).items():
                setattr(rec, k, v)
            rec.status, rec.error = "ok", None
            db.commit()
            return rec.file_path
        except Exception as e:
            rec.status, rec.error = "failed", str(e)[:500]
    try:
        og = find_og_image(article.url)
        if not og or og == rec.source_url:
            raise ValueError("og:image tidak tersedia")
        for k, v in download_image(og).items():
            setattr(rec, k, v)
        rec.source_url, rec.status, rec.error = og[:1000], "ok", None
    except Exception as e:
        rec.status, rec.error = "failed", f"[og] {e}"[:500]
    db.commit()
    return rec.file_path if rec.status == "ok" else None


# ---------------------------------------------------------------- isi artikel lengkap (untuk posting)
SKIP_IMG = re.compile(r"logo|icon|avatar|emoji|sprite|badge|banner|/ads?/|advert|pixel|placeholder|gravatar|"
                      r"\.svg|\.gif|data:image|/default\.(jpe?g|png|webp)|no-?image|noimage|blank\.|spacer|"
                      r"loading\.|lazy\.|iklan|popup|paywall|article-limit|sharedimages|subscribe", re.I)
# wadah yang bukan isi artikel: kotak "baca juga"/terkait, rekomendasi, iklan, widget, embed sosmed, dll.
BLOCK_CONTAINER = re.compile(
    r"\b(baca\w*|lihat\w*|simak\w*|jg|related|terkait|rekomendasi|recommend\w*|populer|popular|terpopuler|trending|terkini|"
    r"lainnya|pilihan|sidebar|widget|promo\w*|sponsor\w*|advert\w*|ads?|adsense|iklan|outbrain|taboola|mgid|"
    r"dable|nativ\w*|newsletter|share|sosmed|social|embed|comment\w*|author|breadcrumb|banner|"
    r"parallax|inbound|topik|tags?|footer|nav|menu)\b", re.I)


def _img_key(url):
    """Kunci pembanding gambar: path tanpa host & tanpa akhiran ukuran.
    Detik menyajikan gambar sama dari CDN berbeda; PC Gamer/WordPress menaruh ukuran di nama file
    (mis. "-1200-80.jpg", "-800x450.jpg")."""
    path = urlparse(url or "").path.lower().rstrip("/")
    return re.sub(r"(-\d{2,4}x\d{2,4}|-\d{3,4}-\d{2})(?=\.\w{3,4}$)", "", path)


def _blocked(el):
    """True bila elemen berada di wadah non-isi (lihat BLOCK_CONTAINER)."""
    for p in el.parents:
        if p.name in ("article", "body", "html", "[document]"):
            return False
        # wadah yang memuat beberapa paragraf panjang = isi artikel (mis. PC Gamer "widget-contentparsed",
        # WordPress "entry-content no-share") — jangan diblokir walau nama class-nya mirip widget
        if sum(1 for x in p.find_all("p", limit=12) if len(x.get_text(strip=True)) > 80) >= 3:
            return False
        attrs = " ".join(p.get("class", [])) + " " + (p.get("id") or "")
        if attrs.strip() and BLOCK_CONTAINER.search(re.sub(r"[-_]", " ", attrs)):
            return True
    return False


AFFILIATE = re.compile(r"georiot|amazon\.|amzn\.|target\.com|bestbuy|walmart|ebay\.|aliexpress|shopee|tokopedia|"
                       r"lazada|blibli|bukalapak|skimresources|linksynergy|awin1|howl\.me|shareasale|impact\.com|"
                       r"go\.redirectingat|Proxy\.ashx|affiliate|/aff/|utm_medium=affiliate|clickbank|tracking", re.I)


def _site(url):
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and parts[-2] in ("co", "com", "or", "my", "go", "ac") else ".".join(parts[-2:])


def _links_elsewhere(img, page_url):
    """Gambar yang dibungkus link ke artikel lain di situs yang sama (kartu "berita terkait") atau ke toko/afiliasi
    (iklan belanja) bukan gambar isi. Link ke situs lain non-toko (mis. halaman Steam/publisher) tetap diterima."""
    a = img.find_parent("a")
    if not a or not a.get("href"):
        return False
    href = urljoin(page_url, a["href"]).split("#")[0]
    if re.search(r"\.(jpe?g|png|webp|avif)(\?|$)", href, re.I) or href.rstrip("/") == page_url.rstrip("/"):
        return False  # link ke versi besar gambarnya sendiri
    if AFFILIATE.search(href):
        return True
    return _site(href) == _site(page_url)


SKIP_TEXT = re.compile(r"^(baca juga|simak|lihat juga|advertisement|scroll to continue|related:|read more|"
                       r"also read|sign up|subscribe|follow us|ikuti kami|tonton juga|dapatkan update)", re.I)


def _img_src(tag, base_url):
    cands = [tag.get(k) for k in ("data-src", "data-lazy-src", "data-original", "src")]
    srcset = tag.get("srcset") or tag.get("data-srcset")
    if srcset:  # ambil kandidat terbesar
        parts = [p.strip().split(" ") for p in srcset.split(",") if p.strip()]
        best = max(parts, key=lambda p: int(re.sub(r"\D", "", p[1]) or 0) if len(p) > 1 else 0)
        cands.insert(0, best[0])
    for c in cands:
        if not c or c.startswith("data:"):
            continue
        url = urljoin(base_url, c.strip())
        q = parse_qs(urlparse(url).query)
        if "/_next/image" in url and q.get("url"):  # gambar Next.js: ambil URL aslinya
            url = urljoin(base_url, unquote(q["url"][0]))
        return url
    return None


YOUTUBE_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})")
VIDEO_EXT = re.compile(r"\.(mp4|webm|mov|m4v)(\?|$)", re.I)
FFMPEG = os.getenv("FFMPEG_BIN", "/home/gitgitmiko/game-toolchain/bin/ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "/home/gitgitmiko/game-toolchain/bin/ffprobe")
MAX_VIDEO_BYTES = int(os.getenv("MAX_VIDEO_MB", "100")) * 1024 * 1024
VIDEO_KEEP_DAYS = int(os.getenv("VIDEO_KEEP_DAYS", "7"))


def extract_article_details(url, title="", return_rejected=False):
    """Ambil isi artikel lengkap.

    Return (paragraf, media, youtube): paragraf (list diberi "• "), media = [(jenis, url)] gambar/video file
    di dalam isi sesuai urutan kemunculan, youtube = daftar ID video YouTube yang disematkan."""
    soup = BeautifulSoup(net.get(url).text, "lxml")
    for tag in soup(["script", "style", "noscript", "aside", "nav", "footer", "header", "form"]):
        tag.decompose()
    container = soup.find("article")
    if container is None or len(container.find_all("p")) < 2:
        best, best_len = None, 0
        for el in soup.find_all(["div", "section", "main"]):
            n = sum(len(p.get_text(strip=True)) for p in el.find_all("p", recursive=False))
            if n > best_len:
                best, best_len = el, n
        container = best or soup.body or soup

    paragraphs, media, youtube, seen, rejected = [], [], [], set(), set()
    media_pos, last_text = [], -1  # urutan kemunculan, untuk membuang gambar setelah paragraf terakhir
    for idx, el in enumerate(container.find_all(["p", "li", "h2", "h3", "img", "video", "iframe"])):
        if el.name == "iframe":
            m = YOUTUBE_ID.search(el.get("src") or el.get("data-src") or "")
            if m and m.group(1) not in youtube:  # embed siaran langsung channel (bukan video) tidak cocok pola ID
                youtube.append(m.group(1))
            continue
        if el.name == "video":
            srcs = [el.get("src")] + [s.get("src") for s in el.find_all("source")]
            src = next((urljoin(url, x) for x in srcs if x and VIDEO_EXT.search(x)), None) \
                or next((urljoin(url, x) for x in srcs if x), None)
            if src and _img_key(src) not in seen and not _blocked(el):
                seen.add(_img_key(src))
                media.append(("video", src))
                media_pos.append(idx)
            continue
        if el.name == "img":
            src = _img_src(el, url)
            if (el.find_parent(["a"]) and el.find_parent(["li"])) or _links_elsewhere(el, url) or _blocked(el):
                if src:  # thumbnail artikel lain / kotak baca juga / iklan / widget
                    rejected.add(_img_key(src))
                continue
            w, h = (int(re.sub(r"\D", "", el.get(k) or "0") or 0) for k in ("width", "height"))
            if not src or SKIP_IMG.search(src) or (w and w < 400) or (h and h < 200):
                continue
            if _img_key(src) not in seen:
                seen.add(_img_key(src))
                media.append(("image", src))
                media_pos.append(idx)
            continue
        if el.name == "p" and el.find_parent("li"):
            continue
        if _blocked(el):  # teks di kotak baca juga / widget bukan isi artikel
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
        if el.name == "li":
            if 3 <= len(text) <= 300 and not el.find("a", recursive=False) or (el.find("a") and len(text) > 60):
                paragraphs.append(f"• {text}")
            continue
        if el.name in ("h2", "h3"):
            if 3 < len(text) < 120 and text.lower() != title.lower():
                paragraphs.append(text.upper() if len(text) < 40 else text)
            continue
        if len(text) > 25 and not SKIP_TEXT.match(text) and text.lower() != title.lower():
            paragraphs.append(text)
            last_text = idx
    # widget rekomendasi biasanya setelah isi berakhir: buang media yang muncul setelah paragraf terakhir
    rejected |= {_img_key(m[1]) for m, pos in zip(media, media_pos) if pos >= last_text}
    media = [m for m, pos in zip(media, media_pos) if pos < last_text]
    out, keys = [], set()
    for p in paragraphs:  # buang paragraf duplikat
        k = p.lower()[:80]
        if k not in keys:
            keys.add(k)
            out.append(p)
    if return_rejected:
        return out, media, youtube, rejected
    return out, media, youtube


def probe_video(path):
    """(lebar, tinggi, durasi detik, ada_audio) lewat ffprobe."""
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                        "-of", "json", path], capture_output=True, text=True, timeout=60)
    info = json.loads(r.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        raise ValueError("bukan file video")
    audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    return v.get("width"), v.get("height"), float(info.get("format", {}).get("duration") or 0), audio


def _flat_image(rel):
    """Gambar hampir satu warna (placeholder/logo di latar polos) — tidak layak jadi slide."""
    from PIL import ImageStat
    try:
        src = Image.open(image_abspath(rel))
        im = src.convert("L")
        im.thumbnail((200, 200))
        colors = len(src.convert("RGB").resize((64, 64)).getcolors(4096) or [])
        # placeholder/latar polos: hampir tanpa variasi atau sangat sedikit warna (screenshot gelap tetap lolos)
        return ImageStat.Stat(im).stddev[0] < 12 or colors < 150
    except OSError:
        return True


def download_video(url):
    r = net.get(url, stream=True, timeout=60)
    ext = (VIDEO_EXT.search(url).group(1).lower() if VIDEO_EXT.search(url) else "mp4")
    tmp = os.path.join(IMAGE_DIR, ".tmp", f"{hashlib.sha1(url.encode()).hexdigest()}.{ext}")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    sha, size = hashlib.sha256(), 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1024 * 256):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                f.close()
                os.remove(tmp)
                raise ValueError("video terlalu besar")
            sha.update(chunk)
            f.write(chunk)
    digest = sha.hexdigest()
    rel = os.path.join(utcnow().strftime("%Y/%m/%d"), f"{digest[:32]}.{ext}")
    path = os.path.join(IMAGE_DIR, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    os.replace(tmp, path)
    w, h, dur, _ = probe_video(path)
    return {"file_path": rel, "sha256": digest, "mime": f"video/{'quicktime' if ext == 'mov' else ext}",
            "width": w, "height": h, "bytes": size, "duration": dur}


def ensure_article_details(db, article, max_media=6):
    """Lengkapi isi artikel & unduh gambar/video di dalam isi (kind "body"/"video").

    Return (media, youtube): media = [{"type": "image"|"video", "path": rel}] sesuai urutan di artikel."""
    def stored():
        rows = (db.query(ArticleImage).filter(ArticleImage.article_id == article.id,
                                              ArticleImage.kind.in_(("body", "video")), ArticleImage.status == "ok")
                .order_by(ArticleImage.position))
        return [{"type": "video" if r.kind == "video" else "image", "path": r.file_path} for r in rows][:max_media]

    if article.url.startswith("https://news.google.com/"):
        return [], []
    try:
        paragraphs, media, youtube = extract_article_details(article.url, article.title or "")
    except Exception as e:
        log.debug("detail artikel gagal %s: %s", article.url, e)
        return stored(), []
    text = "\n\n".join(paragraphs)
    if len(text) > len(article.content or "") * 0.8:  # versi baru memuat list/subjudul; pakai bila tidak lebih pendek
        article.content = text
    article.details_fetched_at = utcnow()
    store_youtube(db, article, youtube)

    main = db.query(ArticleImage).filter_by(article_id=article.id, kind="main").one_or_none()
    main_keys = {_img_key(main.source_url) if main else "", _img_key(article.image_url)} - {""}
    main_sha = main.sha256 if main else None
    existing = {r.source_url: r for r in db.query(ArticleImage).filter(
        ArticleImage.article_id == article.id, ArticleImage.kind.in_(("body", "video")))}
    shas = {r.sha256 for r in existing.values() if r.sha256}
    for pos, (kind, src) in enumerate(media[:max_media + 3]):
        if _img_key(src) in main_keys or src[:1000] in existing or \
                any(_img_key(src) == _img_key(u) for u in existing):
            continue
        rec = ArticleImage(article_id=article.id, kind="video" if kind == "video" else "body", position=pos,
                           source_url=src[:1000])
        try:
            info = download_video(src) if kind == "video" else download_image(src)
            dur = info.pop("duration", None)
            reject = ((kind == "image" and (info["width"] < 500 or info["height"] < 250))  # terlalu kecil
                      or (kind == "image" and _flat_image(info["file_path"]))  # placeholder warna polos
                      or info["sha256"] in shas or info["sha256"] == main_sha  # duplikat
                      or (kind == "video" and dur is not None and dur < 3))  # IG menolak video < 3 detik
            if reject:
                if kind == "video" and info["sha256"] not in shas:  # jangan tinggalkan file video yatim
                    os.remove(image_abspath(info["file_path"]))
                continue
            for k, v in info.items():
                setattr(rec, k, v)
            rec.status = "ok"
            shas.add(info["sha256"])
        except Exception as e:
            rec.status, rec.error = "failed", str(e)[:500]
        db.add(rec)
        existing[src[:1000]] = rec
    db.commit()
    return stored(), youtube


def store_youtube(db, article, video_ids):
    """Simpan metadata video YouTube (oEmbed resmi, tanpa API key) — videonya sendiri tidak diunduh."""
    have = {v for (v,) in db.query(ArticleYoutube.video_id).filter_by(article_id=article.id)}
    for pos, vid in enumerate(video_ids):
        if vid in have:
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        row = ArticleYoutube(article_id=article.id, position=pos, video_id=vid, url=url, fetched_at=utcnow())
        try:
            meta = net.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}).json()
            row.title = (meta.get("title") or "")[:500] or None
            row.channel = (meta.get("author_name") or "")[:255] or None
            row.channel_url = (meta.get("author_url") or "")[:500] or None
            row.thumbnail_url = (meta.get("thumbnail_url") or "")[:500] or None
        except Exception as e:  # video privat/dihapus: simpan ID & link saja
            log.debug("oEmbed YouTube %s gagal: %s", vid, e)
        db.add(row)
        have.add(vid)


def fetch_recent_details(db, categories, hours=48, limit=120, delay=0.5):
    """Saat scraping: ambil isi lengkap + gambar/video di dalam artikel yang terbit `hours` jam terakhir
    (kategori yang punya akun posting). Arsip lama yang baru ter-scrape tidak ikut diproses."""
    rows = (db.query(Article).filter(Article.category.in_(list(categories)),
                                     Article.published_at >= utcnow() - timedelta(hours=hours),
                                     Article.details_fetched_at.is_(None),
                                     ~Article.url.like("https://news.google.com/%"))
            .order_by(Article.published_at.desc()).limit(limit).all())
    n_img = n_vid = 0
    for a in rows:
        media, _ = ensure_article_details(db, a, max_media=6)
        if a.details_fetched_at is None:  # halaman gagal dibuka: tandai agar tidak dicoba tiap jam
            a.details_fetched_at = utcnow()
            db.commit()
        n_img += sum(m["type"] == "image" for m in media)
        n_vid += sum(m["type"] == "video" for m in media)
        time.sleep(delay)
    log.info("Detail artikel: %d artikel, %d gambar & %d video di dalam isi", len(rows), n_img, n_vid)
    return len(rows)


def cleanup_videos(db, keep_days=VIDEO_KEEP_DAYS):
    """Retensi video: hapus file video `keep_days` hari setelah artikelnya diposting, atau `keep_days` hari
    setelah diunduh bila tidak pernah diposting. Catatan di database (URL asli, ukuran, sha256) tetap disimpan."""
    from .db import SocialPost
    from sqlalchemy import func
    cutoff = utcnow() - timedelta(days=keep_days)
    posted = dict(db.query(SocialPost.article_id, func.min(SocialPost.updated_at))
                  .filter(SocialPost.status == "posted", SocialPost.article_id.isnot(None))
                  .group_by(SocialPost.article_id).all())
    removed, freed = 0, 0
    for rec in db.query(ArticleImage).filter(ArticleImage.kind == "video", ArticleImage.status == "ok"):
        ref = posted.get(rec.article_id) or rec.downloaded_at
        if ref and ref < cutoff:
            path = image_abspath(rec.file_path) if rec.file_path else None
            if path and os.path.exists(path):
                freed += os.path.getsize(path)
                os.remove(path)
            rec.status = "expired"
            rec.error = f"file dihapus otomatis (retensi {keep_days} hari)"
            removed += 1
    db.commit()
    log.info("Retensi video: %d file dihapus (%.1f MB)", removed, freed / 1048576)
    return removed


# ---------------------------------------------------------------- gambar game dari CDN Steam (cache 7 hari)
STEAM_ART_URL = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/{file}"


def steam_art(appid, file="library_600x900.jpg", max_age_days=7):
    """Path relatif (terhadap IMAGE_DIR) gambar resmi game dari Steam, mis. sampul portrait/hero/header.
    None bila game tidak punya gambar itu."""
    rel = os.path.join("steam", f"{appid}_{file}")
    path = image_abspath(rel)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_days * 86400:
        return rel
    try:
        data = net.get(STEAM_ART_URL.format(appid=appid, file=file), timeout=30).content
        Image.open(io.BytesIO(data)).verify()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return rel
    except Exception as e:
        log.debug("gambar Steam %s/%s tidak tersedia: %s", appid, file, e)
        return rel if os.path.exists(path) else None


def recheck_body_media(db, categories, days=3, delay=0.3):
    """Terapkan ulang filter terbaru ke gambar isi tersimpan. Ditolak hanya bila ADA BUKTI bukan isi artikel
    (di kotak baca juga/iklan/widget, link ke artikel lain, setelah paragraf terakhir, sama dengan sampul,
    URL mencurigakan, atau placeholder polos). Gambar yang sekadar tidak ditemukan lagi di halaman
    (halaman berubah/lazy-load) dibiarkan. Return {kategori: (diperiksa, ditolak)}."""
    from collections import Counter
    arts = (db.query(Article).join(ArticleImage, ArticleImage.article_id == Article.id)
            .filter(ArticleImage.kind == "body", ArticleImage.status.in_(("ok", "rejected")),
                    Article.category.in_(list(categories)),
                    Article.published_at >= utcnow() - timedelta(days=days)).distinct().all())
    checked, rejected = Counter(), Counter()
    for a in arts:
        try:
            _, _, _, bad_keys = extract_article_details(a.url, a.title or "", return_rejected=True)
        except Exception as e:
            log.debug("recheck %s gagal: %s", a.url, e)
            bad_keys = set()
        main = db.query(ArticleImage).filter_by(article_id=a.id, kind="main").one_or_none()
        main_keys = {_img_key(main.source_url) if main else "", _img_key(a.image_url)} - {""}
        for rec in db.query(ArticleImage).filter(ArticleImage.article_id == a.id, ArticleImage.kind == "body",
                                                 ArticleImage.status.in_(("ok", "rejected"))):
            checked[a.category] += 1
            key = _img_key(rec.source_url)
            bad = (key in bad_keys or key in main_keys or SKIP_IMG.search(rec.source_url)
                   or not rec.file_path or _flat_image(rec.file_path))
            if bad:
                rec.status, rec.error = "rejected", "bukan gambar isi (baca juga/iklan/widget/placeholder/sampul)"
                rejected[a.category] += 1
            else:
                rec.status, rec.error = "ok", None
        db.commit()
        time.sleep(delay)
    return {c: (checked[c], rejected[c]) for c in checked}
