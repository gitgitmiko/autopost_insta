"""Penautan artikel ke aset + skor sentimen pasar berbasis kamus (Indonesia & Inggris).

Kamus difokuskan pada bahasa pergerakan harga (naik/turun, bullish/bearish, net buy/sell, ARA/ARB)
dan peristiwa yang biasanya menggerakkan harga (laba, dividen, buyback, peretasan, gagal bayar, dst).
"""
import logging
import re
from datetime import timedelta

from .config import IDX_TICKERS, STOCK_ALIASES, TRACKED_COINS
from .db import Article, ArticleAsset, ArticleSentiment

log = logging.getLogger(__name__)
METHOD = "lexicon-v2"

# bobot 2 = sinyal kuat
POSITIVE = {
    2: ["melonjak", "melesat", "meroket", "terbang", "auto reject atas", "ARA", "rekor tertinggi", "all time high",
        "ATH", "surge", "surges", "soar", "soars", "skyrocket", "rockets", "record high", "zona hijau", "bullish",
        "laba melonjak", "rally", "reli", "top gainers", "top gainer"],
    1: ["naik", "kenaikan", "menguat", "penguatan", "rebound", "memantul", "pulih", "pemulihan", "menghijau", "cuan",
        "untung", "keuntungan", "laba bersih naik", "laba tumbuh", "tumbuh", "pertumbuhan", "positif", "optimis",
        "optimisme", "net buy", "beli bersih", "akumulasi", "diborong", "borong", "inflow", "dana asing masuk",
        "dividen", "buyback", "target harga naik", "rekomendasi beli", "upgrade", "outperform", "overweight",
        "tertinggi", "breakout", "gain", "gains", "rise", "rises", "rising", "climb", "climbs", "jump", "jumps",
        "higher", "recover", "recovers", "recovery", "approval", "approved", "adoption", "inflows", "buy signal",
        "accumulation", "uptrend", "tren naik", "melaju", "mendaki", "ekspansi", "investasi masuk", "stimulus",
        "suku bunga turun", "pemangkasan suku bunga", "rate cut", "rate cuts", "etf approval", "partnership",
        "kemitraan", "listing", "diserok", "serok", "jalur hijau", "lanjut naik", "buys", "buying",
        "beats estimate", "beat estimates", "inflow asing", "asing masuk"],
}
NEGATIVE = {
    2: ["anjlok", "ambles", "ambruk", "longsor", "terjun bebas", "rontok", "babak belur", "auto reject bawah", "ARB",
        "crash", "crashes", "plunge", "plunges", "plummet", "plummets", "collapse", "tumble", "tumbles", "zona merah",
        "bearish", "hack", "hacked", "exploit", "exploited", "diretas", "peretasan", "bangkrut", "pailit", "PKPU",
        "gagal bayar", "default", "fraud", "penipuan", "delisting", "suspensi", "sell-off", "selloff", "aksi jual"],
    1: ["turun", "penurunan", "melemah", "pelemahan", "merosot", "terkoreksi", "koreksi", "tertekan", "tekanan",
        "memerah", "rugi", "kerugian", "boncos", "negatif", "pesimis", "khawatir", "kekhawatiran", "waspada",
        "net sell", "jual bersih", "outflow", "dana asing keluar", "asing kabur", "dilepas", "target harga turun",
        "rekomendasi jual", "downgrade", "underperform", "underweight", "terendah", "breakdown", "drop", "drops",
        "fall", "falls", "falling", "slump", "slumps", "slide", "slides", "decline", "declines", "lower", "losses",
        "loss", "outflows", "liquidation", "liquidations", "likuidasi", "lawsuit", "gugatan", "sanksi", "sanctions",
        "ban", "larangan", "resesi", "recession", "inflasi tinggi", "suku bunga naik", "rate hike", "tarif",
        "tariff", "tariffs", "downtrend", "tren turun", "volatil", "ketidakpastian", "uncertainty", "fear", "panic",
        "panik", "investigasi", "investigation", "denda", "fined", "tersungkur", "terperosok", "lesu",
        "top losers", "top loser", "lanjut turun", "lanjut melemah", "outflow asing", "misses estimate",
        "sells", "selling pressure", "tekanan jual"],
}
NEGATIONS = {"tidak", "tak", "belum", "bukan", "tanpa", "not", "no", "never", "isn't", "didn't", "won't", "without"}

_SUFFIX = r"(?:nya|kan|lah)?"


def _compile():
    out = []
    for sign, terms in ((1, POSITIVE), (-1, NEGATIVE)):
        for w, words in terms.items():
            for t in words:
                # istilah huruf besar semua (ARA, ATH, PKPU) dicocokkan case-sensitive
                flags = 0 if t.isupper() else re.IGNORECASE
                rx = re.compile(r"(?<![\w-])" + re.escape(t) + _SUFFIX + r"(?![\w-])", flags)
                out.append((rx, t, w, sign))
    # frasa panjang dulu agar "suku bunga naik" (negatif) tidak juga dihitung "naik" (positif)
    return sorted(out, key=lambda x: -len(x[1]))


