"""Skema database & helper upsert (MySQL atau SQLite)."""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint, Index, create_engine,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/scraper.db")

Base = declarative_base()
LongText = Text().with_variant(Text(length=4294967295), "mysql")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Source(Base):
    __tablename__ = "sources"
    id = Column(Integer, primary_key=True)
    name = Column(String(150), nullable=False, unique=True)
    url = Column(String(500), nullable=False)
    category = Column(String(20), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # rss | api
    lang = Column(String(5))
    created_at = Column(DateTime, default=utcnow)


class Article(Base):
    __tablename__ = "articles"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)
    category = Column(String(20), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), nullable=False)
    url_hash = Column(String(64), nullable=False, unique=True)
    summary = Column(Text)
    content = Column(LongText)
    author = Column(String(255))
    tags = Column(String(1000))
    image_url = Column(String(1000))
    published_at = Column(DateTime, index=True)
    scraped_at = Column(DateTime, default=utcnow)
    details_fetched_at = Column(DateTime, index=True)  # isi lengkap + gambar/video di dalam artikel sudah diambil


class CryptoCoin(Base):
    __tablename__ = "crypto_coins"
    id = Column(String(100), primary_key=True)  # id CoinGecko / pair Indodax
    symbol = Column(String(30), nullable=False, index=True)
    name = Column(String(150))
    image_url = Column(String(500))
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class CryptoPrice(Base):
    __tablename__ = "crypto_prices"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    coin_id = Column(String(100), ForeignKey("crypto_coins.id"), nullable=False)
    source = Column(String(30), nullable=False)  # coingecko | indodax
    price_idr = Column(Numeric(30, 8))
    market_cap_idr = Column(Numeric(32, 2))
    volume_24h_idr = Column(Numeric(32, 2))
    high_24h_idr = Column(Numeric(30, 8))
    low_24h_idr = Column(Numeric(30, 8))
    change_24h_pct = Column(Float)
    market_cap_rank = Column(Integer)
    captured_at = Column(DateTime, nullable=False, default=utcnow)
    __table_args__ = (Index("ix_crypto_prices_coin_time", "coin_id", "captured_at"),)


class Stock(Base):
    __tablename__ = "stocks"
    ticker = Column(String(20), primary_key=True)  # contoh: BBCA, ^JKSE
    name = Column(String(255))
    is_index = Column(Integer, default=0)
    currency = Column(String(5))
    exchange = Column(String(20))
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class StockPrice(Base):
    __tablename__ = "stock_prices"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    ticker = Column(String(20), ForeignKey("stocks.ticker"), nullable=False)
    trade_date = Column(Date, nullable=False)
    open = Column(Numeric(20, 4))
    high = Column(Numeric(20, 4))
    low = Column(Numeric(20, 4))
    close = Column(Numeric(20, 4))
    adj_close = Column(Numeric(20, 4))
    volume = Column(BigInteger)
    scraped_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("ticker", "trade_date", name="uq_stock_day"),)


class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    source = Column(String(30), nullable=False)  # freetogame | steam
    external_id = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False, index=True)
    genre = Column(String(100))
    platform = Column(String(100))
    publisher = Column(String(255))
    developer = Column(String(255))
    release_date = Column(Date)
    description = Column(Text)
    url = Column(String(500))
    thumbnail_url = Column(String(500))
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_game_source_ext"),)


class GameStoreSnapshot(Base):
    __tablename__ = "game_store_snapshots"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False, index=True)
    list_type = Column(String(30), nullable=False)  # specials | top_sellers | new_releases | coming_soon | promo_picks
    position = Column(Integer)
    currency = Column(String(5))
    original_price = Column(Numeric(14, 2))
    final_price = Column(Numeric(14, 2))
    discount_pct = Column(Integer)
    rating_pct = Column(Integer)  # % ulasan positif (hanya list_type "promo_picks")
    reviews = Column(Integer)  # jumlah ulasan pengguna
    captured_at = Column(DateTime, nullable=False, default=utcnow)


class ArticleAsset(Base):
    """Artikel X membahas aset Y (saham/indeks atau koin)."""
    __tablename__ = "article_assets"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    article_id = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("articles.id"), nullable=False)
    asset_type = Column(String(10), nullable=False)  # saham | crypto
    asset_code = Column(String(100), nullable=False)  # ticker (BBCA, ^JKSE) / id CoinGecko (bitcoin)
    matched_by = Column(String(10), nullable=False)  # query (Google News per aset) | text (kode/alias di teks)
    __table_args__ = (UniqueConstraint("article_id", "asset_type", "asset_code", name="uq_article_asset"),
                      Index("ix_article_assets_asset", "asset_type", "asset_code"))


