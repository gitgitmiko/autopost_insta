"""Halaman "link di bio" Instagram per akun: daftar postingan terbaru + link artikel, video YouTube, dan Instagram.

Ditulis sebagai HTML statis ke <n8n>/media/public/links/<bio_slug>/ dan disajikan nginx media di
https://media.gitgitmiko.my.id/l/<bio_slug>/ — dibuat ulang setiap ada postingan Instagram yang terbit.
"""
import html
import logging
import os

from PIL import Image

from ..db import Article, ArticleYoutube, Game, GameStoreSnapshot, SocialPost
from . import settings
from .captions import num, tanggal, wib
from .cards import THEME, TOPIC_THEME

log = logging.getLogger(__name__)
LINKS_DIR = os.path.join(os.path.dirname(settings.MEDIA_DIR), "links")
MAX_ITEMS = 40
KIND_LABEL = {"news": "Berita", "steam_deals": "Promo Steam", "recap_saham": "Rekap saham",
              "recap_crypto": "Rekap crypto"}


def page_url(acct):
    return f"{settings.MEDIA_BASE_URL.rsplit('/media/', 1)[0]}/l/{acct.bio_slug}/"


def _local_path(public_url):
    prefix = settings.MEDIA_BASE_URL + "/"
    return os.path.join(settings.MEDIA_DIR, public_url[len(prefix):]) if public_url.startswith(prefix) else None


def _thumb(post, out_dir):
    """Thumbnail kecil disimpan bersama halaman (file media publik dihapus setelah 14 hari)."""
    name = f"{post.id}.jpg"
    dst = os.path.join(out_dir, "thumbs", name)
    if os.path.exists(dst):
        return f"thumbs/{name}"
    src = _local_path(post.image_url or "")
    if not src or not os.path.exists(src):
        return None
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im = Image.open(src).convert("RGB")
    im.thumbnail((300, 375))
    im.save(dst, "JPEG", quality=80, optimize=True)
    return f"thumbs/{name}"


def _topic(slot):
    last = (slot or "").rsplit("-", 1)[-1]
    return last if last in TOPIC_THEME else None


def _promo_games(db, post):
    """Daftar game pada postingan Promo Steam: snapshot "promo_picks" terakhir sebelum postingan dibuat."""
    from datetime import timedelta
    from sqlalchemy import func
    ts = (db.query(func.max(GameStoreSnapshot.captured_at))
          .filter(GameStoreSnapshot.list_type == "promo_picks",
                  GameStoreSnapshot.captured_at <= post.created_at + timedelta(minutes=5)).scalar())
    if ts is None or post.created_at - ts > timedelta(days=1):
        return []
    rows = (db.query(Game.external_id, Game.title, GameStoreSnapshot.discount_pct, GameStoreSnapshot.final_price)
            .join(Game, Game.id == GameStoreSnapshot.game_id)
            .filter(GameStoreSnapshot.list_type == "promo_picks", GameStoreSnapshot.captured_at == ts)
            .order_by(GameStoreSnapshot.position).all())
    return [(a, t, int(d or 0), float(f or 0)) for a, t, d, f in rows]


