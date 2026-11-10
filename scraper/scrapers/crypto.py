"""Harga crypto: CoinGecko (global, IDR) + Indodax (exchange Indonesia)."""
import logging
import time

from .. import net
from ..config import COINGECKO_PAGES
from ..db import CryptoCoin, CryptoPrice, get_or_create_source, upsert, utcnow

log = logging.getLogger(__name__)


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def scrape_coingecko(db, now):
    get_or_create_source(db, "CoinGecko", "https://www.coingecko.com", "crypto", "api", "en")
    coins = []
    for page in range(1, COINGECKO_PAGES + 1):
        coins += net.get("https://api.coingecko.com/api/v3/coins/markets", params={
            "vs_currency": "idr", "order": "market_cap_desc", "per_page": 250, "page": page,
            "price_change_percentage": "24h",
        }).json()
        time.sleep(2)

    upsert(db, CryptoCoin, [
        {"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"], "image_url": c.get("image"), "updated_at": now}
        for c in coins
    ], keys=["id"], update_cols=["symbol", "name", "image_url", "updated_at"])
    db.add_all(CryptoPrice(
        coin_id=c["id"], source="coingecko", price_idr=_num(c.get("current_price")),
        market_cap_idr=_num(c.get("market_cap")), volume_24h_idr=_num(c.get("total_volume")),
        high_24h_idr=_num(c.get("high_24h")), low_24h_idr=_num(c.get("low_24h")),
        change_24h_pct=_num(c.get("price_change_percentage_24h")), market_cap_rank=c.get("market_cap_rank"),
        captured_at=now,
    ) for c in coins)
    db.commit()
    log.info("CoinGecko: %d koin", len(coins))
    return {c["symbol"].upper(): c["id"] for c in sorted(coins, key=lambda c: c.get("market_cap_rank") or 1e9, reverse=True)}


def scrape_indodax(db, now, symbol_to_id):
    get_or_create_source(db, "Indodax", "https://indodax.com", "crypto", "api", "id")
    tickers = net.get("https://indodax.com/api/tickers").json()["tickers"]
    coins, prices = {}, []
    for pair, t in tickers.items():
        if not pair.endswith("_idr"):
            continue
        sym = pair[:-4].upper()
        coin_id = symbol_to_id.get(sym, f"indodax-{sym.lower()}")
        coins.setdefault(coin_id, {"id": coin_id, "symbol": sym, "name": None, "image_url": None, "updated_at": now})
        prices.append(CryptoPrice(
            coin_id=coin_id, source="indodax", price_idr=_num(t.get("last")),
            volume_24h_idr=_num(t.get("vol_idr")), high_24h_idr=_num(t.get("high")),
            low_24h_idr=_num(t.get("low")), captured_at=now,
        ))
    # hanya insert koin yang belum ada (jangan timpa nama dari CoinGecko)
    existing = {i for (i,) in db.query(CryptoCoin.id).filter(CryptoCoin.id.in_(list(coins))).all()}
    upsert(db, CryptoCoin, [c for k, c in coins.items() if k not in existing],
           keys=["id"], update_cols=["updated_at"])
    db.add_all(prices)
    db.commit()
    log.info("Indodax: %d pair IDR", len(prices))
    return len(prices)


def scrape_crypto(db):
    now = utcnow()
    symbol_to_id = {}
    total = 0
    try:
        symbol_to_id = scrape_coingecko(db, now)
        total += len(symbol_to_id)
    except Exception as e:
        db.rollback()
        log.warning("CoinGecko gagal: %s", e)
    total += scrape_indodax(db, now, symbol_to_id)
    return total
