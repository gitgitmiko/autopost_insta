"""Caption otomatis (Bahasa Indonesia) untuk Instagram & Facebook."""
import re
from datetime import timezone
from urllib.parse import urlparse

from ..config import GAME_TOPICS, TRACKED_COINS
from . import settings
from .content import publisher_name

BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
         "November", "Desember"]
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
# Instagram membatasi maks. 5 hashtag per post/Reel sejak 18 Des 2025 (sebelumnya 30): tag ke-6 dst. tidak dihitung.
IG_MAX, IG_MAX_TAGS, FB_MAX_TAGS = 2200, 5, 5
SPECIFIC_TAGS = 3  # dari 5 slot: maks. 3 tag spesifik (aset/topik), sisanya tag akun (urutan di social_accounts.json)

# Karakter tak terlihat (zero-width, BOM, soft hyphen, tag Unicode) yang sering terbawa dari teks hasil scrape:
# merusak hashtag & pencarian IG dan tampil sebagai kotak di kartu. ZWJ di antara emoji (mis. 👨‍💻) dipertahankan.
_EMOJI = "\U0001F000-\U0001FAFF\u2600-\u27BF"
_INVISIBLE = re.compile("[\u200b\u200c\u2060\ufeff\u00ad\u180e\u061c\U000E0000-\U000E007F]"
                        f"|(?<![{_EMOJI}\ufe0f])\u200d|\u200d(?![{_EMOJI}])")
_ODD_SPACE = re.compile("[\u00a0\u202f\u2007\u2009\u200a]")

# Satu ajakan per post (komentar / simpan / bagikan): sinyal yang paling dihitung algoritme IG.
# Dipilih bergantian per artikel supaya feed tidak terasa template.
CTA = {
    "game": ["Menurut kamu gimana? Tulis pendapatmu di komentar 👇",
             "Tag teman mabarmu yang wajib tahu kabar ini 👇",
             "Simpan postingan ini biar nggak ketinggalan update 🔖"],
    "politik": ["Bagaimana pendapatmu? Sampaikan di komentar dengan sopan 👇",
                "Bagikan ke teman yang perlu tahu kabar ini 📤",
                "Simpan postingan ini untuk referensi 🔖"],
    "saham": ["Menurutmu efeknya ke pasar positif atau negatif? Tulis di komentar 👇",
              "Bagikan ke teman sesama investor 📤",
              "Simpan postingan ini untuk bahan analisis 🔖"],
    "crypto": ["Kamu bullish atau bearish? Tulis di komentar 👇",
               "Bagikan ke teman yang juga main crypto 📤",
               "Simpan postingan ini untuk bahan riset 🔖"],
}
RECAP_CTA = "Bagikan rekap ini ke teman sesama investor 📤"

CATEGORY = {
    "saham": {"label": "Saham", "icon": "📈", "tags": ["saham", "IHSG", "investasi", "pasarmodal", "bursaefekindonesia",
                                                     "beritasaham", "investor"]},
    "crypto": {"label": "Crypto", "icon": "🪙", "tags": ["crypto", "kripto", "bitcoin", "blockchain", "beritacrypto",
                                                       "cryptocurrency"]},
    "politik": {"label": "Politik", "icon": "🏛️", "tags": ["politik", "beritaterkini", "indonesia", "beritapolitik",
                                                         "nasional"]},
    "game": {"label": "Game", "icon": "🎮", "tags": ["gaming", "game", "gamer", "beritagame", "videogame"]},
}
TOPIC_ICON = {"valorant": "🎯", "dota2": "🛡️"}
DISCLAIMER = ("⚠️ Konten ini hanya informasi, bukan ajakan membeli atau menjual aset apa pun. "
              "Selalu lakukan riset sendiri (DYOR).")
FG_ID = {"Extreme Fear": "Sangat Takut", "Fear": "Takut", "Neutral": "Netral", "Greed": "Serakah",
         "Extreme Greed": "Sangat Serakah"}


# --- format angka/tanggal gaya Indonesia ---
def num(x, dec=0):
    s = f"{x:,.{dec}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def pct(x, dec=2):
    return ("+" if x > 0 else "") + num(x, dec) + "%"


def rupiah(x):
    if x >= 1000:
        return "Rp" + num(x)
    if x >= 1:
        return "Rp" + num(x, 2)
    dec = min(8, max(2, -int(f"{x:e}".split("e")[1]) + 2))
    return "Rp" + num(x, dec)


def tanggal(d, with_day=True):
    s = f"{d.day} {BULAN[d.month - 1]} {d.year}"
    return f"{HARI[d.weekday()]}, {s}" if with_day else s


def wib(dt_utc):
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(settings.TZ)


