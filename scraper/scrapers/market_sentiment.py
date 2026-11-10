"""Data pendukung sentimen: berita per aset (Google News), Crypto Fear & Greed, harga harian crypto."""
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser

from .. import net
from ..config import GOOGLE_NEWS_WINDOW, IDX_INDICES, IDX_TICKERS, STOCK_ALIASES, TRACKED_COINS
from ..db import (ArticleAsset, CryptoCoin, CryptoDailyPrice, MarketSentimentIndex, get_or_create_source,
                  upsert, utcnow)
from .news import store_entries

log = logging.getLogger(__name__)
GNEWS = "https://news.google.com/rss/search"


def _gnews_queries():
    """(asset_type, asset_code, kategori, query, hl, gl, ceid)"""
    win = f" when:{GOOGLE_NEWS_WINDOW}"
    for t in IDX_TICKERS:
        yield "saham", t, "saham", f'saham "{t}"{win}', "id", "ID", "ID:id"
    for t in IDX_INDICES:
        yield "saham", t, "saham", f'"{STOCK_ALIASES[t][0]}"{win}', "id", "ID", "ID:id"
    for coin_id, (sym, aliases) in TRACKED_COINS.items():
        name = aliases[0] if aliases else sym
        yield "crypto", coin_id, "crypto", f'"{name}" harga crypto{win}', "id", "ID", "ID:id"
        yield "crypto", coin_id, "crypto", f'"{name}" crypto price{win}', "en-US", "US", "US:en"


def _gnews_transform(entry, fields):
    # judul Google News berformat "Judul - Penerbit"; summary hanya berisi ulang judul
    publisher = (entry.get("source") or {}).get("title")
    if publisher and fields["title"].endswith(" - " + publisher):
        fields["title"] = fields["title"][: -len(publisher) - 3]
    fields["author"] = publisher[:255] if publisher else None
    fields["summary"] = None
    return fields


def scrape_google_news(db, categories=("saham", "crypto"), delay=1.0):
    srcs = {c: get_or_create_source(db, f"Google News - {c.title()} (per aset)", "https://news.google.com", c, "rss", "id")
            for c in ("saham", "crypto")}
    new_total, failed = 0, []
    for asset_type, code, category, q, hl, gl, ceid in _gnews_queries():
        if category not in categories:
            continue
        try:
            parsed = feedparser.parse(net.get(GNEWS, params={"q": q, "hl": hl, "gl": gl, "ceid": ceid}).content)
        except Exception as e:
            failed.append(code)
            log.warning("Google News gagal %s: %s", q, e)
            continue
        entries = [e for e in parsed.entries if e.get("link") and e.get("title")]
        stored = store_entries(db, srcs[category], category, entries, transform=_gnews_transform)
        linked = {aid for (aid,) in db.query(ArticleAsset.article_id).filter(
            ArticleAsset.asset_type == asset_type, ArticleAsset.asset_code == code,
            ArticleAsset.article_id.in_([a.id for a, _ in stored]))} if stored else set()
        for a, _ in stored:
            if a.id not in linked:
                db.add(ArticleAsset(article_id=a.id, asset_type=asset_type, asset_code=code, matched_by="query"))
        db.commit()
        new = sum(is_new for _, is_new in stored)
        new_total += new
        log.debug("Google News [%s] %s: %d entri, %d baru", code, q, len(entries), new)
        time.sleep(delay)
    log.info("Google News per aset: %d artikel baru, gagal: %s", new_total, failed or "-")
    return new_total, failed


def scrape_fear_greed(db):
    get_or_create_source(db, "Alternative.me Fear & Greed", "https://alternative.me/crypto/fear-and-greed-index/",
                         "crypto", "api", "en")
    has_data = db.query(MarketSentimentIndex.id).filter_by(name="crypto_fear_greed").first() is not None
    data = net.get("https://api.alternative.me/fng/", params={"limit": 30 if has_data else 0}).json()["data"]
    upsert(db, MarketSentimentIndex, [{
        "name": "crypto_fear_greed", "source": "alternative.me", "value": int(d["value"]),
        "classification": d["value_classification"],
        "index_date": datetime.fromtimestamp(int(d["timestamp"]), timezone.utc).date(),
    } for d in data], keys=["name", "index_date"], update_cols=["value", "classification"])
    db.commit()
    log.info("Fear & Greed: %d hari", len(data))
    return len(data)


def scrape_crypto_daily(db, delay=6.0):
    """Harga harian koin yang dilacak (CoinGecko market_chart). Titik 00:00 UTC = harga penutupan hari sebelumnya."""
    total = 0
    for coin_id, (sym, aliases) in TRACKED_COINS.items():
        has_data = db.query(CryptoDailyPrice.id).filter_by(coin_id=coin_id).first() is not None
        try:
            d = net.get(f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
                        params={"vs_currency": "idr", "days": 7 if has_data else 90, "interval": "daily"}).json()
        except Exception as e:
            log.warning("Harga harian %s gagal: %s", coin_id, e)
            time.sleep(delay)
            continue
        if db.get(CryptoCoin, coin_id) is None:
            db.add(CryptoCoin(id=coin_id, symbol=sym, name=aliases[0] if aliases else sym))
        caps = {ts: v for ts, v in d.get("market_caps", [])}
        vols = {ts: v for ts, v in d.get("total_volumes", [])}
        rows = {}
        for ts, price in d.get("prices", []):
            dt = datetime.fromtimestamp(ts / 1000, timezone.utc)
            day = dt.date() - timedelta(days=1) if (dt.hour, dt.minute) == (0, 0) else dt.date()
            rows[day] = {"coin_id": coin_id, "price_date": day, "price_idr": price,
                         "market_cap_idr": caps.get(ts), "volume_idr": vols.get(ts)}
        upsert(db, CryptoDailyPrice, list(rows.values()), keys=["coin_id", "price_date"],
               update_cols=["price_idr", "market_cap_idr", "volume_idr"])
        db.commit()
        total += len(rows)
        time.sleep(delay)  # batas rate CoinGecko publik
    log.info("Harga harian crypto: %d baris", total)
    return total
