"""Data game: katalog FreeToGame + daftar toko Steam Indonesia (harga IDR)."""
import logging
import re
from datetime import date, timedelta

from .. import net
from bs4 import BeautifulSoup

from ..db import Game, GameStoreSnapshot, SocialPost, get_or_create_source, upsert, utcnow

log = logging.getLogger(__name__)
STEAM_LISTS = ("specials", "top_sellers", "new_releases", "coming_soon")


def _date(s):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def scrape_freetogame(db, now):
    get_or_create_source(db, "FreeToGame", "https://www.freetogame.com", "game", "api", "en")
    games = net.get("https://www.freetogame.com/api/games").json()
    upsert(db, Game, [{
        "source": "freetogame", "external_id": str(g["id"]), "title": g["title"][:255],
        "genre": g.get("genre"), "platform": g.get("platform"), "publisher": g.get("publisher"),
        "developer": g.get("developer"), "release_date": _date(g.get("release_date")),
        "description": g.get("short_description"), "url": g.get("game_url"),
        "thumbnail_url": g.get("thumbnail"), "updated_at": now,
    } for g in games], keys=["source", "external_id"],
        update_cols=["title", "genre", "platform", "publisher", "developer", "release_date",
                     "description", "url", "thumbnail_url", "updated_at"])
    db.commit()
    log.info("FreeToGame: %d game", len(games))
    return len(games)


def scrape_steam(db, now):
    get_or_create_source(db, "Steam Store (ID)", "https://store.steampowered.com", "game", "api", "en")
    data = net.get("https://store.steampowered.com/api/featuredcategories",
                   params={"cc": "id", "l": "english"}).json()
    items = [(lst, pos, it) for lst in STEAM_LISTS
             for pos, it in enumerate(data.get(lst, {}).get("items", []), 1) if it.get("id")]

    upsert(db, Game, [{
        "source": "steam", "external_id": str(it["id"]), "title": it["name"][:255], "platform": "PC (Steam)",
        "url": f"https://store.steampowered.com/app/{it['id']}", "thumbnail_url": it.get("header_image"),
        "updated_at": now,
    } for _, _, it in items], keys=["source", "external_id"], update_cols=["title", "thumbnail_url", "updated_at"])
    ids = {gid: pk for pk, gid in db.query(Game.id, Game.external_id)
           .filter(Game.source == "steam", Game.external_id.in_([str(it["id"]) for _, _, it in items]))}

    cents = lambda v: None if v is None else v / 100  # Steam memberi harga dalam satuan sen
    db.add_all(GameStoreSnapshot(
        game_id=ids[str(it["id"])], list_type=lst, position=pos, currency=it.get("currency"),
        original_price=cents(it.get("original_price")), final_price=cents(it.get("final_price")),
        discount_pct=it.get("discount_percent"), captured_at=now,
    ) for lst, pos, it in items)
    db.commit()
    log.info("Steam: %d entri toko", len(items))
    return len(items)


def scrape_games(db):
    now, total = utcnow(), 0
    for fn in (scrape_freetogame, scrape_steam):
        try:
            total += fn(db, now)
        except Exception as e:
            db.rollback()
            log.warning("%s gagal: %s", fn.__name__, e)
    return total


# ---------------------------------------------------------------- pilihan promo Steam (untuk postingan)
PROMO_MIN_DISCOUNT = 60
PROMO_MIN_RATING = 80
PROMO_MIN_REVIEWS = 1000
PROMO_COUNT = 16
NOT_A_GAME = re.compile(r"soundtrack|\bost\b|bundle|\bpack\b|\bdlc\b|season pass|upgrade|artbook|demo|"
                        r"supporter|expansion pass|deluxe upgrade", re.I)


def _franchise(title):
    """Kunci kasar waralaba agar satu seri (mis. Resident Evil) tidak memenuhi seluruh daftar."""
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower().split(":")[0].split("/")[0]).split()
    words = [w for w in words if not w.isdigit() and w not in {"the", "a", "of"}]
    return " ".join(words[:2])


