"""CLI: python -m scraper [--category game politik crypto saham] [--full-text]"""
import argparse
import logging

from .config import CATEGORIES
from .db import ScrapeRun, Session, init_db, utcnow
from .media import cleanup_videos, fetch_recent_details, process_images
from .sentiment import process_pending, reset_sentiment
from .scrapers.crypto import scrape_crypto
from .scrapers.games import scrape_games, scrape_steam_promo
from .scrapers.game_topics import scrape_game_topics
from .scrapers.market_sentiment import scrape_crypto_daily, scrape_fear_greed, scrape_google_news
from .scrapers.news import scrape_feeds
from .scrapers.stocks import scrape_stocks

log = logging.getLogger("scraper")


def run_job(db, job, category, fn):
    run = ScrapeRun(job=job, category=category, started_at=utcnow())
    db.add(run)
    db.commit()
    try:
        items, msg = fn()
        run.status, run.items_new, run.message = ("partial" if msg else "success"), items, msg
    except Exception as e:
        db.rollback()
        log.exception("Job %s gagal", job)
        run.status, run.message = "failed", str(e)[:2000]
    run.finished_at = utcnow()
    db.commit()


def _posting_categories():
    try:
        from .social.settings import load_accounts
        return {a.category for a in load_accounts().values() if a.enabled}
    except Exception:  # file akun tidak ada / rusak: lewati
        return set()


def main():
    p = argparse.ArgumentParser(description="Scraper data game, politik, crypto & saham Indonesia")
    p.add_argument("-c", "--category", nargs="+", choices=CATEGORIES, default=list(CATEGORIES))
    p.add_argument("--full-text", action="store_true", help="ambil juga isi lengkap artikel berita")
    p.add_argument("--full-text-limit", type=int, default=50, help="maks. artikel yang diambil isinya per run")
    p.add_argument("--no-news", action="store_true", help="lewati berita, hanya data pasar/katalog")
    p.add_argument("--no-sentiment", action="store_true",
                   help="lewati berita per aset (Google News), Fear & Greed & analisis sentimen")
    p.add_argument("--no-images", action="store_true", help="jangan unduh gambar berita")
    p.add_argument("--reanalyze", action="store_true", help="hitung ulang sentimen semua artikel")
    p.add_argument("--sentiment-only", action="store_true", help="tanpa scraping, hanya analisis sentimen")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    init_db()
    cats = set() if args.sentiment_only else set(args.category)
    with Session() as db:
        if not args.no_news and cats:
            for cat in sorted(cats):
                run_job(db, "news", cat, lambda c=cat: (
                    sum(scrape_feeds(db, {c}, args.full_text, args.full_text_limit).values()), None))
        if not args.no_news and not args.no_images and cats:
            run_job(db, "images", None, lambda: (process_images(db), None))
            # isi lengkap + gambar/video di dalam artikel, hanya untuk kategori yang punya akun posting aktif
            detail_cats = cats & _posting_categories()
            if detail_cats:
                run_job(db, "article_media", ",".join(sorted(detail_cats)),
                        lambda: (fetch_recent_details(db, detail_cats), None))
            run_job(db, "video_cleanup", None, lambda: (cleanup_videos(db), None))
        if "crypto" in cats:
            run_job(db, "crypto_prices", "crypto", lambda: (scrape_crypto(db), None))
        if "saham" in cats:
            def stocks():
                n, failed = scrape_stocks(db)
                return n, (f"gagal: {', '.join(failed)}" if failed else None)
            run_job(db, "stock_prices", "saham", stocks)
        if "game" in cats:
            run_job(db, "game_catalog", "game", lambda: (scrape_games(db), None))
            run_job(db, "game_topics", "game", lambda: (scrape_game_topics(db), None))
            run_job(db, "steam_promo", "game", lambda: (scrape_steam_promo(db), None))

        market = sorted(cats & {"saham", "crypto"})
        if market and not args.no_sentiment:
            def gnews():
                n, failed = scrape_google_news(db, market)
                return n, (f"gagal: {', '.join(failed)}" if failed else None)
            run_job(db, "asset_news", ",".join(market), gnews)
            if "crypto" in cats:
                run_job(db, "crypto_fear_greed", "crypto", lambda: (scrape_fear_greed(db), None))
                run_job(db, "crypto_daily_prices", "crypto", lambda: (scrape_crypto_daily(db), None))
        if args.reanalyze:
            reset_sentiment(db)
        if not args.no_sentiment:
            run_job(db, "sentiment", None, lambda: (process_pending(db), None))
    log.info("Selesai.")


if __name__ == "__main__":
    main()
