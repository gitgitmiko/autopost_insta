"""Audit postingan Instagram yang sudah tayang (adaptasi /ig-audit dari instagram-agent-skill, MIT).

Bukti "berhasil" bukan angka mentah, tapi kelipatan terhadap median akun sendiri (outlier multiple):
post 3x median = sesuatu yang perlu diulang; 0,3x = sesuatu yang perlu dihentikan. Hasilnya dikelompokkan
per jam slot, jenis konten/topik, format (Reel vs carousel), media sumber, hari, dan ajakan (CTA).

Metrik utama:
- views (Reel/carousel) bila token punya izin `instagram_manage_insights`; ditambah reach, saves, shares,
  dan sends per reach (shares/reach: sinyal terkuat yang bisa didapat);
- tanpa izin itu: interaksi = like + 3 x komentar (komentar lebih mahal dari like).

Token Page diambil dari credential n8n (sama dengan yang dipakai memposting); tidak pernah dicetak.
"""
import logging
import os
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

import requests

from ..db import Article, SocialPost, Source, utcnow
from . import n8n, settings
from .captions import CTA, RECAP_CTA, wib

log = logging.getLogger(__name__)
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
METRICS = ("reach,views,saved,shares,total_interactions", "reach,saved,shares,total_interactions")
REPORT_DIR = os.path.join(settings.ROOT, "data", "reports")


class NoPermission(Exception):
    pass


def page_token(acct):
    tok = n8n.credential_value(n8n.meta_cred(acct.key)["id"])
    if not tok or tok == n8n.TOKEN_PLACEHOLDER:
        raise SystemExit(f"Token Meta akun '{acct.key}' belum diisi (jalankan setup-token)")
    return tok


def _get(path, token, **params):
    r = requests.get(f"{settings.GRAPH_BASE}/{path}", params={"access_token": token, **params}, timeout=30).json()
    if "error" in r:
        err = r["error"]
        if err.get("code") == 10 or "permission" in err.get("message", "").lower():
            raise NoPermission(err.get("message"))
        raise RuntimeError(err.get("message"))
    return r


def fetch_media(acct, token, since_utc):
    """Media IG akun sejak since_utc (terbaru dulu)."""
    out, after = [], None
    fields = "id,timestamp,media_type,media_product_type,like_count,comments_count,permalink"
    while True:
        params = {"fields": fields, "limit": 50, **({"after": after} if after else {})}
        page = _get(f"{acct.ig_user_id}/media", token, **params)
        for m in page.get("data", []):
            if m["timestamp"][:19] < since_utc.strftime("%Y-%m-%dT%H:%M:%S"):
                return out
            out.append(m)
        after = page.get("paging", {}).get("cursors", {}).get("after")
        if not after or not page.get("paging", {}).get("next"):
            return out


def fetch_insights(media, token):
    """Isi m["insights"] untuk tiap media. Return False bila token tidak punya izin insights."""
    for m in media:
        for metrics in METRICS:
            try:
                data = _get(f"{m['id']}/insights", token, metric=metrics).get("data", [])
                m["insights"] = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {})
                                                                                .get("value")) for d in data}
                break
            except NoPermission:
                return False
            except RuntimeError as e:  # metrik tidak didukung untuk jenis media ini: coba set lebih kecil
                log.debug("insights %s (%s): %s", m["id"], metrics, e)
    return True


def _cta_kind(caption):
    """Jenis ajakan yang dipakai caption (hanya post sejak CTA otomatis diterapkan)."""
    caption = caption or ""
    line = next((x for opts in CTA.values() for x in opts if x in caption), None)
    if line is None:
        return "bagikan" if RECAP_CTA in caption else "tanpa CTA"
    low = line.lower()
    return ("tag teman" if "tag teman" in low else "komentar" if "komentar" in low else
            "bagikan" if "bagikan" in low else "simpan")


