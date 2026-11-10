"""Scraper berita via RSS (semua kategori) + ekstraksi isi artikel opsional."""
import calendar
import hashlib
import logging
import re
import time
from datetime import datetime

import feedparser
from bs4 import BeautifulSoup

from .. import net
from ..config import NEWS_FEEDS
from ..db import Article, get_or_create_source

log = logging.getLogger(__name__)


def _clean_html(html):
    if not html:
        return None
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip() or None


def _published(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.utcfromtimestamp(calendar.timegm(t))
    return None


def _image(entry):
    for key in ("media_content", "media_thumbnail"):
        items = entry.get(key) or []
        if items and items[0].get("url"):
            return items[0]["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]
    return None


def extract_article_text(url):
    """Ambil isi artikel dari halaman HTML (heuristik umum: paragraf dalam <article>/blok terbesar)."""
    soup = BeautifulSoup(net.get(url).text, "lxml")
    for tag in soup(["script", "style", "noscript", "aside", "nav", "footer", "header", "form", "figure"]):
        tag.decompose()
    container = soup.find("article")
    if container is None or len(container.find_all("p")) < 2:
        # pilih elemen dengan jumlah teks paragraf langsung terbanyak
        best, best_len = None, 0
        for el in soup.find_all(["div", "section", "main"]):
            n = sum(len(p.get_text(strip=True)) for p in el.find_all("p", recursive=False))
            if n > best_len:
                best, best_len = el, n
        container = best or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    paras = [p for p in paras if len(p) > 40 and not re.match(r"(?i)^(baca juga|simak|lihat juga|advertisement)", p)]
    return "\n\n".join(paras) or None


def url_hash(url):
    return hashlib.sha256(url.strip().encode()).hexdigest()


def store_entries(db, src, category, entries, transform=None):
    """Simpan entri feedparser sebagai Article. Return list (article, is_new) termasuk yang sudah ada."""
    by_hash = {url_hash(e.link): e for e in entries}
    if not by_hash:
        return []
    existing = {a.url_hash: a for a in db.query(Article).filter(Article.url_hash.in_(list(by_hash)))}
    out = []
    for h, e in by_hash.items():
        if h in existing:
            out.append((existing[h], False))
            continue
        summary_html = e.get("summary") or (e.get("content") or [{}])[0].get("value")
        fields = dict(
            source_id=src.id,
            category=category,
            title=_clean_html(e.title)[:500],
            url=e.link.strip()[:1000],
            url_hash=h,
            summary=_clean_html(summary_html),
            author=(e.get("author") or None) and e.author[:255],
            tags=", ".join(t.get("term", "") for t in e.get("tags", []) if t.get("term"))[:1000] or None,
            image_url=_image(e),
            published_at=_published(e),
        )
        if transform:
            fields = transform(e, fields)
        a = Article(**fields)
        db.add(a)
        out.append((a, True))
    db.flush()
    return out


def scrape_feeds(db, categories, full_text=False, full_text_limit=50, delay=1.0):
    """Return dict kategori -> jumlah artikel baru."""
    counts = {}
    for feed in NEWS_FEEDS:
        if feed["category"] not in categories:
            continue
        try:
            resp = net.get(feed["url"], timeout=feed.get("timeout", net.TIMEOUT))
            parsed = feedparser.parse(resp.content)
        except Exception as e:  # satu feed gagal tidak menghentikan yang lain
            log.warning("Feed gagal %s: %s", feed["name"], e)
            continue

        src = get_or_create_source(db, feed["name"], feed["url"], feed["category"], "rss", feed["lang"])
        entries = [e for e in parsed.entries if e.get("link") and e.get("title")]
        new = len([a for a, is_new in store_entries(db, src, feed["category"], entries) if is_new])
        db.commit()
        counts[feed["category"]] = counts.get(feed["category"], 0) + new
        log.info("[%s] %s: %d entri, %d baru", feed["category"], feed["name"], len(entries), new)

    if full_text:
        fill_full_text(db, categories, full_text_limit, delay)
    return counts


def fill_full_text(db, categories, limit, delay=1.0):
    """Lengkapi kolom content untuk artikel terbaru yang belum punya isi."""
    rows = (db.query(Article).filter(Article.content.is_(None), Article.category.in_(categories),
                                     ~Article.url.like("https://news.google.com/%"))
            .order_by(Article.published_at.desc()).limit(limit).all())
    ok = 0
    for a in rows:
        try:
            a.content = extract_article_text(a.url) or ""
            ok += bool(a.content)
        except Exception as e:
            log.debug("Isi artikel gagal %s: %s", a.url, e)
            a.content = ""  # tandai sudah dicoba
        db.commit()
        time.sleep(delay)
    log.info("Isi artikel terambil: %d/%d", ok, len(rows))
