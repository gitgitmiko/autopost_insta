"""Harga harian saham & indeks Bursa Efek Indonesia via Yahoo Finance chart API."""
import logging
import time
from datetime import datetime, timedelta, timezone

from .. import net
from ..config import IDX_INDICES, IDX_TICKERS, STOCK_HISTORY_RANGE
from ..db import Stock, StockPrice, get_or_create_source, upsert, utcnow

log = logging.getLogger(__name__)
WIB = timezone(timedelta(hours=7))


def fetch_chart(symbol, rng):
    data = net.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                   params={"range": rng, "interval": "1d", "events": "div,split"},
                   headers={"User-Agent": "Mozilla/5.0"}).json()  # Yahoo membalas 429 untuk UA browser lengkap
    return data["chart"]["result"][0]


def scrape_stocks(db, rng=STOCK_HISTORY_RANGE, delay=0.5):
    get_or_create_source(db, "Yahoo Finance (IDX)", "https://finance.yahoo.com", "saham", "api", "en")
    symbols = [(t, f"{t}.JK", False) for t in IDX_TICKERS] + [(t, t, True) for t in IDX_INDICES]
    now, rows_total, failed = utcnow(), 0, []

    for ticker, ysym, is_index in symbols:
        try:
            res = fetch_chart(ysym, rng)
        except Exception as e:
            failed.append(ticker)
            log.warning("Saham %s gagal: %s", ticker, e)
            continue
        meta = res["meta"]
        upsert(db, Stock, [{
            "ticker": ticker, "name": IDX_INDICES.get(ticker) or meta.get("longName") or meta.get("shortName"),
            "is_index": int(is_index), "currency": meta.get("currency"), "exchange": meta.get("exchangeName"),
            "updated_at": now,
        }], keys=["ticker"], update_cols=["name", "currency", "exchange", "updated_at"])

        q = res["indicators"]["quote"][0]
        adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(res.get("timestamp", []))
        rows = []
        for i, ts in enumerate(res.get("timestamp") or []):
            if q["close"][i] is None:
                continue
            rows.append({
                "ticker": ticker, "trade_date": datetime.fromtimestamp(ts, WIB).date(),
                "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": q["close"][i],
                "adj_close": adj[i], "volume": q["volume"][i], "scraped_at": now,
            })
        upsert(db, StockPrice, rows, keys=["ticker", "trade_date"],
               update_cols=["open", "high", "low", "close", "adj_close", "volume", "scraped_at"])
        db.commit()
        rows_total += len(rows)
        time.sleep(delay)

    log.info("Saham: %d simbol, %d baris harga, gagal: %s", len(symbols) - len(failed), rows_total, failed or "-")
    return rows_total, failed
