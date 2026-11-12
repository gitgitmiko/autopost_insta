"""Berita khusus VALORANT & Dota 2: situs resmi VALORANT (ID), pengumuman resmi Dota 2 di Steam,
lalu penandaan topik (article_assets asset_type="game") untuk semua artikel game."""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from .. import net
from ..config import GAME_TOPICS, NEWS_FEEDS
from ..db import Article, ArticleAsset, Source, get_or_create_source, utcnow
from .news import store_entries

log = logging.getLogger(__name__)
VALORANT_NEWS = "https://playvalorant.com/id-id/news/"
DOTA_NEWS = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
OFFICIAL_SOURCES = {"VALORANT Resmi (playvalorant.com)": "valorant", "Dota 2 Resmi (Steam)": "dota2"}


def _entry(title, link, published, summary=None, image=None):
    """Bentuk mirip entri feedparser agar bisa disimpan lewat store_entries()."""
    e = SimpleNamespace(title=title, link=link)
    data = {"title": title, "link": link, "summary": summary,
            "published_parsed": published.utctimetuple() if published else None,
            "media_content": [{"url": image}] if image else []}
    e.get = lambda k, default=None: data.get(k, default)
    return e


def scrape_valorant_official(db):
    html = net.get(VALORANT_NEWS).text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise ValueError("struktur halaman playvalorant.com berubah (__NEXT_DATA__ tidak ada)")
    items = []

    def walk(o):
        if isinstance(o, dict):
            if o.get("title") and (o.get("analytics") or {}).get("publishDate") and o.get("action"):
                items.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(m.group(1)))

    entries, seen = [], set()
    for it in items:
        url = ((it.get("action") or {}).get("payload") or {}).get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        published = datetime.fromisoformat(it["analytics"]["publishDate"].replace("Z", "+00:00"))
        desc = (it.get("description") or {}).get("body")
        image = ((it.get("imageMedia") or it.get("media") or {}).get("url"))
        entries.append(_entry(it["title"], url, published, desc, image))
    src = get_or_create_source(db, "VALORANT Resmi (playvalorant.com)", VALORANT_NEWS, "game", "web", "id")
    stored = store_entries(db, src, "game", entries)
    db.commit()
    return sum(n for _, n in stored)


def scrape_dota_official(db):
    data = net.get(DOTA_NEWS, params={"appid": 570, "count": 30, "maxlength": 600, "format": "json",
                                      "feeds": "steam_community_announcements"}).json()
    entries = []
    for n in data["appnews"]["newsitems"]:
        text = re.sub(r"\[/?[a-z0-9*]+(=[^\]]*)?\]|\{STEAM_CLAN_IMAGE\}\S*|<[^>]+>", " ", n.get("contents") or "")
        text = re.sub(r"\s+", " ", text).strip()
        published = datetime.fromtimestamp(n["date"], timezone.utc)
        entries.append(_entry(n["title"], n["url"], published, text or None))
    src = get_or_create_source(db, "Dota 2 Resmi (Steam)", "https://store.steampowered.com/news/app/570", "game",
                               "api", "en")
    stored = store_entries(db, src, "game", entries)
    db.commit()
    return sum(n for _, n in stored)


def tag_game_topics(db, days=7):
    """Tandai artikel game 7 hari terakhir dengan topik VALORANT/Dota 2 (sumber khusus atau kata kunci)."""
    feed_topic = {f["name"]: f["game_topic"] for f in NEWS_FEEDS if f.get("game_topic")}
    feed_topic.update(OFFICIAL_SOURCES)
    patterns = {k: re.compile(v["pattern"], re.I) for k, v in GAME_TOPICS.items()}
    rows = (db.query(Article.id, Article.title, Article.summary, Source.name)
            .join(Source, Source.id == Article.source_id)
            .filter(Article.category == "game", Article.scraped_at >= utcnow() - timedelta(days=days)).all())
    existing = {(a, c): how for a, c, how in db.query(ArticleAsset.article_id, ArticleAsset.asset_code,
                                                       ArticleAsset.matched_by)
                .filter(ArticleAsset.asset_type == "game", ArticleAsset.article_id.in_([r[0] for r in rows]))} \
        if rows else {}
    added, wanted = 0, set()
    for aid, title, summary, src_name in rows:
        tags = {}
        if src_name in feed_topic:
            tags[feed_topic[src_name]] = "query"
        for topic, rx in patterns.items():
            # di judul, atau ≥2 kali di ringkasan: sekadar disebut sekilas (mis. contoh lootbox) bukan berita topik itu
            if topic not in tags and (rx.search(title) or len(rx.findall(summary or "")) >= 2):
                tags[topic] = "text"
        for topic, how in tags.items():
            wanted.add((aid, topic))
            if (aid, topic) not in existing:
                db.add(ArticleAsset(article_id=aid, asset_type="game", asset_code=topic, matched_by=how))
                added += 1
    # tanda kata kunci lama yang tidak lolos aturan sekarang dibuang (kalau tidak, artikel salah topik tetap terpilih)
    stale = [k for k, how in existing.items() if how == "text" and k not in wanted]
    for aid, topic in stale:
        db.query(ArticleAsset).filter_by(article_id=aid, asset_type="game", asset_code=topic).delete()
    db.commit()
    log.info("Topik game: %d tanda baru, %d dibuang", added, len(stale))
    return added


def scrape_game_topics(db):
    total = 0
    for fn in (scrape_valorant_official, scrape_dota_official):
        try:
            n = fn(db)
            total += n
            log.info("%s: %d artikel baru", fn.__name__, n)
        except Exception as e:
            db.rollback()
            log.warning("%s gagal: %s", fn.__name__, e)
    tag_game_topics(db)
    return total
