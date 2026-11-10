"""Pemilihan konten untuk posting: berita terbaik per kategori, rekap saham & rekap crypto."""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func

from ..config import NEWS_FEEDS, TOPIC_KEYWORDS, TRACKED_COINS
from ..media import ensure_image
from ..db import (Article, ArticleAsset, ArticleSentiment, CryptoCoin, CryptoPrice, Game, GameStoreSnapshot,
                  MarketSentimentIndex, SocialPost, Source, Stock, StockPrice, utcnow)
from . import settings


@dataclass
class NewsItem:
    article: Article
    source: Source
    sentiment: ArticleSentiment | None
    assets: list
    image_path: str | None
    body: str
    photo_used: bool = False  # diisi saat kartu dibuat: foto berita benar-benar dipakai
    topic: str | None = None  # topik game khusus (valorant/dota2) bila diambil untuk slot topik


@dataclass
class StockRecap:
    day: date
    ihsg_close: float
    ihsg_change: float
    gainers: list  # [(ticker, close, pct)]
    losers: list
    sentiment: dict  # positif/negatif/netral -> jumlah
    headlines: list = field(default_factory=list)  # [(title, publisher)]


@dataclass
class CryptoRecap:
    captured_at: datetime
    coins: list  # [(symbol, name, price_idr, change_24h)]
    fear_greed: tuple | None  # (value, classification, value_kemarin)
    sentiment: dict
    headlines: list = field(default_factory=list)


STOPWORDS = {"dan", "yang", "di", "ke", "dari", "ini", "itu", "untuk", "dengan", "pada", "the", "and", "for", "of",
             "to", "in", "on", "as", "is", "a", "an", "hari", "jadi", "akan", "usai", "soal", "bisa", "lagi"}


def words(t):
    return {w for w in re.findall(r"[a-z0-9]+", (t or "").lower()) if len(w) > 2 and w not in STOPWORDS}