def clean_text(text):
    """Buang karakter tak terlihat & samakan spasi aneh jadi spasi biasa."""
    return _ODD_SPACE.sub(" ", _INVISIBLE.sub("", text or ""))


def cta_line(category, seed):
    options = CTA.get(category) or []
    return options[(seed or 0) % len(options)] if options else None


def _hashtag(s):
    t = re.sub(r"[^0-9A-Za-z_]", "", s)
    return "#" + t if t and not t.isdigit() else None


def hashtags(category, assets=(), extra=(), limit=IG_MAX_TAGS, base=None):
    """Maks. `limit` hashtag: dulu yang spesifik (aset, topik; maks. SPECIFIC_TAGS), lalu tag akun/kategori,
    lalu sisa tag spesifik bila masih ada slot."""
    specific = []
    for code in assets:
        if code == "^JKSE":
            specific.append("IHSG")
        elif code in TRACKED_COINS:
            specific += [TRACKED_COINS[code][0], (TRACKED_COINS[code][1] or [""])[0]]
        elif not code.startswith("^"):
            specific.append(code)
    specific += list(extra)
    out, seen = [], set()

    def add(tags, upto):
        for t in tags:
            h = _hashtag(t)
            if len(out) >= upto:
                return
            if h and h.lower() not in seen:
                seen.add(h.lower())
                out.append(h)

    add(specific, min(SPECIFIC_TAGS, limit))
    add(list(base or CATEGORY[category]["tags"]), limit)
    add(specific, limit)
    return " ".join(out)