def render(db, acct):
    if not acct.bio_slug:
        return None
    out_dir = os.path.join(LINKS_DIR, acct.bio_slug)
    os.makedirs(out_dir, exist_ok=True)
    posts = (db.query(SocialPost).filter(SocialPost.account == acct.key, SocialPost.platform == "instagram",
                                         SocialPost.status == "posted")
             .order_by(SocialPost.updated_at.desc()).limit(MAX_ITEMS).all())
    accent = "#%02x%02x%02x" % THEME.get(acct.category, THEME["game"])["accent"]
    cards, keep, seen_articles = [], set(), set()
    for p in posts:
        if p.article_id:  # artikel yang diposting ulang (repost) cukup tampil sekali, versi terbaru
            if p.article_id in seen_articles:
                continue
            seen_articles.add(p.article_id)
        a = db.get(Article, p.article_id) if p.article_id else None
        topic = _topic(p.slot)
        label = KIND_LABEL.get(p.content_type, p.content_type)
        if topic:
            label += " " + {"valorant": "VALORANT", "dota2": "DOTA 2"}.get(topic, topic)
        title = a.title if a else (p.caption or "").split("\n", 1)[0].lstrip("🔥📊🪙 ")
        links = []
        if a:
            links.append(("📰 Baca artikel", a.url))
            for y in (db.query(ArticleYoutube).filter_by(article_id=a.id).order_by(ArticleYoutube.position).limit(2)):
                links.append((f"🎬 Tonton video{': ' + y.title[:40] if y.title else ''}", y.url))
        games_html = ""
        if p.content_type == "steam_deals":
            links.append(("🎮 Lihat semua promo di Steam", "https://store.steampowered.com/specials"))
            games = _promo_games(db, p)
            if games:
                games_html = (f'<details class="games" open><summary>{len(games)} game di promo ini</summary><ul>'
                              + "".join(f'<li><a href="https://store.steampowered.com/app/{html.escape(g[0])}/" '
                                        f'target="_blank" rel="noopener">{html.escape(g[1])}</a>'
                                        f'<span>-{g[2]}% · Rp{num(g[3])}</span></li>' for g in games)
                              + "</ul></details>")
        if p.permalink:
            links.append(("📷 Lihat di Instagram", p.permalink))
        thumb = _thumb(p, out_dir)
        if thumb:
            keep.add(os.path.basename(thumb))
        tag_color = "#%02x%02x%02x" % TOPIC_THEME[topic]["accent"] if topic else accent
        when = wib(p.updated_at)
        cards.append(f"""
      <article class="card">
        {f'<img class="thumb" src="{thumb}" alt="" loading="lazy">' if thumb else '<div class="thumb"></div>'}
        <div class="body">
          <div class="meta"><span class="tag" style="background:{tag_color}">{html.escape(label)}</span>
            {html.escape(tanggal(when.date(), False))}, {when:%H.%M} WIB</div>
          <h2>{html.escape(title)}</h2>
          {games_html}
          <div class="links">{''.join(f'<a href="{html.escape(u, quote=True)}" target="_blank" rel="noopener">{html.escape(t)}</a>' for t, u in links)}</div>
        </div>
      </article>""")

    # hapus thumbnail postingan yang sudah tidak tampil
    thumbs_dir = os.path.join(out_dir, "thumbs")
    if os.path.isdir(thumbs_dir):
        for f in os.listdir(thumbs_dir):
            if f not in keep:
                os.remove(os.path.join(thumbs_dir, f))

    handle = acct.brand_handle.lstrip("@")
    page = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(acct.brand_name)} — link berita & video</title>
  <meta name="description" content="Link artikel dan video dari postingan terbaru {html.escape(acct.brand_handle)}">
  <meta property="og:title" content="{html.escape(acct.brand_name)} — link berita & video">
  <style>
    :root {{ --accent: {accent}; --bg: #0f0b24; --card: #1a1438; --line: #2c2456; --text: #f1eefc; --muted: #a9a2c8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--text);
           background: radial-gradient(900px 400px at 50% -10%, #2c1c66, var(--bg)); min-height: 100vh; }}
    main {{ max-width: 640px; margin: 0 auto; padding: 28px 16px 48px; }}
    header {{ text-align: center; margin-bottom: 22px; }}
    header h1 {{ margin: 0; font-size: 1.6rem; letter-spacing: -0.02em; }}
    header a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
    header p {{ color: var(--muted); margin: 6px 0 0; font-size: 0.95rem; }}
    .card {{ display: flex; gap: 12px; background: var(--card); border: 1px solid var(--line); border-radius: 16px;
            padding: 12px; margin-bottom: 12px; }}
    .thumb {{ width: 92px; height: 115px; flex: 0 0 92px; border-radius: 10px; object-fit: cover; background: #241c4a; }}
    .body {{ min-width: 0; flex: 1; }}
    .meta {{ color: var(--muted); font-size: 0.78rem; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .tag {{ color: #0d0a1c; font-weight: 700; border-radius: 99px; padding: 2px 8px; font-size: 0.72rem; }}
    h2 {{ font-size: 0.98rem; line-height: 1.3; margin: 6px 0 8px; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .links a {{ display: inline-block; padding: 7px 11px; border-radius: 10px; background: #2a2156; color: var(--text);
               text-decoration: none; font-size: 0.82rem; border: 1px solid var(--line); }}
    .games {{ margin: 0 0 10px; font-size: 0.85rem; }}
    .games summary {{ cursor: pointer; color: var(--muted); margin-bottom: 6px; }}
    .games ul {{ list-style: none; margin: 0; padding: 0; }}
    .games li {{ display: flex; justify-content: space-between; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--line); }}
    .games li a {{ color: var(--text); text-decoration: none; }}
    .games li span {{ color: #a4d007; white-space: nowrap; font-weight: 600; }}
    .links a:first-child {{ background: var(--accent); color: #0d0a1c; font-weight: 700; border-color: var(--accent); }}
    footer {{ text-align: center; color: var(--muted); font-size: 0.78rem; margin-top: 24px; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(acct.brand_name)}</h1>
      <p><a href="https://www.instagram.com/{html.escape(handle)}/" target="_blank" rel="noopener">{html.escape(acct.brand_handle)}</a></p>
      <p>Link artikel & video dari postingan terbaru</p>
    </header>
    {''.join(cards) or '<p style="text-align:center;color:var(--muted)">Belum ada postingan.</p>'}
    <footer>Diperbarui otomatis · sumber berita milik masing-masing penerbit</footer>
  </main>
</body>
</html>
"""
    tmp = os.path.join(out_dir, "index.html.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, os.path.join(out_dir, "index.html"))
    log.info("Halaman bio %s diperbarui (%d postingan)", acct.bio_slug, len(posts))
    return page_url(acct)
