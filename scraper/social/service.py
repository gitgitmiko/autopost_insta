"""Layanan yang dipanggil workflow n8n.

prepare(): pilih konten untuk satu akun & slot, buat gambar di folder media publik, catat di social_posts.
report():  catat hasil posting dari n8n (posted/failed, id & permalink).
"""
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from ..config import GAME_TOPICS
from ..media import ensure_article_details
from ..db import SocialPost
from . import captions, cards, content, music, settings

log = logging.getLogger(__name__)
FINAL = ("posted", "skipped")


def _normalize_time(hour, minute):
    return f"{int(hour):02d}:{int(minute):02d}"


def _cleanup_media():
    """Hapus file publik lama: gambar setelah MEDIA_KEEP_DAYS, slide video (mp4) setelah VIDEO_KEEP_DAYS.
    Aman karena Instagram/Facebook menyalin media saat posting."""
    from ..media import VIDEO_KEEP_DAYS
    now = time.time()
    for root, _, files in os.walk(settings.MEDIA_DIR):
        for f in files:
            p = os.path.join(root, f)
            days = VIDEO_KEEP_DAYS if f.endswith(".mp4") else settings.MEDIA_KEEP_DAYS
            if os.path.getmtime(p) < now - days * 86400:
                os.remove(p)


def _soundtrack(acct, mood, segments, out_path, reel_cover=None):
    """Render Reel berlagu dari kartu-kartu. segments: [(path, detik)].
    Return (kredit lagu untuk caption, {"reel": path, ...}) — gagal/tanpa lagu: (None, {}) → posting gambar biasa."""
    track = music.pick(mood, out_path) if acct.music else None
    if not track:
        return None, {}
    try:
        path = music.reel_video(segments, _slide_path(out_path, "reel", ".mp4"), track)
    except Exception as e:
        log.warning("Reel berlagu (%s) gagal dibuat, posting tanpa lagu: %s", mood, getattr(e, "stderr", None) or e)
        return None, {}
    log.info("[%s] lagu %s: %s", acct.key, mood, track.title)
    return music.credit(track), {"reel": path, "mood": mood, **({"reel_cover": reel_cover} if reel_cover else {})}


def _feed_music(acct, mood, slides, out_path):
    """Carousel feed berlagu (bukan Reel): tiap slide jadi video diam + potongan lagu bersambung.
    Return (kredit lagu, {"ig_slides": [path mp4]}) — butuh ≥2 slide; gagal/tanpa lagu: (None, {}) → gambar biasa."""
    track = music.pick(mood, out_path) if acct.music and len(slides) > 1 else None
    if not track:
        return None, {}
    try:
        paths = music.carousel_videos(slides, track, out_path)
    except Exception as e:
        log.warning("carousel berlagu (%s) gagal dibuat, posting tanpa lagu: %s", mood,
                    getattr(e, "stderr", None) or e)
        return None, {}
    log.info("[%s] lagu %s (carousel): %s", acct.key, mood, track.title)
    return music.credit(track), {"ig_slides": paths, "mood": mood}


def _words(paras):
    return sum(len(p.split()) for p in paras)


