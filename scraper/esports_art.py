"""Gambar berita esports yang dibuat otomatis bila artikel tidak punya foto sendiri.

VLR.gg memakai gambar bawaan situs (card.png) untuk banyak artikel, jadi semua postingan terlihat sama.
Sebagai gantinya: logo tim + foto pemain yang disebut di artikel, disusun di latar bertema VALORANT."""
import hashlib
import io
import logging
import os
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import net

log = logging.getLogger(__name__)
CW, CH = 1600, 900
BG1, BG2, RED, TEAL = (15, 25, 35), (52, 22, 30), (255, 70, 85), (40, 220, 200)
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "fonts")
MAX_PLAYERS = 5


def _font(size, name="Montserrat-ExtraBold.ttf"):
    path = os.path.join(FONT_DIR, name)
    return ImageFont.truetype(path, size) if os.path.exists(path) else ImageFont.load_default()


def _img(url):
    try:
        data = net.get(url, timeout=20).content
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        log.debug("gambar %s gagal: %s", url, e)
        return None


def vlr_subjects(url):
    """Logo tim pertama + pemain (nama, url foto) yang disebut di isi artikel VLR."""
    soup = BeautifulSoup(net.get(url).text, "lxml")
    body = soup.select_one(".article-body")
    if not body:
        return None, []
    logo, team = None, None
    for a in body.select('a[href^="/team/"]'):
        im = a.find("img")
        if im and im.get("src"):
            logo, team = urljoin("https://www.vlr.gg", im["src"]), a.get_text(" ", strip=True).split(" Rank")[0]
            team = re.sub(r"\s+(North America|Europe|Brazil|Latin America.*|Asia.*|Korea|Japan|China|Inactive).*$",
                          "", team).strip()
            break
    for card in body.select(".wf-hover-card, .article-ref-card"):  # isi kartu hover = roster tim, bukan subjek berita
        card.decompose()
    players, seen = [], set()
    for a in body.select('a[href^="/player/"]'):
        href = a["href"]
        name = a.get_text(strip=True)
        if href in seen or not name or a.find("img"):
            continue
        seen.add(href)
        players.append((name, urljoin("https://www.vlr.gg", href)))
        if len(players) == MAX_PLAYERS:
            break
    shots = []
    for name, purl in players:
        try:
            ps = BeautifulSoup(net.get(purl).text, "lxml")
            im = ps.select_one(".player-header img") or ps.select_one(".wf-avatar img")
            src = urljoin("https://www.vlr.gg", im["src"]) if im and im.get("src") else None
            if src and "ph/sil" not in src:  # foto siluet bawaan = tanpa foto
                shots.append((name, src))
        except Exception as e:
            log.debug("pemain %s gagal: %s", purl, e)
    return (logo, team), shots


def _background():
    img = Image.new("RGB", (CW, CH), BG1)
    px = Image.linear_gradient("L").rotate(-60, expand=True).resize((CW, CH))
    img = Image.composite(Image.new("RGB", (CW, CH), BG2), img, px)
    d = ImageDraw.Draw(img, "RGBA")
    for k in range(-4, 14):  # garis diagonal khas VALORANT
        x = k * 150
        d.polygon([(x, CH), (x + 60, CH), (x + 60 + CH * 0.6, 0), (x + CH * 0.6, 0)], fill=(255, 70, 85, 14))
    d.polygon([(0, CH - 120), (CW * 0.55, CH), (0, CH)], fill=(*RED, 230))
    d.polygon([(CW, 0), (CW, 110), (CW * 0.6, 0)], fill=(*TEAL, 200))
    return img


def compose(logo_team, shots):
    logo_url, team = logo_team if logo_team else (None, None)
    logo = _img(logo_url) if logo_url else None
    photos = [(n, _img(u)) for n, u in shots]
    photos = [(n, p) for n, p in photos if p]
    if not logo and not photos:
        return None
    img = _background()
    d = ImageDraw.Draw(img, "RGBA")
    if logo:
        # logo besar samar sebagai latar + logo tajam di kiri
        big = logo.resize((760, 760), Image.LANCZOS)
        a = big.split()[-1].point(lambda v: v * 0.10)
        big.putalpha(a)
        img.paste(big, (CW - 700, 70), big)
        lg = logo.resize((380, 380), Image.LANCZOS)
        glow = Image.new("RGBA", (460, 460), (0, 0, 0, 0))
        glow.paste((255, 255, 255, 255), (40, 40), lg.split()[-1])
        glow = glow.filter(ImageFilter.GaussianBlur(18))
        lx, ly = (90, 150) if photos else ((CW - 380) // 2, 170)
        img.paste(glow, (lx - 40, ly - 40), glow)
        img.paste(lg, (lx, ly), lg)
        if team:
            f = _font(54)
            tw = d.textlength(team.upper(), font=f)
            cx = lx + 190
            d.text((max(40, cx - tw / 2), ly + 410), team.upper(), font=f, fill=(255, 255, 255))
    if photos:
        n = len(photos)
        x0 = 560 if logo else 80
        avail = CW - x0 - 60
        size = min(300, (avail - (n - 1) * 24) // n)
        y = 230 if n > 3 else 200
        fn = _font(30, "Montserrat-Bold.ttf")
        for k, (name, p) in enumerate(photos):
            x = x0 + k * (size + 24)
            tile = Image.new("RGBA", (size, size), (255, 255, 255, 18))
            ph = ImageOps.contain(p, (size, size), Image.LANCZOS)
            tile.paste(ph, ((size - ph.width) // 2, size - ph.height), ph)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=24, fill=255)
            d.rounded_rectangle((x - 4, y - 4, x + size + 4, y + size + 4), radius=28, outline=(*RED, 255), width=4)
            img.paste(tile, (x, y), Image.composite(tile.split()[-1].point(lambda v: 255), mask, mask))
            img.paste(tile, (x, y), mask)
            label = name if d.textlength(name, font=fn) <= size else name[:10] + "…"
            tw = d.textlength(label, font=fn)
            d.rounded_rectangle((x + (size - tw) / 2 - 14, y + size + 16, x + (size + tw) / 2 + 14, y + size + 62),
                                radius=12, fill=(0, 0, 0, 170))
            d.text((x + (size - tw) / 2, y + size + 22), label, font=fn, fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def article_art(url):
    """Bytes JPEG gambar pengganti untuk artikel esports, atau None bila tidak bisa dibuat."""
    if "vlr.gg/" not in url:
        return None
    try:
        return compose(*vlr_subjects(url))
    except Exception as e:
        log.warning("gambar esports %s gagal: %s", url, e)
        return None


def save(data, image_dir, utcnow):
    sha = hashlib.sha256(data).hexdigest()
    rel = os.path.join(utcnow().strftime("%Y/%m/%d"), f"{sha[:32]}.jpg")
    path = os.path.join(image_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return {"file_path": rel, "sha256": sha, "mime": "image/jpeg", "width": CW, "height": CH, "bytes": len(data)}