def _search_specials(start, count=100):
    r = net.get("https://store.steampowered.com/search/results/", params={
        "query": "", "start": start, "count": count, "specials": 1, "category1": 998, "sort_by": "Reviews_DESC",
        "cc": "id", "l": "english", "infinite": 1, "ignore_preferences": 1})
    soup = BeautifulSoup(r.json()["results_html"], "lxml")
    out = []
    for a in soup.select("a.search_result_row"):
        blk = a.select_one(".search_discount_block")
        if not blk or not blk.get("data-discount"):
            continue
        orig = a.select_one(".discount_original_price")
        rev = a.select_one(".search_review_summary")
        m = re.search(r"(\d+)% of the ([\d,]+) user reviews", (rev.get("data-tooltip-html") or "") if rev else "")
        out.append({
            "appid": a["data-ds-appid"].split(",")[0], "title": a.select_one(".title").get_text(strip=True),
            "discount": int(blk["data-discount"]), "final": int(blk.get("data-price-final") or 0) / 100,
            "orig": float(re.sub(r"\D", "", orig.get_text())) if orig and re.sub(r"\D", "", orig.get_text()) else None,
            "rating": int(m.group(1)) if m else None, "reviews": int(m.group(2).replace(",", "")) if m else 0})
    return out


def recent_promo_appids(db, days=3):
    """appid yang sudah tampil di postingan Promo Steam beberapa hari terakhir (untuk rotasi)."""
    since = utcnow() - timedelta(days=days)
    used = set()
    for (key,) in db.query(SocialPost.content_key).filter(
            SocialPost.content_type == "steam_deals", SocialPost.status.in_(("posted", "prepared")),
            SocialPost.created_at >= since):
        used.update((key or "").split(","))
    return used


def scrape_steam_promo(db, now=None, n=PROMO_COUNT):
    """Pilih n game populer dengan diskon besar (harga region Indonesia), simpan sebagai snapshot "promo_picks"."""
    now = now or utcnow()
    get_or_create_source(db, "Steam Store (ID)", "https://store.steampowered.com", "game", "api", "en")
    items = []
    for start in (0, 100, 200):
        try:
            items += _search_specials(start)
        except Exception as e:
            log.warning("Steam search start=%d gagal: %s", start, e)
            break
    good = [i for i in items if i["discount"] >= PROMO_MIN_DISCOUNT and (i["rating"] or 0) >= PROMO_MIN_RATING
            and i["reviews"] >= PROMO_MIN_REVIEWS and not NOT_A_GAME.search(i["title"])]
    good.sort(key=lambda i: i["reviews"] * i["discount"], reverse=True)

    def pick(pool):
        chosen, per_franchise = [], {}
        for i in pool:
            fk = _franchise(i["title"])
            if per_franchise.get(fk, 0) >= 1:  # satu game per waralaba agar daftar bervariasi
                continue
            per_franchise[fk] = per_franchise.get(fk, 0) + 1
            chosen.append(i)
            if len(chosen) == n:
                break
        return chosen

    used = recent_promo_appids(db)
    # game yang belum tampil beberapa hari terakhir didahulukan; sisanya hanya sebagai cadangan
    picks = pick([i for i in good if i["appid"] not in used] + [i for i in good if i["appid"] in used])
    picks = picks[:n]
    if not picks:
        log.warning("Promo Steam: tidak ada game yang memenuhi filter")
        return 0

    upsert(db, Game, [{
        "source": "steam", "external_id": i["appid"], "title": i["title"][:255], "platform": "PC (Steam)",
        "url": f"https://store.steampowered.com/app/{i['appid']}",
        "thumbnail_url": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{i['appid']}/header.jpg",
        "updated_at": now} for i in picks], keys=["source", "external_id"],
        update_cols=["title", "thumbnail_url", "updated_at"])
    ids = {gid: pk for pk, gid in db.query(Game.id, Game.external_id)
           .filter(Game.source == "steam", Game.external_id.in_([i["appid"] for i in picks]))}
    db.add_all(GameStoreSnapshot(
        game_id=ids[i["appid"]], list_type="promo_picks", position=pos, currency="IDR", original_price=i["orig"],
        final_price=i["final"], discount_pct=i["discount"], rating_pct=i["rating"], reviews=i["reviews"],
        captured_at=now) for pos, i in enumerate(picks, 1))
    db.commit()
    log.info("Promo Steam: %d pilihan dari %d kandidat (%d lolos filter)", len(picks), len(items), len(good))
    return len(picks)
