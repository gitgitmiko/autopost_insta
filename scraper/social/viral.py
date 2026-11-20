"""Riset post yang sedang berhasil di niche (adaptasi /ig-viral + swipe.py dari instagram-agent-skill, MIT).

Views/like mentah bukan bukti: akun 2 juta follower dengan 40 ribu like sedang sepi, akun 4 ribu follower
dengan 4 ribu like menemukan sesuatu. Jadi tiap post dirangking dengan kelipatan interaksinya terhadap median
akun itu sendiri, lalu baris pertama caption-nya (hook) dicatat ke swipe file.

Sumber data: Instagram Graph API `business_discovery` (akun Bisnis/Kreator publik saja), memakai token Page
akun kita. Butuh izin `instagram_basic` + `instagram_manage_insights` pada token. Daftar akun pesaing per akun:
`"competitors": ["username1", "username2"]` di social_accounts.json.
"""
import os
import statistics

from . import settings
from .captions import wib
from .insights import REPORT_DIR, NoPermission, _get, _num, page_token
from ..db import utcnow

FIELDS = ("business_discovery.username({u}){{username,followers_count,media_count,"
          "media.limit({n}){{caption,like_count,comments_count,timestamp,media_type,media_product_type,permalink}}}}")


def fetch_account(acct, token, username, n=30):
    r = _get(acct.ig_user_id, token, fields=FIELDS.format(u=username.lstrip("@"), n=n))["business_discovery"]
    media = r.get("media", {}).get("data", [])
    for m in media:
        m["engagement"] = (m.get("like_count") or 0) + 3 * (m.get("comments_count") or 0)
    med = statistics.median([m["engagement"] for m in media]) if media else 0
    for m in media:
        m["multiple"] = m["engagement"] / med if med else 0
        m["hook"] = ((m.get("caption") or "").strip().split("\n", 1)[0])[:160]
        m["account"] = r["username"]
        m["followers"] = r.get("followers_count") or 0
    return r, med, media


def run(acct, top=20, per_account=30, save=True):
    if not acct.competitors:
        return (f"Akun '{acct.key}' belum punya daftar pesaing. Tambahkan di social_accounts.json, mis.\n"
                f'  "competitors": ["akun_pesaing_1", "akun_pesaing_2"]\n'
                "(akun Bisnis/Kreator publik di niche yang sama, ukuran mirip atau sedikit lebih besar)")
    token = page_token(acct)
    accounts, posts, errors = [], [], []
    for username in acct.competitors:
        try:
            info, med, media = fetch_account(acct, token, username, per_account)
            accounts.append((info["username"], info.get("followers_count") or 0, med, len(media)))
            posts += media
        except NoPermission as e:
            return ("Token belum punya izin untuk business_discovery "
                    f"({e}). Tambahkan izin `instagram_manage_insights` saat membuat user token, "
                    "lalu jalankan setup-token lagi.")
        except (RuntimeError, KeyError) as e:
            errors.append(f"- @{username}: {e} (bukan akun Bisnis/Kreator, privat, atau username salah)")
    posts.sort(key=lambda m: m["multiple"], reverse=True)
    out = [f"# Swipe file {acct.brand_handle} · {wib(utcnow()):%d/%m/%Y}", "",
           "Dirangking dengan kelipatan interaksi (like + 3 x komentar) terhadap median akun itu sendiri.", "",
           "## Akun yang dipantau", "", "| akun | follower | median interaksi | post dibaca |", "|---|---:|---:|---:|"]
    out += [f"| @{u} | {_num(f)} | {_num(m, 1)} | {n} |" for u, f, m, n in accounts] + [""]
    if errors:
        out += ["Gagal dibaca:", *errors, ""]
    out += [f"## {top} post teratas", "", "| kelipatan | akun | format | hook (baris pertama caption) | angka |",
            "|---:|---|---|---|---|"]
    for m in posts[:top]:
        fmt = "Reel" if m.get("media_product_type") == "REELS" else \
            "Carousel" if m.get("media_type") == "CAROUSEL_ALBUM" else "Foto"
        hook = m["hook"].replace("|", "/") or "(tanpa caption)"
        out.append(f"| {_num(m['multiple'], 1)}x | @{m['account']} | {fmt} | [{hook}]({m.get('permalink')}) | "
                   f"{m.get('like_count') or 0}♥ {m.get('comments_count') or 0}💬 |")
    out += ["", "Langkah berikutnya: jalankan `/ig-viral` di Claude Code dengan file ini untuk menamai formula hook "
            "tiap post dan memilih pola yang layak ditiru di kartu/caption kita."]
    text = "\n".join(out)
    if save:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, f"swipe-{acct.key}-{wib(utcnow()):%Y%m%d}.md")
        with open(path, "w") as f:
            f.write(text + "\n")
        text += f"\n\n(disimpan: {path})"
    return text