def build(db, acct, kind, out_path, article_id=None, exclude_ids=(), refresh=True, topic=None, max_age_hours=None):
    """Buat gambar + caption. Return (dict konten, None) atau (None, alasan dilewati).

    topic (mis. "valorant"/"dota2") membatasi berita ke topik game khusus."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plats = ("instagram", "facebook")
    if kind == "news":
        max_age = max_age_hours or settings.NEWS_MAX_AGE_HOURS
        item = (content.load_news_item(db, article_id, topic) if article_id else
                content.pick_news(db, acct.category, acct.key, acct.languages, exclude_ids=exclude_ids,
                                  topic=topic, max_age_hours=max_age))
        if not item:
            what = GAME_TOPICS[topic]["label"] if topic else acct.category
            return None, f"tidak ada berita {what} baru yang layak dalam {max_age} jam"
        # isi lengkap + gambar/video di dalam artikel → caption lebih lengkap & slide carousel tambahan
        media, youtube = ensure_article_details(db, item.article, max_media=acct.max_extra_slides) \
            if acct.use_article_photo and acct.max_extra_slides else ([], [])
        if not acct.use_article_photo:
            media, youtube = [], ensure_article_details(db, item.article, max_media=0)[1]
        item.extra_slides = len(media)
        item.extra_media = {"image": sum(m["type"] == "image" for m in media),
                            "video": sum(m["type"] == "video" for m in media)}
        item.youtube = youtube[:2]
        feed = kind in acct.feed_kinds  # IG: carousel feed berlagu, bukan Reel
        # carousel butuh ≥2 slide: tanpa media artikel, foto utama + lanjutan isi jadi slide kedua
        photo_slide = (feed and acct.music and not media and acct.use_article_photo and item.image_path
                       and os.path.exists(cards.image_abspath(item.image_path)))
        if photo_slide:
            item.extra_slides = 1  # kartu pertama cukup judul + "Geser"
        cards.news_card(item, out_path, acct)
        slides = [{"path": out_path, "type": "image"}]
        seconds = []  # lama tampil tiap slide 2+ di Reel, sesuai banyaknya teks
        theme = cards.TOPIC_THEME.get(topic) or cards.THEME[item.article.category]
        pub = content.publisher_name(item.source.name)
        narration = captions.slide_narration(item)  # lanjutan isi artikel, diteruskan dari slide ke slide
        # panel teks bergantian bawah/atas/mengambang supaya carousel tidak monoton
        layouts = cards.slide_layouts([m["type"] for m in media], out_path)
        for i, (m, layout) in enumerate(zip(media, layouts), start=2):
            try:
                if m["type"] == "video":
                    path = _slide_path(out_path, i, ".mp4")
                    rest = cards.video_slide(m["path"], path, acct, theme, layout, f"Video: {pub}",
                                             f"Sumber: {pub}", heading=item.article.title, narration=narration)
                else:
                    path = _slide_path(out_path, i)
                    rest = cards.image_slide(m["path"], path, acct, theme, layout, f"Foto: {pub}",
                                             f"Sumber: {pub}", heading=item.article.title, narration=narration)
                shown = _words(narration) - _words(rest) if narration else len(item.article.title.split())
                sec = music.read_seconds(shown)
                if m["type"] == "video":  # potongan video artikel (tanpa suara aslinya), cukup untuk dibaca
                    sec = max(sec, min(music.VIDEO_MAX_SECONDS, sec + 4))
                narration = rest
                slides.append({"path": path, "type": m["type"]})
                seconds.append(sec)
            except Exception as e:
                log.warning("slide %d (%s) gagal dibuat: %s", i, m["type"], e)
        if photo_slide:
            try:
                path = _slide_path(out_path, 2)
                cards.image_slide(item.image_path, path, acct, theme, "bottom", f"Foto: {pub}", f"Sumber: {pub}",
                                  heading=item.article.title, narration=narration)
                slides.append({"path": path, "type": "image"})
            except Exception as e:
                log.warning("slide foto utama gagal dibuat: %s", e)
            item.extra_slides = 0  # bukan media tambahan dari artikel (caption tidak menyebutnya)
        if feed:
            credit, video = _feed_music(acct, music.news_mood(item), slides, out_path)
            texts = {p: captions.news_texts(item, p, acct, credit, reel=False) for p in plats}
            return {"article_id": item.article.id, "content_key": None, "title": item.article.title,
                    "captions": {p: t[0] for p, t in texts.items()},
                    "comments": {p: t[1] for p, t in texts.items()}, "slides": slides, **video}, None
        # Instagram: semua kartu jadi satu Reel berlagu (cover tanpa "Geser"); Facebook tetap album foto
        if len(slides) == 1:
            segments, reel_cover = [(out_path, music.SINGLE_SECONDS)], None
        else:
            reel_cover = cards.news_card(item, _slide_path(out_path, "reel-cover"), acct, swipe_hint=False) \
                if acct.music else None
            segments = [(reel_cover, music.COVER_SECONDS)] + [(sl["path"], sec) for sl, sec in zip(slides[1:], seconds)]
        credit, video = _soundtrack(acct, music.news_mood(item), segments, out_path, reel_cover)
        texts = {p: captions.news_texts(item, p, acct, credit) for p in plats}
        return {"article_id": item.article.id, "content_key": None, "title": item.article.title,
                "captions": {p: t[0] for p, t in texts.items()},
                "comments": {p: t[1] for p, t in texts.items()}, "slides": slides, **video}, None

    if kind == "steam_deals":
        if refresh:  # harga & pilihan terbaru sesaat sebelum posting
            from ..scrapers.games import scrape_steam_promo
            try:
                scrape_steam_promo(db)
            except Exception as e:
                db.rollback()
                log.warning("refresh promo Steam gagal, memakai data terakhir: %s", e)
        deals = content.steam_deals(db)
        if not deals:
            return None, "data promo Steam belum ada"
        last = (db.query(SocialPost.content_key)
                .filter(SocialPost.account == acct.key, SocialPost.content_type == "steam_deals",
                        SocialPost.status == "posted").order_by(SocialPost.id.desc()).first())
        if last and set((last[0] or "").split(",")) == set(deals.key.split(",")):
            return None, "daftar promo Steam sama dengan postingan sebelumnya"
        n_slides = 1 + -(-len(deals.items) // cards.PER_SLIDE)
        paths = [out_path] + [_slide_path(out_path, i) for i in range(2, n_slides + 1)]
        cards.steam_promo_slides(deals, paths, acct)
        credit, video = None, {}
        if kind in acct.feed_kinds:  # carousel feed berlagu (cover tetap dengan "Geser »")
            credit, video = _feed_music(acct, "seru", [{"path": p, "type": "image"} for p in paths], out_path)
        elif acct.music:  # Reel tidak bisa digeser: cover tanpa "Geser »" (album Facebook tetap memakai paths[0])
            reel_cover = cards.steam_cover(deals, _slide_path(out_path, "reel-cover"), acct, swipe_hint=False)
            credit, video = _soundtrack(acct, "seru", [(p, music.STEAM_SLIDE_SECONDS) for p in [reel_cover] + paths[1:]],
                                        out_path, reel_cover)
        caps = {p: captions.steam_deals_caption(deals, p, acct, credit, reel="reel" in video) for p in plats}
        return {"article_id": None, "content_key": deals.key, "captions": caps, "title": "Promo Steam",
                "slides": [{"path": p, "type": "image"} for p in paths], **video}, None

    if kind == "recap_saham":
        if refresh:  # harga penutupan terbaru sesaat sebelum posting
            from ..scrapers.stocks import scrape_stocks
            from ..sentiment import process_pending
            scrape_stocks(db, rng="5d", delay=0.2)
            process_pending(db)
        r = content.stock_recap(db)
        if not r:
            return None, "belum ada data penutupan bursa hari ini (libur/akhir pekan?)"
        cards.stock_recap_card(r, out_path, acct)
        credit, video = _soundtrack(acct, music.market_mood(r.ihsg_change), [(out_path, music.SINGLE_SECONDS)],
                                    out_path)
        caps = {p: captions.stock_recap_caption(r, p, acct, credit) for p in plats}
        return {"article_id": None, "content_key": str(r.day), "captions": caps, "title": "Rekap saham",
                **video}, None

    if kind == "recap_crypto":
        if refresh:
            from ..scrapers.crypto import scrape_crypto
            from ..scrapers.market_sentiment import scrape_fear_greed
            from ..sentiment import process_pending
            scrape_crypto(db)
            scrape_fear_greed(db)
            process_pending(db)
        r = content.crypto_recap(db)
        if not r or not r.coins:
            return None, "data harga crypto belum tersedia"
        cards.crypto_recap_card(r, out_path, acct)
        avg = sum(c[3] or 0 for c in r.coins) / len(r.coins)  # rata-rata perubahan 24 jam
        credit, video = _soundtrack(acct, music.market_mood(avg), [(out_path, music.SINGLE_SECONDS)], out_path)
        caps = {p: captions.crypto_recap_caption(r, p, acct, credit) for p in plats}
        return {"article_id": None, "content_key": None, "captions": caps, "title": "Rekap crypto", **video}, None
    raise ValueError(f"jenis konten tidak dikenal: {kind}")


def _slide_path(first_path, index, ext=None):
    base, first_ext = os.path.splitext(first_path)
    return f"{base[:-2] if base.endswith('-1') else base}-{index}{ext or first_ext}"


def _row(db, acct_key, slot, day, platform):
    row = db.query(SocialPost).filter_by(account=acct_key, slot=slot, slot_date=day, platform=platform).one_or_none()
    if row is None:
        row = SocialPost(account=acct_key, slot=slot, slot_date=day, platform=platform, attempts=0)
        db.add(row)
    return row


def prepare(db, account, hour=None, minute=None, kind=None, now=None, topic=None, article_id=None):
    """Dipanggil n8n saat jadwal tiba. Tanpa hour/minute (pemicu manual) dibuat slot 'manual-…'."""
    acct = settings.get_account(account)
    if not acct.enabled:
        return {"status": "skip", "reason": f"akun {account} dinonaktifkan"}
    now = now or datetime.now(settings.TZ)
    day = now.date()
    entry = None
    if hour is not None and minute is not None:
        hhmm = _normalize_time(hour, minute)
        entry = acct.slot_at(hhmm) or {"time": hhmm, "kind": kind or "news"}
        if kind or topic:  # permintaan eksplisit mengalahkan jadwal
            entry = {**entry, "kind": kind or entry["kind"], "topic": topic or entry.get("topic")}
        slot = settings.slot_name(entry)
    else:
        entry = {"time": f"manual-{now:%H%M%S}", "kind": kind or "news", "topic": topic}
        slot = settings.slot_name(entry)
    kind, topic = entry["kind"], entry.get("topic")

    rows = {r.platform: r for r in db.query(SocialPost).filter_by(account=account, slot=slot, slot_date=day)}
    pending = [p for p in acct.platforms if p not in rows or
               (rows[p].status not in FINAL and (rows[p].attempts or 0) < settings.MAX_ATTEMPTS)]
    if not pending:
        return {"status": "duplicate", "reason": f"slot {slot} sudah diproses"}
    reuse_article = next((r.article_id for r in rows.values() if r.article_id), None) or article_id

    _cleanup_media()
    name = f"{slot.replace(':', '')}-{secrets.token_hex(4)}-1.jpg"
    rel = f"{account}/{day.isoformat()}/{name}"
    out_path = os.path.join(settings.MEDIA_DIR, rel)
    built, reason = build(db, acct, kind, out_path, article_id=reuse_article, topic=topic,
                          max_age_hours=entry.get("max_age_hours"))
    if not built:
        for p in pending:
            r = _row(db, account, slot, day, p)
            r.status, r.content_type, r.error = "skipped", kind, reason
            r.attempts = (r.attempts or 0) + 1
        db.commit()
        log.info("[%s] %s dilewati: %s", account, slot, reason)
        return {"status": "skip", "reason": reason, "slot": slot}

    def url(path):
        return f"{settings.MEDIA_BASE_URL}/{os.path.relpath(path, settings.MEDIA_DIR)}"

    slides = built.get("slides") or [{"path": out_path, "type": "image"}]
    slide_items = [{"url": url(sl["path"]), "type": sl["type"]} for sl in slides]
    image_url = slide_items[0]["url"]
    fb_slides = [sl["url"] for sl in slide_items if sl["type"] == "image"]  # album Facebook hanya foto (tanpa lagu)
    # Instagram: seluruh postingan jadi satu Reel berlagu (tanpa lagu/gagal render: gambar/carousel biasa)
    ig_items = list(slide_items)
    reel_url = url(built["reel"]) if built.get("reel") else None
    reel_cover_url = url(built["reel_cover"]) if built.get("reel_cover") else image_url
    if reel_url:
        ig_items = [{"url": reel_url, "type": "reel"}]
    elif built.get("ig_slides"):  # carousel feed berlagu: semua slide berupa video
        ig_items = [{"url": url(p), "type": "video"} for p in built["ig_slides"]]
    comments = built.get("comments") or {}
    post_ids = {}
    for p in pending:
        r = _row(db, account, slot, day, p)
        r.status, r.content_type, r.error = "prepared", kind, None
        r.article_id, r.content_key = built["article_id"], built["content_key"]
        r.caption, r.image_url = built["captions"][p], image_url
        r.slides = json.dumps(ig_items if p == "instagram" else slide_items)
        r.comments = json.dumps(comments.get(p) or [], ensure_ascii=False)
        r.attempts = (r.attempts or 0) + 1
        db.flush()
        post_ids[p] = r.id
    db.commit()
    log.info("[%s] %s siap: %s → %s%s", account, slot, built["title"][:80], reel_url or image_url,
             f" (lagu {built['mood']})" if built.get("mood") else "")
    return {
        "status": "ready", "account": account, "slot": slot, "kind": kind, "topic": topic, "title": built["title"],
        "image_url": image_url, "slides": ig_items, "carousel": len(ig_items) > 1,
        "has_video": any(sl["type"] == "video" for sl in ig_items),
        "reel": bool(reel_url), "reel_url": reel_url, "reel_cover_url": reel_cover_url, "mood": built.get("mood"),
        "fb_slides": fb_slides, "fb_carousel": len(fb_slides) > 1,
        "comments_instagram": comments.get("instagram") or [],
        "graph_base": settings.GRAPH_BASE,
        "ig_user_id": acct.ig_user_id, "page_id": acct.page_id,
        "instagram": "instagram" in post_ids, "facebook": "facebook" in post_ids,
        "post_id_instagram": post_ids.get("instagram"), "post_id_facebook": post_ids.get("facebook"),
        "caption_instagram": built["captions"]["instagram"], "caption_facebook": built["captions"]["facebook"],
    }


def _clean_error(error):
    """Ringkas pesan error n8n & sembunyikan token yang mungkin ikut tercatat."""
    if not error:
        return None
    text = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
    try:
        data = json.loads(text)
        msg = data.get("message") or ""
        inner = data.get("description") or (data.get("error") or {}).get("message") if isinstance(data, dict) else None
        text = " | ".join(x for x in (msg, inner if isinstance(inner, str) else None, text[:1500]) if x)
    except (ValueError, AttributeError):
        pass
    # pesan paling dalam (biasanya pesan asli dari Graph API) ditaruh di depan
    inner_msgs = re.findall(r'message\W{1,12}([^"\\]{3,200})', text)
    if inner_msgs and inner_msgs[-1] not in text[:200]:
        text = f"{inner_msgs[-1]} | {text}"
    return re.sub(r"(access_token[\"'=:\s]+)[A-Za-z0-9_\-.|%]+", r"\1***", text)[:5000]


def report(db, post_id, status, platform_post_id=None, permalink=None, error=None, note=None):
    row = db.get(SocialPost, int(post_id))
    if row is None:
        return {"ok": False, "reason": f"post_id {post_id} tidak ditemukan"}
    if note and not status:  # catatan tambahan (mis. komentar lanjutan gagal) tanpa mengubah status
        row.error = ((row.error + "\n") if row.error else "") + _clean_error(note)[:2000]
        db.commit()
        log.info("[%s] %s %s catatan: %s", row.account, row.slot, row.platform, note[:200])
        return {"ok": True}
    if status not in ("posted", "failed"):
        return {"ok": False, "reason": "status harus posted/failed"}
    row.status = status
    row.platform_post_id = platform_post_id or row.platform_post_id
    row.permalink = permalink or row.permalink
    row.error = _clean_error(error) if status == "failed" else None
    db.commit()
    log.info("[%s] %s %s → %s %s", row.account, row.slot, row.platform, status, permalink or error or "")
    if status == "posted" and row.platform == "instagram":
        try:  # perbarui halaman "link di bio"
            from . import bio
            bio.render(db, settings.get_account(row.account))
        except Exception:
            log.exception("halaman bio gagal diperbarui")
    return {"ok": True}


def status(db, account, day=None):
    day = day or datetime.now(settings.TZ).date()
    acct = settings.get_account(account)
    rows = {(r.slot, r.platform): r for r in db.query(SocialPost).filter_by(account=account, slot_date=day)}
    out = []
    for s in acct.schedule:
        slot = settings.slot_name(s)
        for p in acct.platforms:
            r = rows.pop((slot, p), None)
            out.append((slot, p, r.status if r else "menunggu", (r.permalink or r.error or "") if r else ""))
    for (slot, p), r in sorted(rows.items()):  # slot manual / di luar jadwal
        out.append((slot, p, r.status, r.permalink or r.error or ""))
    return out


# ---------------------------------------------------------------- baca (dashboard)
def _wib_iso(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(settings.TZ).isoformat(timespec="seconds") if dt else None


KIND_LABEL = {"news": "Berita", "steam_deals": "Promo Steam", "recap_saham": "Rekap saham",
              "recap_crypto": "Rekap crypto"}


def _label(kind, topic=None):
    base = KIND_LABEL.get(kind, kind)
    return f"{base} {GAME_TOPICS[topic]['label']}" if topic in GAME_TOPICS else base


def _slot_topic(slot):
    last = (slot or "").rsplit("-", 1)[-1]
    return last if last in GAME_TOPICS else None


def _post_dict(r, title):
    return {
        "id": r.id, "account": r.account, "slot": r.slot, "date": r.slot_date.isoformat(),
        "platform": r.platform, "kind": r.content_type, "label": _label(r.content_type, _slot_topic(r.slot)),
        "status": r.status, "attempts": r.attempts,
        "title": title or ((r.caption or "").split("\n", 1)[0].lstrip("🎮📊🪙🔥🏛️📈 ") or None),
        "image_url": r.image_url, "permalink": r.permalink,
        "error": (r.error or "")[:400] or None,
        "created_at": _wib_iso(r.created_at), "updated_at": _wib_iso(r.updated_at),
    }


def list_posts(db, account=None, status=None, day=None, page=1, page_size=10):
    from ..db import Article
    page_size = page_size if page_size in (10, 25, 50, 100) else 10
    q = db.query(SocialPost, Article.title).outerjoin(Article, Article.id == SocialPost.article_id)
    if account:
        q = q.filter(SocialPost.account == account)
    if status:
        q = q.filter(SocialPost.status == status)
    if day:
        q = q.filter(SocialPost.slot_date == day)
    total = q.count()
    pages = max(1, -(-total // page_size))
    page = min(max(1, page), pages)
    rows = q.order_by(SocialPost.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"posts": [_post_dict(r, t) for r, t in rows], "total": total, "page": page,
            "pageSize": page_size, "totalPages": pages}


def overview(db, now=None):
    from sqlalchemy import func
    now = now or datetime.now(settings.TZ)
    today = now.date()
    week_ago = today - timedelta(days=6)

    def count(status, since):
        return db.query(func.count(SocialPost.id)).filter(SocialPost.status == status,
                                                         SocialPost.slot_date >= since).scalar()

    accounts, upcoming = [], []
    for acct in settings.load_accounts().values():
        rows = {(r.slot, r.platform): r for r in db.query(SocialPost).filter_by(account=acct.key, slot_date=today)}
        schedule = []
        for s in sorted(acct.schedule, key=lambda x: x["time"]):
            slot = settings.slot_name(s)
            plats = []
            for p in acct.platforms:
                r = rows.get((slot, p))
                plats.append({"platform": p, "status": r.status if r else None,
                              "permalink": r.permalink if r else None,
                              "error": (r.error or "")[:200] if r else None})
            hh, mm = map(int, s["time"].split(":"))
            due = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            schedule.append({"time": s["time"], "kind": s["kind"], "topic": s.get("topic"),
                             "label": _label(s["kind"], s.get("topic")), "past": due <= now, "platforms": plats})
            if due > now and acct.enabled and acct.ig_user_id:
                upcoming.append({"at": due.isoformat(timespec="minutes"), "account": acct.key, "kind": s["kind"],
                                 "label": _label(s["kind"], s.get("topic"))})
        accounts.append({"key": acct.key, "category": acct.category, "brand_name": acct.brand_name,
                         "handle": acct.brand_handle, "enabled": acct.enabled,
                         "connected": bool(acct.ig_user_id), "platforms": acct.platforms, "schedule": schedule})

    last = (db.query(SocialPost).filter(SocialPost.status == "posted")
            .order_by(SocialPost.updated_at.desc()).first())
    return {
        "now": now.isoformat(timespec="seconds"),
        "today": {"posted": count("posted", today), "failed": count("failed", today),
                  "skipped": count("skipped", today)},
        "week": {"posted": count("posted", week_ago), "failed": count("failed", week_ago),
                 "skipped": count("skipped", week_ago)},
        "next": min(upcoming, key=lambda x: x["at"]) if upcoming else None,
        "last": _post_dict(last, None) if last else None,
        "accounts": accounts,
    }