def _finish(text, platform):
    text = clean_text(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if platform == "instagram" and len(text) > IG_MAX:
        text = text[:IG_MAX - 1].rsplit("\n", 1)[0]
    return text


def sentiment_line(sent):
    if not sent or sent.method == "skipped":
        return None
    return {"positif": "📈 Sentimen berita: Positif", "negatif": "📉 Sentimen berita: Negatif",
            "netral": "➖ Sentimen berita: Netral"}[sent.label]


def _tag_limit(platform):
    return IG_MAX_TAGS if platform == "instagram" else FB_MAX_TAGS


IG_COMMENT_MAX = 2000  # batas aman per komentar Instagram (maks. resmi 2.200)
MAX_COMMENTS = 2
FB_BODY_MAX = 6000
CONTINUE_NOTE = "⬇️ Lanjutan ada di kolom komentar"


def _split_long(text, limit):
    """Pecah paragraf yang lebih panjang dari limit di batas kalimat."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sent) + 1 > limit:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return [c[:limit] for c in out]


def article_paragraphs(item):
    """Isi artikel sebagai daftar paragraf, diawali ringkasan bila ringkasan itu belum ada di isi."""
    from .content import similar
    paras = [p.strip() for p in (item.article.content or "").split("\n\n") if p.strip()]
    lead = (item.body or "").rstrip("…").strip()
    if lead and not any(similar(lead, p) > 0.45 or lead[:60] in p for p in paras[:3]):
        paras.insert(0, item.body)
    return paras or ([item.body] if item.body else [])


def _join(paras):
    """Gabung paragraf dengan baris kosong, tapi poin list (•) yang berurutan cukup satu baris baru."""
    out = ""
    for i, p in enumerate(paras):
        if i:
            out += "\n" if p.startswith("• ") and paras[i - 1].startswith("• ") else "\n\n"
        out += p
    return out


def slide_narration(item):
    """Lanjutan narasi untuk slide 2+: sisa ringkasan yang terpotong di slide 1, lalu paragraf isi berikutnya
    (paragraf yang sama dengan ringkasan slide 1 dilewati)."""
    from .content import similar
    paras = article_paragraphs(item)
    if getattr(item, "card_lead_unused", False):  # slide 1 hanya memuat judul: narasi mulai dari ringkasan
        return paras
    lead = (item.body or "").rstrip("…").strip()
    if lead:
        paras = [p for p in paras if p != item.body and not (similar(p, lead) > 0.45 or lead[:60] in p
                                                               or p[:60] in lead)]
    rest = getattr(item, "card_rest", "")
    return ([f"…{rest}"] if rest else []) + paras


def _pack(paras, limit):
    """Ambil paragraf berurutan selama total panjang <= limit. Return (dipakai, sisa)."""
    used, size = [], 0
    queue = list(paras)
    while queue:
        p = queue[0]
        add = len(p) + (1 if used and p.startswith("• ") and used[-1].startswith("• ") else 2 if used else 0)
        if size + add <= limit:
            used.append(queue.pop(0))
            size += add
        elif not used and len(p) > limit:  # paragraf pertama terlalu panjang: pecah per kalimat
            pieces = _split_long(p, limit)
            queue[0:1] = pieces
            if len(pieces) == 1:
                used.append(queue.pop(0)[:limit])
                break
        else:
            break
    return used, queue


def news_caption(item, platform, acct, music=None, reel=True):
    caption, _ = news_texts(item, platform, acct, music, reel)
    return caption


def news_texts(item, platform, acct, music=None, reel=True):
    """Caption + daftar komentar lanjutan. Instagram: isi yang tidak muat di caption (2.200 karakter)
    dilanjutkan di maks. 2 komentar. Facebook: isi lengkap langsung di postingan.
    music: baris kredit lagu (hanya Instagram — Facebook memakai foto tanpa lagu).
    reel: Instagram berlagu diposting sebagai Reel (False: carousel feed berlagu, tetap bisa digeser)."""
    a, cat = item.article, CATEGORY[item.article.category]
    published = wib(a.published_at)
    publisher = publisher_name(item.source.name)
    domain = urlparse(a.url).netloc.replace("www.", "")
    icon = TOPIC_ICON.get(item.topic, cat["icon"])
    head = f"{icon} {a.title}"

    tail = []
    extra = getattr(item, "extra_slides", 0)
    em = getattr(item, "extra_media", {}) or {}
    if extra and platform == "instagram":
        what = " & ".join(x for x in (f"{em.get('image')} gambar" if em.get("image") else "",
                                       f"{em.get('video')} video" if em.get("video") else "") if x)
        # Reel berlagu tidak bisa digeser; carousel (berlagu atau tidak) bisa
        tail.append(f"▶️ Tonton sampai habis: ada {what} dari artikel" if music and reel else
                    f"🖼️ Geser untuk melihat {what} dari artikel")
    elif em.get("image") and platform == "facebook":
        tail.append(f"🖼️ {em['image']} gambar tambahan dari artikel ada di album ini")
    use_bio = platform == "instagram" and acct.bio_slug  # link di caption IG tidak bisa diklik
    if getattr(item, "youtube", None):
        if use_bio:
            tail.append("🎬 Link video ada di bio (klik profil kami)")
        else:
            tail.extend(f"🎬 Video: https://youtu.be/{yid}" for yid in item.youtube)
    if a.category in ("saham", "crypto"):
        tail.append(sentiment_line(item.sentiment))
    src = f"📰 Sumber: {publisher} · {tanggal(published.date(), False)}, {published:%H.%M} WIB"
    if item.photo_used or em.get("image"):
        src += f"\n📷 Foto: {publisher}"
    if em.get("video") and platform == "instagram":
        src += f"\n🎥 Video: {publisher}"
    if music and platform == "instagram":
        src += f"\n{music}"
    tail.append(src)
    tail.append(f"🔗 Baca selengkapnya: {a.url}" if platform == "facebook" else
                f"🔗 Link artikel lengkap ada di bio · {domain}" if use_bio else f"🔗 Baca selengkapnya di {domain}")
    if a.category in ("saham", "crypto"):
        tail.append(DISCLAIMER)
    topic_tags = GAME_TOPICS[item.topic]["hashtags"] if item.topic in GAME_TOPICS else ()
    tail.append(hashtags(a.category, item.assets, topic_tags, _tag_limit(platform), acct.hashtags))
    tail = [t for t in tail if t]
    cta = cta_line(a.category, a.id)
    tail = ([cta] if cta else []) + tail

    paras = [clean_text(p) for p in article_paragraphs(item)]
    if platform == "facebook":
        body, rest = _pack(paras, FB_BODY_MAX)
        if rest:
            body.append("…")
        return _finish("\n\n".join([head, _join(body)] + tail), platform), []

    fixed = len(head) + sum(len(t) + 2 for t in tail) + 4
    body, rest = _pack(paras, IG_MAX - fixed - 10)
    if rest:  # tidak muat: sisakan ruang untuk catatan lanjutan
        body, rest = _pack(paras, IG_MAX - fixed - len(CONTINUE_NOTE) - 14)
    comments = []
    if rest and not acct.comment_overflow:  # tanpa izin komentar: potong rapi + ajak baca artikel lengkap
        body.append("…")
        rest = []
    for i in range(MAX_COMMENTS):
        if not rest:
            break
        prefix = "📝 Lanjutan:\n\n" if i == 0 else ""
        chunk, rest = _pack(rest, IG_COMMENT_MAX - len(prefix) - 60)
        if not chunk:
            break
        text = prefix + _join(chunk)
        if rest and i == MAX_COMMENTS - 1:
            text += f"\n\n… Baca artikel lengkapnya di {domain}"
        comments.append(text)
    comments = [clean_text(c) for c in comments]
    parts = [head, _join(body)] + ([CONTINUE_NOTE] if comments else []) + tail
    return _finish("\n\n".join(parts), platform), comments


def _sentiment_summary(sent):
    total = sum(sent.values())
    if not total:
        return None
    pos, neg = sent["positif"], sent["negatif"]
    tone = "cenderung positif 🟢" if pos > neg * 1.2 else "cenderung negatif 🔴" if neg > pos * 1.2 else "berimbang ⚪"
    return f"📰 Sentimen {total} berita: {pos} positif · {neg} negatif · {sent['netral']} netral → {tone}"


def stock_recap_caption(r, platform, acct, music=None):
    arah = "menguat" if r.ihsg_change > 0 else "melemah" if r.ihsg_change < 0 else "stagnan"
    lines = [f"📊 Rekap Pasar Saham — {tanggal(r.day)}",
             f"IHSG ditutup {arah} {num(abs(r.ihsg_change), 2)}% ke level {num(r.ihsg_close, 2)}."]
    if r.gainers:
        lines.append("🟢 Top gainers (pantauan saham big cap):\n" +
                     "\n".join(f"• {t} {pct(c)} → {num(p)}" for t, p, c in r.gainers))
    if r.losers:
        lines.append("🔴 Top losers:\n" + "\n".join(f"• {t} {pct(c)} → {num(p)}" for t, p, c in r.losers))
    lines.append(_sentiment_summary(r.sentiment))
    if r.headlines:
        lines.append("🗞️ Berita penggerak hari ini:\n" + "\n".join(f"• {t} ({p})" for t, p in r.headlines))
    lines += [RECAP_CTA, music if platform == "instagram" else None, DISCLAIMER, hashtags("saham", ["^JKSE"] + [g[0] for g in r.gainers[:2]], limit=_tag_limit(platform),
                                   base=acct.hashtags)]
    return _finish("\n\n".join(x for x in lines if x), platform)


def crypto_recap_caption(r, platform, acct, music=None):
    now = wib(r.captured_at)
    lines = [f"🪙 Rekap Pasar Crypto — {tanggal(now.date())}, {now:%H.%M} WIB"]
    if r.fear_greed:
        v, cls, prev = r.fear_greed
        delta = f" (kemarin {prev})" if prev is not None else ""
        lines.append(f"😨 Crypto Fear & Greed Index: {v}/100 — {FG_ID.get(cls, cls)}{delta}")
    lines.append("💰 Harga & perubahan 24 jam:\n" + "\n".join(
        f"{'🟢' if c > 0 else '🔴' if c < 0 else '⚪'} {s} {rupiah(p)} ({pct(c)})" for s, _, p, c in r.coins))
    lines.append(_sentiment_summary(r.sentiment))
    if r.headlines:
        lines.append("🗞️ Berita terkini:\n" + "\n".join(f"• {t} ({p})" for t, p in r.headlines))
    lines += [RECAP_CTA, music if platform == "instagram" else None, DISCLAIMER, hashtags("crypto", ["bitcoin", "ethereum"], limit=_tag_limit(platform), base=acct.hashtags)]
    return _finish("\n\n".join(x for x in lines if x), platform)


def steam_deals_caption(deals, platform, acct, music=None, reel=True):
    items = deals.items
    lines = [f"🔥 Promo Steam — {tanggal(wib(deals.captured_at).date())}",
             f"{len(items)} game populer lagi diskon besar di Steam (harga Indonesia):"]
    lines.append("\n".join(
        f"🎮 {i['title']} — -{i['disc']}% jadi {'Gratis' if not i['final'] else 'Rp' + num(i['final'])}"
        + (f" (dari Rp{num(i['orig'])})" if i["orig"] and i["orig"] != i["final"] else "")
        for i in items))
    with_music = music and platform == "instagram"
    reel = with_music and reel  # Reel berlagu tidak bisa digeser; carousel berlagu bisa
    lines.append("⭐ Semua game berating ulasan positif " + f"{min((i['rating'] or 0) for i in items)}%+. "
                 + ("Tonton sampai habis ▶️" if reel else "Geser untuk melihat semua ➡️"))
    if platform == "instagram" and acct.bio_slug:
        lines.append("🔗 Link tiap game ada di bio")
    else:
        lines.append("🔗 Lihat semua: https://store.steampowered.com/specials")
    lines.append("Harga dapat berubah sewaktu-waktu — cek langsung di Steam sebelum membeli.")
    lines.append("Mana yang masuk wishlist kamu? Tulis di komentar! 👇")
    if with_music:
        lines.append(music)
    lines.append(hashtags("game", (), ("steam", "steamsale", "diskongame", "pcgaming"), _tag_limit(platform),
                          acct.hashtags))
    return _finish("\n\n".join(lines), platform)