def similar(a, b):
    """Kemiripan Jaccard kata (0..1). Menerima string atau set kata."""
    a = a if isinstance(a, set) else words(a)
    b = b if isinstance(b, set) else words(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def _sentences(text, max_chars):
    """Potong teks di batas kalimat."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > max_chars * 0.4 else cut.rsplit(" ", 1)[0] + "…"


def article_body(a, max_chars=600):
    """Ringkasan untuk caption/kartu: summary RSS, atau paragraf awal isi artikel."""
    summary = (a.summary or "").strip()
    if summary and similar(summary[:len(a.title) + 10], a.title) > 0.8:
        summary = summary[len(a.title):].strip(" -–:")
    if len(summary) < 80 and a.content:
        summary = a.content
    summary = re.sub(r"\((Foto|Ilustrasi|Sumber|Gambar)[^)]*\)", "", summary, flags=re.I)
    summary = re.sub(r"\s*\[(…|\.\.\.|&hellip;)\]\s*$", "…", summary.strip())
    summary = re.sub(r"\s*(The post .* appeared first on .*|Artikel .* pertama kali tampil di .*)$", "", summary)
    # buang prefiks lokasi kantor berita, mis. "Jakarta, CNBC Indonesia -" / "Jakarta (ANTARA) -"
    summary = re.sub(r"^[A-Z][\w .]{1,30}(,| \()[\w .]{2,30}\)? ?[-–—] ?", "", summary)
    return _sentences(summary, max_chars)


SPAM = re.compile(r"presale|pre-sale|\b\d{2,4}x\b|next 100|best crypto to buy|price prediction|sponsored",
                  re.I)
# Untuk akun game: panduan, artikel belanja/promo, dan "kode redeem" bukan berita.
NOISE = {
    "game": re.compile(r"^(how to|where to|when to|all |every )|\bguides?\b|walkthrough|\bdeals?\b|% off|"
                       r"\bsave \$|best .* (to buy|deals)|kode redeem|redeem code|codes? \(|cara (mendapatkan|main)",
                       re.I),
}
FEED_TOPIC = {f["name"]: re.compile(TOPIC_KEYWORDS[f["topic"]], re.I) for f in NEWS_FEEDS if f.get("topic")}


def posted_article_ids(db, account):
    return {i for (i,) in db.query(SocialPost.article_id)
            .filter(SocialPost.account == account, SocialPost.article_id.isnot(None),
                    SocialPost.status.in_(("posted", "prepared"))).distinct()}


def pick_news(db, category, account, languages=("id", "en"), now_utc=None, exclude_ids=(), topic=None,
              max_age_hours=None):
    """Pilih berita terbaik untuk satu akun: baru, sesuai urutan bahasa, diberitakan banyak media,
    belum pernah diposting akun ini, dan bukan topik yang sama dengan postingan 3 hari terakhir."""
    now_utc = now_utc or utcnow()
    since = now_utc - timedelta(hours=max_age_hours or settings.NEWS_MAX_AGE_HOURS)
    q = (db.query(Article, Source).join(Source, Source.id == Article.source_id)
         .filter(Article.category == category, Article.published_at >= since,
                 Article.published_at <= now_utc + timedelta(minutes=5),
                 ~Article.url.like("https://news.google.com/%")))
    if topic:  # hanya artikel yang ditandai topik game ini (lihat scrapers/game_topics.py)
        q = q.filter(Article.id.in_(db.query(ArticleAsset.article_id)
                                    .filter(ArticleAsset.asset_type == "game", ArticleAsset.asset_code == topic)))
    rows = q.order_by(Article.published_at.desc()).limit(200).all()
    if not rows:
        return None

    used = posted_article_ids(db, account) | set(exclude_ids)
    recent_titles = [words(t) for (t,) in db.query(Article.title).join(SocialPost, SocialPost.article_id == Article.id)
                     .filter(SocialPost.account == account, SocialPost.status.in_(("posted", "prepared")),
                             SocialPost.created_at >= now_utc - timedelta(days=3))]
    # semua judul 24 jam terakhir untuk mengukur seberapa ramai topiknya
    pool = [words(t) for (t,) in db.query(Article.title).filter(Article.published_at >= now_utc - timedelta(hours=24))]
    noise = NOISE.get(category)
    # variasi sumber: kurangi skor media yang baru saja diposting akun ini (dan di batch preview)
    recent_sources = [sid for (sid,) in db.query(Article.source_id).join(SocialPost, SocialPost.article_id == Article.id)
                      .filter(SocialPost.account == account).order_by(SocialPost.id.desc()).limit(3)]
    recent_sources += [sid for (sid,) in db.query(Article.source_id).filter(Article.id.in_(list(exclude_ids)))]
    lang_bonus = {lang: 8 * (len(languages) - i - 1) for i, lang in enumerate(languages)}

    best, best_score = None, float("-inf")
    for a, src in rows:
        w = words(a.title)
        if (a.id in used or len(a.title) < 25 or src.lang not in lang_bonus or SPAM.search(a.title)
                or (noise and noise.search(a.title))
                or (src.name in FEED_TOPIC and not FEED_TOPIC[src.name].search(f"{a.title} {a.summary or ''}"))
                or any(similar(w, t) > 0.5 for t in recent_titles)):
            continue
        body = article_body(a)
        coverage = sum(1 for t in pool if 0.3 < similar(w, t) < 1.0)
        hours_old = (now_utc - a.published_at).total_seconds() / 3600
        # slot topik memakai jendela waktu lebih panjang: kurangi bobot usia, utamakan yang bergambar
        age_weight = 0.25 * settings.NEWS_MAX_AGE_HOURS / (max_age_hours or settings.NEWS_MAX_AGE_HOURS)
        score = (lang_bonus[src.lang] + 2 * min(coverage, 5) + (len(body) >= 120) - age_weight * hours_old
                 + (2 if topic else 0.5) * bool(a.image_url) - 1.5 * recent_sources.count(src.id))
        if score > best_score:
            best, best_score = (a, src, body), score
    if not best:
        return None

    a, src, body = best
    sent = db.get(ArticleSentiment, a.id)
    assets = [c for (c,) in db.query(ArticleAsset.asset_code).filter(ArticleAsset.article_id == a.id)]
    return NewsItem(a, src, sent, assets, ensure_image(db, a), body, topic=topic)


def load_news_item(db, article_id, topic=None):
    a = db.get(Article, article_id)
    return NewsItem(a, db.get(Source, a.source_id), db.get(ArticleSentiment, a.id),
                    [c for (c,) in db.query(ArticleAsset.asset_code).filter_by(article_id=a.id)],
                    ensure_image(db, a), article_body(a), topic=topic)


@dataclass
class SteamDeals:
    captured_at: datetime
    items: list  # [{appid, title, final, orig, disc, rating, reviews}] urut peringkat
    key: str  # appid berurutan "a,b,c" — untuk rotasi & deteksi daftar yang sama


def steam_deals(db, n=16):
    """Pilihan promo Steam terbaru (snapshot "promo_picks" dari scrapers.games.scrape_steam_promo)."""
    ts = db.query(func.max(GameStoreSnapshot.captured_at)).filter(GameStoreSnapshot.list_type == "promo_picks").scalar()
    if ts is None:
        return None
    rows = (db.query(Game.external_id, Game.title, GameStoreSnapshot.final_price, GameStoreSnapshot.original_price,
                     GameStoreSnapshot.discount_pct, GameStoreSnapshot.rating_pct, GameStoreSnapshot.reviews)
            .join(Game, Game.id == GameStoreSnapshot.game_id)
            .filter(GameStoreSnapshot.captured_at == ts, GameStoreSnapshot.list_type == "promo_picks")
            .order_by(GameStoreSnapshot.position).limit(n).all())
    if not rows:
        return None
    items = [{"appid": a, "title": t, "final": float(f or 0), "orig": float(o or 0), "disc": int(d or 0),
              "rating": r, "reviews": rv} for a, t, f, o, d, r, rv in rows]
    return SteamDeals(ts, items, ",".join(i["appid"] for i in items))


def publisher_name(source_name):
    """Nama media yang ringkas: "CNBC Indonesia - Market" → "CNBC Indonesia",
    "VALORANT Resmi (playvalorant.com)" → "VALORANT Resmi"."""
    return re.sub(r"\s*\(.*\)$", "", source_name.split(" - ")[0]).strip()


def _sentiment_counts(q):
    out = {"positif": 0, "negatif": 0, "netral": 0}
    for label, n in q.group_by(ArticleSentiment.label):
        out[label] = n
    return out


def _headlines(db, asset_filter, since_utc, n=3):
    q = (db.query(Article.title, Article.author, Source.name, Article.url)
         .join(Source, Source.id == Article.source_id)
         .join(ArticleSentiment, ArticleSentiment.article_id == Article.id)
         .filter(Article.published_at >= since_utc, asset_filter)
         .order_by((~Article.url.like("https://news.google.com/%")).desc(), (Source.lang == "id").desc(),
                   Article.published_at.desc()).limit(150))
    out = []
    for title, author, src_name, url in q:
        # Google News: penerbit asli ada di kolom author; sumber lain: nama media
        pub = author if url.startswith("https://news.google.com/") and author else publisher_name(src_name)
        if SPAM.search(title):
            continue
        if not any(similar(title, t) > 0.4 for t, _ in out):
            out.append((title, pub))
        if len(out) == n:
            break
    return out


def stock_recap(db, day=None, force=False):
    """Rekap hari bursa `day` (WIB). None jika belum ada data penutupan untuk hari itu."""
    day = day or datetime.now(settings.TZ).date()
    last = db.query(func.max(StockPrice.trade_date)).filter(StockPrice.ticker == "^JKSE").scalar()
    if last is None or (last != day and not force):
        return None
    day = last

    def two_days(ticker):
        r = (db.query(StockPrice.close).filter(StockPrice.ticker == ticker, StockPrice.trade_date <= day)
             .order_by(StockPrice.trade_date.desc()).limit(2).all())
        return (float(r[0][0]), float(r[1][0])) if len(r) == 2 else None

    ihsg = two_days("^JKSE")
    if not ihsg:
        return None
    changes = []
    for (t,) in db.query(Stock.ticker).filter(Stock.is_index == 0):
        p = two_days(t)
        has_today = db.query(StockPrice.id).filter_by(ticker=t, trade_date=day).first()
        if p and has_today and p[1]:
            changes.append((t, p[0], 100 * (p[0] / p[1] - 1)))
    changes.sort(key=lambda x: x[2], reverse=True)

    sent = _sentiment_counts(db.query(ArticleSentiment.label, func.count())
                             .join(Article, Article.id == ArticleSentiment.article_id)
                             .filter(Article.category == "saham", ArticleSentiment.news_date == day,
                                     ArticleSentiment.method != "skipped"))
    start_utc = datetime.combine(day, datetime.min.time()) - timedelta(hours=7)
    heads = _headlines(db, Article.id.in_(db.query(ArticleAsset.article_id)
                                          .filter(ArticleAsset.asset_code == "^JKSE")), start_utc)
    return StockRecap(day, ihsg[0], 100 * (ihsg[0] / ihsg[1] - 1), [c for c in changes[:5] if c[2] > 0],
                      [c for c in changes[::-1][:5] if c[2] < 0], sent, heads)


def crypto_recap(db, n_coins=8):
    ts = db.query(func.max(CryptoPrice.captured_at)).filter(CryptoPrice.source == "coingecko").scalar()
    if ts is None:
        return None
    rows = (db.query(CryptoCoin.id, CryptoCoin.symbol, CryptoCoin.name, CryptoPrice.price_idr,
                     CryptoPrice.change_24h_pct, CryptoPrice.market_cap_rank)
            .join(CryptoPrice, CryptoPrice.coin_id == CryptoCoin.id)
            .filter(CryptoPrice.source == "coingecko", CryptoPrice.captured_at == ts,
                    CryptoCoin.id.in_(list(TRACKED_COINS)))
            .order_by(CryptoPrice.market_cap_rank).limit(n_coins).all())
    coins = [(sym, name, float(p or 0), float(ch or 0)) for _, sym, name, p, ch, _ in rows]

    fg = (db.query(MarketSentimentIndex.value, MarketSentimentIndex.classification)
          .filter_by(name="crypto_fear_greed").order_by(MarketSentimentIndex.index_date.desc()).limit(2).all())
    fear_greed = (fg[0][0], fg[0][1], fg[1][0] if len(fg) > 1 else None) if fg else None

    since = utcnow() - timedelta(hours=24)
    sent = _sentiment_counts(db.query(ArticleSentiment.label, func.count())
                             .join(Article, Article.id == ArticleSentiment.article_id)
                             .filter(Article.category == "crypto", Article.published_at >= since,
                                     ArticleSentiment.method != "skipped"))
    heads = _headlines(db, Article.category == "crypto", since)
    return CryptoRecap(ts, coins, fear_greed, sent, heads)