PATTERNS = _compile()


def _negated(text, start):
    prev = re.findall(r"[\w']+", text[max(0, start - 30):start].lower())[-2:]
    return any(p in NEGATIONS for p in prev)


def score_text(text):
    """Return (score, pos, neg, keywords). Skor = (pos-neg)/(pos+neg) di rentang -1..1."""
    pos = neg = 0.0
    hits = []
    taken = []  # rentang karakter yang sudah dipakai frasa yang lebih panjang
    for rx, term, weight, sign in PATTERNS:
        for m in rx.finditer(text):
            if m.group(0) in IDX_TICKERS:  # "CUAN" = kode saham, bukan kata "cuan"
                continue
            if any(m.start() < e and b < m.end() for b, e in taken):
                continue
            taken.append((m.start(), m.end()))
            s = -sign if _negated(text, m.start()) else sign
            if s > 0:
                pos += weight
            else:
                neg += weight
            hits.append(("+" if s > 0 else "-") + term)
    total = pos + neg
    return (0.0 if total == 0 else (pos - neg) / total), pos, neg, hits


def analyze_article(a):
    # judul diberi bobot 2x karena paling mencerminkan inti berita
    title_s = score_text(a.title or "")
    body_s = score_text(" ".join(filter(None, [a.summary, (a.content or "")[:3000]])))
    pos, neg = 2 * title_s[1] + body_s[1], 2 * title_s[2] + body_s[2]
    total = pos + neg
    score = 0.0 if total == 0 else round((pos - neg) / total, 4)
    # sedikit bukti -> redam skor agar 1 kata tidak langsung memberi +1/-1
    score = round(score * min(1.0, total / 3), 4)
    label = "positif" if score >= 0.2 else "negatif" if score <= -0.2 else "netral"
    keywords = ", ".join(dict.fromkeys(title_s[3] + body_s[3]))[:1000] or None
    return score, label, int(pos), int(neg), keywords


# --- penautan aset ---
def _asset_patterns():
    pats = []

    def add(asset_type, code, term):
        case_insensitive = len(term) >= 6 and (term.islower() or term.istitle() or " " in term) and not term.isupper()
        rx = re.compile(r"(?<![\w$^])\$?" + re.escape(term) + r"(?![\w])", re.IGNORECASE if case_insensitive else 0)
        pats.append((asset_type, code, rx))

    for code, aliases in STOCK_ALIASES.items():
        if not code.startswith("^"):
            add("saham", code, code)
        for al in aliases:
            add("saham", code, al)
    for coin_id, (sym, aliases) in TRACKED_COINS.items():
        add("crypto", coin_id, sym)
        for al in aliases:
            add("crypto", coin_id, al)
    return pats


ASSET_PATTERNS = _asset_patterns()


def find_assets(text):
    return {(t, c) for t, c, rx in ASSET_PATTERNS if rx.search(text)}


def reset_sentiment(db):
    """Hapus hasil sentimen agar semua artikel dianalisis ulang (mis. setelah kamus diubah)."""
    n = db.query(ArticleSentiment).delete()
    db.query(ArticleAsset).filter(ArticleAsset.matched_by == "text").delete()
    db.commit()
    log.info("Reset sentimen: %d baris dihapus", n)


def process_pending(db, batch=500):
    """Tautkan aset & hitung sentimen untuk artikel yang belum dianalisis.

    Dianalisis: artikel kategori saham/crypto, plus artikel kategori lain yang menyebut aset.
    """
    done = 0
    while True:
        rows = (db.query(Article).outerjoin(ArticleSentiment, ArticleSentiment.article_id == Article.id)
                .filter(ArticleSentiment.article_id.is_(None)).order_by(Article.id).limit(batch).all())
        if not rows:
            break
        existing = {(aid, t, c) for aid, t, c in db.query(ArticleAsset.article_id, ArticleAsset.asset_type,
                                                          ArticleAsset.asset_code)
                    .filter(ArticleAsset.article_id.in_([a.id for a in rows]))}
        for a in rows:
            text = " ".join(filter(None, [a.title, a.summary, (a.content or "")[:3000]]))
            assets = find_assets(text)
            for t, c in assets:
                if (a.id, t, c) not in existing:
                    db.add(ArticleAsset(article_id=a.id, asset_type=t, asset_code=c, matched_by="text"))
            relevant = a.category in ("saham", "crypto") or assets or any(k[0] == a.id for k in existing)
            score, label, pos, neg, kw = analyze_article(a) if relevant else (0.0, "netral", 0, 0, None)
            news_date = (a.published_at or a.scraped_at) + timedelta(hours=7)  # UTC -> WIB
            db.add(ArticleSentiment(article_id=a.id, news_date=news_date.date(), score=score, label=label,
                                    positive_hits=pos, negative_hits=neg, keywords=kw,
                                    method=METHOD if relevant else "skipped"))
            done += 1
        db.commit()
    log.info("Sentimen: %d artikel dianalisis", done)
    return done