def collect(db, acct, days=30, with_insights=True):
    """Gabungkan media IG dengan baris social_posts (slot, jenis, artikel). Return (rows, insights_ok)."""
    token = page_token(acct)
    since = utcnow() - timedelta(days=days)
    media = fetch_media(acct, token, since)
    insights_ok = fetch_insights(media, token) if with_insights and media else False
    posts = {p.platform_post_id: p for p in db.query(SocialPost).filter(
        SocialPost.account == acct.key, SocialPost.platform == "instagram", SocialPost.status == "posted",
        SocialPost.platform_post_id.in_([m["id"] for m in media]))}
    rows = []
    for m in media:
        p = posts.get(m["id"])
        ins = m.get("insights") or {}
        likes, comments = m.get("like_count") or 0, m.get("comments_count") or 0
        row = {"id": m["id"], "permalink": m.get("permalink"), "likes": likes, "comments": comments,
               "format": "Reel" if m.get("media_product_type") == "REELS" else
               "Carousel" if m.get("media_type") == "CAROUSEL_ALBUM" else "Foto",
               "reach": ins.get("reach"), "views": ins.get("views"), "saved": ins.get("saved"),
               "shares": ins.get("shares"), "engagement": likes + 3 * comments}
        posted = wib(datetime.strptime(m["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        row["day"] = HARI[posted.weekday()]
        row["date"] = posted.strftime("%d/%m %H.%M")
        if p:
            parts = p.slot.split("-")
            row["slot"] = parts[0] if not p.slot.startswith("manual") else "manual"
            row["kind"] = p.content_type + (f" · {parts[2]}" if len(parts) > 2 and not p.slot.startswith("manual")
                                            else "")
            row["cta"] = _cta_kind(p.caption)
            if p.article_id:
                a, src = db.query(Article, Source).join(Source, Source.id == Article.source_id) \
                    .filter(Article.id == p.article_id).first() or (None, None)
                row["title"] = a.title if a else ""
                row["source"] = src.name if src else "?"
            else:
                row["title"], row["source"] = p.content_type, "(bukan artikel)"
        else:  # diposting di luar pipeline
            row.update(slot="di luar pipeline", kind="di luar pipeline", cta="?", title="", source="?")
        rows.append(row)
    metric = "views" if insights_ok and any(r["views"] for r in rows) else "engagement"
    values = [r[metric] or 0 for r in rows]
    med = statistics.median(values) if values else 0
    for r in rows:
        r["multiple"] = (r[metric] or 0) / med if med else 0
        r["sends_per_reach"] = (r["shares"] or 0) / r["reach"] if r.get("reach") else None
    return rows, insights_ok, metric, med


def _num(x, dec=0):
    return f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _group_table(rows, key, title, min_n=3):
    groups = defaultdict(list)
    for r in rows:
        groups[r.get(key) or "?"].append(r["multiple"])
    items = sorted(((statistics.median(v), len(v), k) for k, v in groups.items() if len(v) >= min_n), reverse=True)
    if not items:
        return [], None
    lines = [f"### {title}", "", "| | post | median kelipatan |", "|---|---:|---:|"]
    lines += [f"| {k} | {n} | {_num(m, 2)}x |" for m, n, k in items]
    return lines + [""], items


def report(acct, rows, insights_ok, metric, med, days):
    label = "views" if metric == "views" else "interaksi (like + 3 x komentar)"
    out = [f"# Audit Instagram {acct.brand_handle} · {days} hari terakhir", "",
           f"{len(rows)} post · metrik: **{label}** · median akun: **{_num(med, 1)}**", ""]
    if not insights_ok:
        out += ["> Token belum punya izin `instagram_manage_insights`, jadi reach/views/saves/shares tidak tersedia "
                "dan audit memakai like + komentar. Tambahkan izin itu saat membuat user token lalu jalankan "
                "`setup-token` lagi.", ""]
    if not rows:
        return "\n".join(out + ["Belum ada post pada periode ini."])
    ranked = sorted(rows, key=lambda r: r["multiple"], reverse=True)

    def post_line(r):
        extra = ""
        if r.get("reach"):
            extra = f" · reach {_num(r['reach'])} · simpan {r['saved'] or 0} · bagikan {r['shares'] or 0}"
        return (f"| {_num(r['multiple'], 1)}x | {r['date']} | {r['format']} | {r.get('kind', '')} | "
                f"[{(r.get('title') or '-')[:70]}]({r['permalink']}) | {r['likes']}♥ {r['comments']}💬{extra} |")

    head = ["| kelipatan | waktu | format | jenis | judul | angka |", "|---:|---|---|---|---|---|"]
    out += ["## Post terbaik (ulangi polanya)", ""] + head + [post_line(r) for r in ranked[:8]] + [""]
    out += ["## Post terlemah", ""] + head + [post_line(r) for r in ranked[-5:]] + [""]
    out += ["## Pola", ""]
    findings = []
    for key, title in (("slot", "Jam slot (WIB)"), ("kind", "Jenis konten / topik"), ("format", "Format"),
                       ("source", "Media sumber"), ("day", "Hari"), ("cta", "Ajakan (CTA)")):
        lines, items = _group_table(rows, key, title)
        out += lines
        if items and len(items) > 1:
            findings.append(f"- **{title}:** terbaik `{items[0][2]}` ({_num(items[0][0], 2)}x, {items[0][1]} post), "
                            f"terlemah `{items[-1][2]}` ({_num(items[-1][0], 2)}x, {items[-1][1]} post)")
    if insights_ok and any(r["sends_per_reach"] for r in rows):
        spr = sorted((r for r in rows if r["sends_per_reach"]), key=lambda r: r["sends_per_reach"], reverse=True)
        out += ["### Paling banyak dibagikan per reach", ""]
        out += [f"- {_num(r['sends_per_reach'] * 100, 2)}% · {(r.get('title') or '-')[:80]}" for r in spr[:5]] + [""]
    outliers = sum(r["multiple"] >= 3 for r in rows)
    flops = sum(r["multiple"] <= 0.3 for r in rows)
    out += ["## Ringkasan", "", *findings,
            f"- {outliers} post ≥ 3x median (outlier), {flops} post ≤ 0,3x median", "",
            "Kelompok dengan < 3 post tidak ditampilkan. Selisih kecil antar kelompok bisa kebetulan; "
            "ubah jadwal/format bila polanya bertahan di dua audit berturut-turut."]
    return "\n".join(out)


def run(db, acct, days=30, save=True):
    rows, insights_ok, metric, med = collect(db, acct, days)
    text = report(acct, rows, insights_ok, metric, med, days)
    if save:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, f"audit-{acct.key}-{wib(utcnow()):%Y%m%d}.md")
        with open(path, "w") as f:
            f.write(text + "\n")
        text += f"\n\n(disimpan: {path})"
    return text