class ArticleSentiment(Base):
    __tablename__ = "article_sentiments"
    article_id = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("articles.id"), primary_key=True)
    news_date = Column(Date, index=True)  # tanggal terbit dalam WIB
    score = Column(Float, nullable=False)  # -1 (sangat negatif/bearish) .. +1 (sangat positif/bullish)
    label = Column(String(10), nullable=False, index=True)  # positif | negatif | netral
    positive_hits = Column(Integer, default=0)
    negative_hits = Column(Integer, default=0)
    keywords = Column(String(1000))  # kata kunci yang memicu skor, mis. "+menguat, -net sell"
    method = Column(String(30), nullable=False)
    analyzed_at = Column(DateTime, default=utcnow)


class MarketSentimentIndex(Base):
    __tablename__ = "market_sentiment_index"
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)  # crypto_fear_greed
    index_date = Column(Date, nullable=False)
    value = Column(Integer, nullable=False)  # 0 = extreme fear, 100 = extreme greed
    classification = Column(String(30))
    source = Column(String(50))
    __table_args__ = (UniqueConstraint("name", "index_date", name="uq_sentiment_index_day"),)


class CryptoDailyPrice(Base):
    __tablename__ = "crypto_daily_prices"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    coin_id = Column(String(100), ForeignKey("crypto_coins.id"), nullable=False)
    price_date = Column(Date, nullable=False)  # tanggal UTC
    price_idr = Column(Numeric(30, 8))
    market_cap_idr = Column(Numeric(32, 2))
    volume_idr = Column(Numeric(32, 2))
    __table_args__ = (UniqueConstraint("coin_id", "price_date", name="uq_crypto_day"),)


class ArticleImage(Base):
    """File gambar berita yang sudah diunduh (path relatif terhadap IMAGE_DIR)."""
    __tablename__ = "article_images"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    article_id = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("articles.id"), nullable=False,
                        index=True)
    kind = Column(String(10), nullable=False, default="main")  # main (gambar utama) | body (gambar di isi artikel)
    position = Column(Integer, nullable=False, default=0)  # urutan gambar body di artikel
    source_url = Column(String(1000), nullable=False)
    file_path = Column(String(300))
    sha256 = Column(String(64))
    mime = Column(String(30))
    width = Column(Integer)
    height = Column(Integer)
    bytes = Column(Integer)
    status = Column(String(15), nullable=False)  # ok | failed
    error = Column(String(500))
    downloaded_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("article_id", "kind", "position", name="uq_article_image_pos"),)


class ArticleYoutube(Base):
    """Video YouTube yang disematkan di artikel. Hanya metadata (oEmbed resmi YouTube) — videonya tidak diunduh."""
    __tablename__ = "article_youtube"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    article_id = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("articles.id"), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    video_id = Column(String(20), nullable=False, index=True)
    url = Column(String(100), nullable=False)
    title = Column(String(500))
    channel = Column(String(255))
    channel_url = Column(String(500))
    thumbnail_url = Column(String(500))
    fetched_at = Column(DateTime)
    __table_args__ = (UniqueConstraint("article_id", "video_id", name="uq_article_youtube"),)


class SocialPost(Base):
    """Postingan media sosial: satu baris per akun per slot per hari per platform.

    status: prepared (konten siap, n8n sedang memposting) | posted | failed | skipped
    """
    __tablename__ = "social_posts"
    id = Column(Integer, primary_key=True)
    account = Column(String(50), nullable=False)  # kunci akun di social_accounts.json, mis. "game"
    slot = Column(String(40), nullable=False)  # "08:00-news" / "manual-081530-news"
    slot_date = Column(Date, nullable=False)  # tanggal WIB
    platform = Column(String(15), nullable=False)  # instagram | facebook
    content_type = Column(String(20), nullable=False)  # news | steam_deals | recap_saham | recap_crypto
    article_id = Column(BigInteger().with_variant(Integer, "sqlite"), ForeignKey("articles.id"))
    content_key = Column(String(500))  # sidik jari konten non-berita (mis. daftar promo Steam)
    status = Column(String(15), nullable=False)
    caption = Column(Text)
    image_url = Column(String(500))  # slide pertama
    slides = Column(Text)  # JSON list URL semua slide (carousel)
    comments = Column(Text)  # JSON list komentar lanjutan caption
    platform_post_id = Column(String(100))
    permalink = Column(String(500))
    error = Column(Text)
    attempts = Column(Integer, default=1)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("account", "slot", "slot_date", "platform", name="uq_social_slot_day"),
                      Index("ix_social_posts_account_status", "account", "status"))


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    id = Column(Integer, primary_key=True)
    job = Column(String(50), nullable=False)
    category = Column(String(20))
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime)
    status = Column(String(20))  # success | partial | failed
    items_new = Column(Integer, default=0)
    message = Column(Text)


if DATABASE_URL.startswith("sqlite:///"):
    os.makedirs(os.path.dirname(DATABASE_URL[len("sqlite:///"):]) or ".", exist_ok=True)
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
Session = sessionmaker(bind=engine, future=True)


# Sentimen harian per aset vs perubahan harga pada hari yang sama (saham: hari bursa, crypto: hari UTC).
VIEWS = {
    "v_asset_daily_sentiment": """
        WITH s AS (
            SELECT aa.asset_type, aa.asset_code, se.news_date AS day, COUNT(*) AS n_articles,
                   ROUND(AVG(se.score), 4) AS avg_sentiment,
                   SUM(CASE WHEN se.label = 'positif' THEN 1 ELSE 0 END) AS n_positif,
                   SUM(CASE WHEN se.label = 'negatif' THEN 1 ELSE 0 END) AS n_negatif,
                   SUM(CASE WHEN se.label = 'netral' THEN 1 ELSE 0 END) AS n_netral
            FROM article_assets aa
            JOIN article_sentiments se ON se.article_id = aa.article_id
            WHERE se.method <> 'skipped'
            GROUP BY aa.asset_type, aa.asset_code, se.news_date
        ), p AS (
            SELECT 'saham' AS asset_type, ticker AS asset_code, trade_date AS day, close AS price,
                   100.0 * (close / LAG(close) OVER (PARTITION BY ticker ORDER BY trade_date) - 1) AS change_pct
            FROM stock_prices
            UNION ALL
            SELECT 'crypto', coin_id, price_date, price_idr,
                   100.0 * (price_idr / LAG(price_idr) OVER (PARTITION BY coin_id ORDER BY price_date) - 1)
            FROM crypto_daily_prices
        )
        SELECT s.asset_type, s.asset_code, s.day, s.n_articles, s.avg_sentiment, s.n_positif, s.n_negatif,
               s.n_netral, p.price, ROUND(p.change_pct, 3) AS price_change_pct,
               CASE WHEN p.change_pct IS NULL THEN NULL
                    WHEN p.change_pct > 0 AND s.avg_sentiment > 0 THEN 'searah'
                    WHEN p.change_pct < 0 AND s.avg_sentiment < 0 THEN 'searah'
                    WHEN s.avg_sentiment = 0 OR p.change_pct = 0 THEN 'netral'
                    ELSE 'berlawanan' END AS sentiment_vs_price
        FROM s LEFT JOIN p ON p.asset_type = s.asset_type AND p.asset_code = s.asset_code AND p.day = s.day
    """,
    "v_asset_news_sentiment": """
        SELECT aa.asset_type, aa.asset_code, se.news_date, a.published_at, se.label, se.score, a.title,
               COALESCE(a.author, src.name) AS publisher, se.keywords, a.url, aa.matched_by
        FROM article_assets aa
        JOIN articles a ON a.id = aa.article_id
        JOIN sources src ON src.id = a.source_id
        JOIN article_sentiments se ON se.article_id = a.id
        WHERE se.method <> 'skipped'
    """,
}


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for name, sql in VIEWS.items():
            conn.exec_driver_sql(f"DROP VIEW IF EXISTS {name}")
            conn.exec_driver_sql(f"CREATE VIEW {name} AS {sql}")


def upsert(session, model, rows, keys, update_cols):
    """INSERT ... ON DUPLICATE KEY UPDATE (MySQL) / ON CONFLICT (SQLite)."""
    if not rows:
        return
    table = model.__table__
    if engine.dialect.name == "mysql":
        stmt = mysql_insert(table).values(rows)
        stmt = stmt.on_duplicate_key_update({c: stmt.inserted[c] for c in update_cols})
    else:
        stmt = sqlite_insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(index_elements=keys, set_={c: stmt.excluded[c] for c in update_cols})
    session.execute(stmt)


def get_or_create_source(session, name, url, category, kind, lang=None):
    src = session.query(Source).filter_by(name=name).one_or_none()
    if src is None:
        src = Source(name=name, url=url, category=category, kind=kind, lang=lang)
        session.add(src)
        session.flush()
    return src
