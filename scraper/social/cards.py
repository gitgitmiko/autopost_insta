"""Render gambar postingan 1080x1350 (4:5) dengan Pillow."""
import os
import re
import subprocess
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..media import image_abspath
from . import settings
from .captions import FG_ID, num, pct, rupiah, tanggal, wib
from .content import publisher_name

W, H = 1080, 1350
PAD = 64
WHITE, MUTED, DIM = (255, 255, 255), (200, 206, 216), (140, 148, 160)
GREEN, RED, GREY = (34, 197, 94), (239, 68, 68), (148, 163, 184)
THEME = {
    "saham": {"bg": (11, 25, 44), "bg2": (17, 52, 74), "accent": (34, 197, 94), "label": "SAHAM"},
    "crypto": {"bg": (20, 14, 38), "bg2": (52, 30, 74), "accent": (247, 147, 26), "label": "CRYPTO"},
    "politik": {"bg": (30, 12, 18), "bg2": (78, 20, 32), "accent": (239, 68, 68), "label": "POLITIK"},
    "game": {"bg": (16, 12, 40), "bg2": (44, 28, 96), "accent": (139, 92, 246), "label": "GAME"},
}
# Tema topik game khusus (menggantikan tema kategori pada slot topik)
TOPIC_THEME = {
    "valorant": {"bg": (15, 25, 35), "bg2": (52, 22, 30), "accent": (255, 70, 85), "label": "VALORANT"},
    "dota2": {"bg": (20, 14, 14), "bg2": (64, 22, 18), "accent": (210, 62, 42), "label": "DOTA 2"},
}


@lru_cache(maxsize=64)
def font(weight, size):
    path = os.path.join(settings.FONT_DIR, f"Montserrat-{weight}.ttf")
    if not os.path.exists(path):
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if weight != "Medium" else "") + ".ttf"
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_text(draw, text, weight, sizes, max_w, max_lines):
    """Ukuran font terbesar yang muat; jika tetap tidak muat, potong dengan elipsis."""
    for size in sizes:
        f = font(weight, size)
        lines = wrap(draw, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    lines = lines[:max_lines]
    while lines and draw.textlength(lines[-1] + "…", font=f) > max_w:
        lines[-1] = lines[-1].rsplit(" ", 1)[0]
    lines[-1] += "…"
    return f, lines


def draw_lines(draw, xy, lines, fnt, fill, spacing=1.22):
    x, y = xy
    lh = int(fnt.size * spacing)
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += lh
    return y


def gradient(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        base.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return base.resize((w, h))


def triangle(draw, x, y, size, up, fill):
    pts = [(x, y + size), (x + size, y + size), (x + size / 2, y)] if up else \
          [(x, y), (x + size, y), (x + size / 2, y + size)]
    draw.polygon(pts, fill=fill)


def chip(draw, x, y, text, bg, fg=WHITE, size=28, arrow=None):
    f = font("Bold", size)
    tw = draw.textlength(text, font=f)
    extra = size + 14 if arrow is not None else 0
    h = size + 26
    draw.rounded_rectangle((x, y, x + tw + 48 + extra, y + h), radius=h // 2, fill=bg)
    if arrow is not None:
        triangle(draw, x + 24, y + 13 + 2, size - 4, arrow, fg)
    draw.text((x + 24 + extra, y + 12), text, font=f, fill=fg)
    return x + tw + 48 + extra


def base_canvas(theme):
    img = gradient((W, H), theme["bg2"], theme["bg"])
    return img, ImageDraw.Draw(img)


def header(draw, theme, acct, label=None):
    """Judul jenis konten (mis. REKAP SAHAM) di kiri + nama akun di kanan. Label kategori tidak lagi ditulis."""
    if label:
        chip(draw, PAD, PAD, label, theme["accent"], (10, 10, 10), size=26)
    f = font("ExtraBold", 28)
    tw = draw.textlength(acct.brand_name, font=f)
    draw.rounded_rectangle((W - PAD - tw - 40, PAD, W - PAD, PAD + 54), radius=27, fill=(0, 0, 0, 140))
    draw.text((W - PAD - tw - 20, PAD + 11), acct.brand_name, font=f, fill=WHITE)


def footer(draw, left, theme, acct):
    y = H - PAD - 40
    draw.line((PAD, y - 24, W - PAD, y - 24), fill=(255, 255, 255, 60), width=2)
    f = font("Medium", 24)
    fh = font("Bold", 24)
    hw = draw.textlength(acct.brand_handle, font=fh)
    room = W - 2 * PAD - hw - 30  # teks kiri tidak boleh menabrak handle akun
    while left and draw.textlength(left, font=f) > room:
        left = left[:-2].rstrip() + "…"
    draw.text((PAD, y), left, font=f, fill=MUTED)
    draw.text((W - PAD - hw, y), acct.brand_handle, font=fh, fill=theme["accent"])


def _photo_area(img, theme, image_rel, height=640, use_photo=False):
    """Tempel foto berita (cover-crop) + gradasi ke warna latar; tanpa foto: pola dekoratif."""
    if image_rel and use_photo and os.path.exists(image_abspath(image_rel)):
        try:
            photo = ImageOps.fit(Image.open(image_abspath(image_rel)).convert("RGB"), (W, height))
            photo = Image.blend(photo, Image.new("RGB", photo.size, (0, 0, 0)), 0.25)  # header tetap terbaca
            # mask: foto penuh di atas, memudar ke latar gradasi di bagian bawah
            mask = Image.new("L", (1, height))
            for y in range(height):
                t = max(0.0, (y - height * 0.45) / (height * 0.55))
                mask.putpixel((0, y), int(255 * (1 - t) ** 1.6))
            region = img.crop((0, 0, W, height))
            img.paste(Image.composite(photo, region, mask.resize((W, height))), (0, 0))
            # gradasi gelap di atas agar badge kategori & nama akun tetap terbaca
            top = Image.new("L", (1, 220))
            for y in range(220):
                top.putpixel((0, y), int(200 * (1 - y / 220) ** 1.5))
            img.paste(Image.new("RGB", (W, 220), (0, 0, 0)), (0, 0), top.resize((W, 220)))
            return True
        except OSError:
            pass
    deco = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    for i, r in enumerate((520, 380, 240)):
        d.ellipse((W - r - 40 + i * 30, -r // 3, W + r // 2, r), outline=theme["accent"] + (40 + 25 * i,), width=6)
    img.paste(deco, (0, 0), deco.filter(ImageFilter.GaussianBlur(0.6)))
    return False


NARR_FONT, NARR_LH, NARR_GAP = 31, 44, 16
PAPER, INK, INK_MUTED = (250, 250, 248), (24, 24, 28), (110, 112, 120)
LAYOUTS = ("bottom", "top", "float")  # posisi panel teks di slide 2+: bawah, atas, kotak mengambang di atas foto
TEXT_MAX_H = {"bottom": 560, "top": 560, "float": 470}  # tinggi maks. blok teks (sisanya untuk media)


def _draw_narration(draw, paras, x, y, max_w, max_y, accent, fill=INK):
    """Gambar lanjutan narasi mulai (x, y) sampai max_y. Paragraf yang tidak muat dipotong di batas kalimat
    (atau kata, bila satu kalimat pun tidak muat) dan sisanya dikembalikan untuk slide berikutnya.
    Return (sisa paragraf, y akhir)."""
    f = font("Medium", NARR_FONT)
    rest, cur = list(paras), y

    def put(lines):
        nonlocal cur
        for ln in lines:
            draw.text((x, cur), ln, font=f, fill=fill)
            cur += NARR_LH
        cur += NARR_GAP

    while rest:
        lines = wrap(draw, rest[0], f, max_w)
        if cur + len(lines) * NARR_LH <= max_y:
            put(lines)
            rest.pop(0)
            continue
        sents = re.split(r"(?<=[.!?…])\s+", rest[0])
        fit_n, fit_lines = 0, []
        for i in range(1, len(sents) + 1):
            cand = wrap(draw, " ".join(sents[:i]), f, max_w)
            if cur + len(cand) * NARR_LH > max_y:
                break
            fit_n, fit_lines = i, cand
        if fit_n:
            put(fit_lines)
            rest[0] = " ".join(sents[fit_n:])
        elif cur == y:  # satu kalimat pun tidak muat di slide kosong: potong per kata
            k = max(1, int((max_y - cur) // NARR_LH))
            put(lines[:k - 1] + [lines[k - 1] + " …"])
            rest[0] = "… " + " ".join(" ".join(lines[k:]).split())
        break
    if cur > y:  # garis aksen di sisi kiri blok narasi
        draw.rectangle((x - 30, y + 4, x - 22, cur - NARR_GAP - 8), fill=accent)
    return [r for r in rest if r.strip()], (cur - NARR_GAP if cur > y else y)


def slide_layouts(types, seed):
    """Posisi panel teks untuk tiap slide 2+ — bergantian supaya carousel tidak monoton.
    Video tidak bisa ditimpa kotak teks (ffmpeg menempel video paling atas), jadi tidak pernah 'float'."""
    start = sum(map(ord, str(seed))) % len(LAYOUTS)
    out, prev = [], None
    for i, t in enumerate(types):
        lay = LAYOUTS[(start + i) % len(LAYOUTS)]
        if t == "video" and lay == "float":
            lay = "top" if prev == "bottom" else "bottom"
        out.append(lay)
        prev = lay
    return out


def _brand(draw, x, y, acct, on_photo=True, accent=None):
    """Nama akun di pojok (seperti logo media): pil gelap di atas foto, teks aksen di atas panel kertas."""
    f = font("ExtraBold", 28)
    tw = draw.textlength(acct.brand_name, font=f)
    if on_photo:
        draw.rounded_rectangle((x, y, x + tw + 40, y + 54), radius=27, fill=(0, 0, 0, 150))
        draw.text((x + 20, y + 11), acct.brand_name, font=f, fill=WHITE)
    else:
        draw.text((x, y + 11), acct.brand_name, font=f, fill=accent)


def _credit_chip(draw, right, bottom, text):
    fc = font("SemiBold", 22)
    tw = draw.textlength(text, font=fc)
    draw.rounded_rectangle((right - tw - 28, bottom - 38, right, bottom), radius=19, fill=(0, 0, 0, 150))
    draw.text((right - tw - 14, bottom - 32), text, font=fc, fill=WHITE)


def _media_fit(mw, mh, w, h):
    """'cover' (isi penuh, sedikit terpotong) bila rasio mirip; 'contain' (utuh) bila terlalu banyak terpotong
    — mis. infografik tinggi atau tangkapan layar lebar."""
    loss = 1 - min((w / h) / (mw / mh), (mw / mh) / (w / h))
    return "cover" if loss <= 0.3 else "contain"


def _paste_media(img, photo, box, clear=None):
    """clear: bagian box yang tidak tertutup panel teks (slide 'float') — media utuh ditaruh di situ."""
    x, y, w, h = box
    if _media_fit(photo.width, photo.height, w, h) == "cover":
        img.paste(ImageOps.fit(photo, (w, h), Image.LANCZOS), (x, y))
        return
    # utuh, latar = foto yang sama diburamkan
    bg = ImageOps.fit(photo, (w, h)).filter(ImageFilter.GaussianBlur(28))
    img.paste(Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.35), (x, y))
    cx, cy, cw, ch = clear or box
    fg = ImageOps.contain(photo, (cw, ch), Image.LANCZOS)
    img.paste(fg, (cx + (cw - fg.width) // 2, cy + (ch - fg.height) // 2))


def _media_slide_base(acct, theme, layout, credit, source_line, heading, narration):
    """Lapisan panel teks putih (bawah/atas/mengambang) untuk slide 2+, transparan di luar panel.
    Pemanggil menempel media di `box` lalu menimpakan lapisan ini.
    Return (lapisan RGBA, box(x, y, w, h), sisa narasi, area box yang tidak tertutup panel)."""
    accent = theme["accent"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    inset = 46 if layout == "float" else 0  # kotak mengambang punya margin dari tepi slide
    tx = PAD + inset + 30
    tw = W - 2 * (PAD + inset) - 30

    # ukur dulu teksnya di kanvas bayangan supaya tinggi panel pas dengan isinya
    probe = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    rest = list(narration or [])
    if rest:
        rest, end = _draw_narration(probe, rest, tx, 0, tw, TEXT_MAX_H[layout], accent)
        text_h, head = end, None
    else:  # narasi habis: judul artikel sebagai teks panel
        f_head, head = fit_text(probe, heading or "", "ExtraBold", (44, 40, 36), tw, 3)
        text_h = len(head) * int(f_head.size * 1.22)
    brand_h = 74 if layout == "top" else 0
    panel_h = 44 + brand_h + text_h + 30 + 50  # padding + (brand) + teks + jarak + baris sumber

    def text_block(top):
        if head is None:
            _draw_narration(draw, narration, tx, top, tw, top + TEXT_MAX_H[layout], accent)
        else:
            y = draw_lines(draw, (tx, top), head, f_head, INK)
            draw.rectangle((tx - 30, top + 4, tx - 22, y - 12), fill=accent)

    def source_row(bottom):
        f, fh = font("Medium", 22), font("Bold", 22)
        hw = draw.textlength(acct.brand_handle, font=fh)
        left, room = source_line, W - 2 * (PAD + inset) - hw - 30
        while left and draw.textlength(left, font=f) > room:
            left = left[:-2].rstrip() + "…"
        draw.text((PAD + inset, bottom - 40), left, font=f, fill=INK_MUTED)
        draw.text((W - PAD - inset - hw, bottom - 40), acct.brand_handle, font=fh, fill=accent)

    if layout == "bottom":
        box = (0, 0, W, H - panel_h)
        draw.rectangle((0, H - panel_h, W, H), fill=PAPER)
        text_block(H - panel_h + 44)
        source_row(H - 16)
    elif layout == "top":
        box = (0, panel_h, W, H - panel_h)
        draw.rectangle((0, 0, W, panel_h), fill=PAPER)
        _brand(draw, PAD, 30, acct, on_photo=False, accent=accent)
        text_block(44 + brand_h)
        source_row(panel_h - 16)
    else:  # float: media penuh, kotak teks putih di sepertiga bawah
        box = (0, 0, W, H)
        top = H - 130 - panel_h
        clear = (0, PAD + 70, W, top - PAD - 70)  # di bawah logo, di atas kotak teks
        draw.rectangle((PAD, top, W - PAD, top + panel_h), fill=PAPER)
        text_block(top + 44)
        source_row(top + panel_h - 16)
    box = (box[0], box[1], box[2] // 2 * 2, box[3] // 2 * 2)
    return img, box, rest, clear if layout == "float" else box


def _decorate_media(img, acct, layout, box, credit):
    """Logo akun (bila belum ada di panel) & kredit media di pojok media."""
    draw = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = box
    if layout != "top":
        _brand(draw, PAD, PAD, acct)
    # float: kredit di kanan atas supaya tidak tertutup kotak teks
    _credit_chip(draw, W - PAD, PAD + 46 if layout == "float" else y + h - 20, credit)


def image_slide(image_rel, path, acct, theme, layout, credit, source_line, heading=None, narration=None):
    """Slide gambar dari isi artikel + lanjutan narasi di panel teks. Return sisa narasi."""
    photo = Image.open(image_abspath(image_rel)).convert("RGB")
    panel, box, rest, clear = _media_slide_base(acct, theme, layout, credit, source_line, heading, narration)
    img = Image.new("RGB", (W, H), theme["bg"])
    _paste_media(img, photo, box, clear)
    img.paste(panel, (0, 0), panel)
    _decorate_media(img, acct, layout, box, credit)
    img.save(path, "JPEG", quality=93, optimize=True)
    return rest


def video_slide(video_rel, path, acct, theme, layout, credit, source_line, heading=None, max_seconds=60,
                narration=None):
    """Slide video carousel: panel teks (Pillow) + video ditempel (ffmpeg) di area media.
    Hasil MP4 1080x1350, H.264/AAC, 30 fps, maks. max_seconds detik. Return sisa narasi."""
    from ..media import FFMPEG, probe_video
    src = image_abspath(video_rel)
    vw, vh, _, has_audio = probe_video(src)
    layout = "bottom" if layout == "float" else layout
    panel, (x, y, ow, oh), rest, _ = _media_slide_base(acct, theme, layout, credit, source_line, heading, narration)
    img = Image.new("RGB", (W, H), theme["bg"])
    img.paste(panel, (0, 0), panel)
    base = path[:-4] + ".base.png"
    img.save(base)
    if _media_fit(vw, vh, ow, oh) == "cover":
        fit = f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh}"
    else:
        fit = f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2:black"
    # logo & kredit digambar di lapisan transparan di atas video
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _decorate_media(over, acct, layout, (x, y, ow, oh), credit)
    top_png = path[:-4] + ".top.png"
    over.save(top_png)
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", base, "-i", src,
           "-loop", "1", "-framerate", "30", "-i", top_png]
    if not has_audio:  # beberapa pemutar/IG lebih stabil bila ada trek audio: tambahkan audio senyap
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-filter_complex",
            f"[1:v]{fit},setsar=1,fps=30[v];[0:v][v]overlay={x}:{y}:shortest=1[m];"
            "[m][2:v]overlay=0:0:shortest=1,format=yuv420p[out]",
            "-map", "[out]", "-map", "1:a" if has_audio else "3:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high", "-level", "4.0",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-t", str(max_seconds), "-shortest", "-movflags", "+faststart", path]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=600)
    finally:
        os.remove(base)
        os.remove(top_png)
    return rest


def news_card(item, path, acct, swipe_hint=True):
    """Slide pertama: foto penuh di atas, panel warna aksen berisi judul di bawah (tanpa label kategori).
    Ada slide lanjutan: judul saja (+ ajakan geser bila swipe_hint; Reel tanpa). Satu kartu: judul + ringkasan."""
    a = item.article
    theme = TOPIC_THEME.get(item.topic) or THEME[a.category]
    accent = theme["accent"]
    panel_bg = tuple(int(c * 0.72) for c in accent)  # aksen digelapkan: teks putih tetap terbaca
    swipe = bool(getattr(item, "extra_slides", 0))
    img = Image.new("RGB", (W, H), theme["bg"])
    draw = ImageDraw.Draw(img, "RGBA")
    tx, tw = PAD + 34, W - 2 * PAD - 34

    sent = item.sentiment
    chip_h = 0
    if a.category in ("saham", "crypto") and sent and sent.method != "skipped":
        chip_h = 54 + 22
    f_title, lines = fit_text(draw, a.title, "ExtraBold", (66, 60, 54, 50, 46), tw, 5)
    title_h = len(lines) * int(f_title.size * 1.22)
    f_body = font("Medium", 31)
    body_lh = int(f_body.size * 1.4)
    body = []
    item.card_rest, item.card_lead_unused = "", swipe
    if item.body and not swipe:  # tanpa slide lanjutan: ringkasan ikut di panel
        room = int(H * 0.6) - (56 + chip_h + title_h + 26 + 90)
        max_lines = max(0, room // body_lh)
        body = wrap(draw, item.body, f_body, tw)
        if len(body) > max_lines:
            body = body[:max_lines]
            if body:
                last = body[-1].rstrip(".,;")
                while last and draw.textlength(last + "…", font=f_body) > tw:
                    last = last.rsplit(" ", 1)[0].rstrip(".,;")
                body[-1] = last + "…"
    panel_h = max(400, 56 + chip_h + title_h + (26 + len(body) * body_lh if body else 0) + 90)
    photo_h = H - panel_h

    # ---- foto (atau pola dekoratif bila tidak ada)
    item.photo_used = False
    if acct.use_article_photo and item.image_path and os.path.exists(image_abspath(item.image_path)):
        try:
            photo = Image.open(image_abspath(item.image_path)).convert("RGB")
            img.paste(ImageOps.fit(photo, (W, photo_h), Image.LANCZOS), (0, 0))
            shade = Image.new("L", (1, 200))  # gradasi gelap tipis di atas: logo & ajakan geser terbaca
            for y in range(200):
                shade.putpixel((0, y), int(150 * (1 - y / 200) ** 1.6))
            img.paste(Image.new("RGB", (W, 200), (0, 0, 0)), (0, 0), shade.resize((W, 200)))
            item.photo_used = True
        except OSError:
            pass
    if not item.photo_used:
        _photo_area(img, theme, None, height=photo_h)
    draw = ImageDraw.Draw(img, "RGBA")
    _brand(draw, PAD, PAD, acct)
    if item.photo_used:
        _credit_chip(draw, W - PAD, photo_h - 22, f"Foto: {publisher_name(item.source.name)}")
    if swipe and swipe_hint:  # ajakan geser di kanan atas, seperti "Slide Kedua →"
        fh = font("ExtraBold", 32)
        hint = "Geser"
        hw = draw.textlength(hint, font=fh)
        hx, hy = W - PAD - hw - 10, PAD + 6
        draw.text((hx + 2, hy + 2), hint, font=fh, fill=(0, 0, 0, 140))
        draw.text((hx, hy), hint, font=fh, fill=WHITE)
        ay = hy + 48
        draw.line((hx - 20, ay, W - PAD, ay), fill=WHITE, width=4)
        draw.polygon([(W - PAD + 4, ay), (W - PAD - 12, ay - 9), (W - PAD - 12, ay + 9)], fill=WHITE)

    # ---- panel judul
    draw.rectangle((0, photo_h, W, H), fill=panel_bg)
    y = photo_h + 56
    if chip_h:
        color, up = {"positif": (GREEN, True), "negatif": (RED, False), "netral": (GREY, None)}[sent.label]
        chip(draw, PAD, y, f"SENTIMEN {sent.label.upper()}", color, size=24, arrow=up)
        y += chip_h
    end = draw_lines(draw, (tx, y), lines, f_title, WHITE)
    draw.rectangle((PAD, y + 6, PAD + 12, end - 16), fill=WHITE)
    if body:
        draw_lines(draw, (tx, end + 26), body, f_body, (244, 244, 248), spacing=1.4)
    published = wib(a.published_at)
    f, fh = font("Medium", 23), font("Bold", 23)
    src = f"Sumber: {publisher_name(item.source.name)} · {published:%d/%m/%Y %H.%M} WIB"
    hw = draw.textlength(acct.brand_handle, font=fh)
    while draw.textlength(src, font=f) > W - 2 * PAD - hw - 30:
        src = src[:-2].rstrip() + "…"
    draw.text((PAD, H - PAD - 24), src, font=f, fill=(235, 235, 240))
    draw.text((W - PAD - hw, H - PAD - 24), acct.brand_handle, font=fh, fill=WHITE)
    img.save(path, "JPEG", quality=92, optimize=True)
    return path


def sentiment_bar(draw, y, sent, title):
    total = sum(sent.values())
    draw.text((PAD, y), title, font=font("Bold", 28), fill=WHITE)
    y += 52
    x0, x1, h = PAD, W - PAD, 26
    draw.rounded_rectangle((x0, y, x1, y + h), radius=h // 2, fill=(255, 255, 255, 30))
    if total:
        x = x0
        for key, color in (("positif", GREEN), ("netral", GREY), ("negatif", RED)):
            w = (x1 - x0) * sent[key] / total
            if w >= 1:
                draw.rectangle((x, y, x + w, y + h), fill=color)
                x += w
    y += h + 16
    f = font("SemiBold", 24)
    x = PAD
    for key, color in (("positif", GREEN), ("netral", GREY), ("negatif", RED)):
        draw.ellipse((x, y + 6, x + 16, y + 22), fill=color)
        t = f"{sent[key]} {key}"
        draw.text((x + 26, y), t, font=f, fill=MUTED)
        x += 26 + draw.textlength(t, font=f) + 40
    return y + 40


def stock_recap_card(r, path, acct):
    theme = THEME["saham"]
    img, _ = base_canvas(theme)
    _photo_area(img, theme, None, height=520)
    draw = ImageDraw.Draw(img, "RGBA")
    header(draw, theme, acct, "REKAP SAHAM")

    draw.text((PAD, 170), "IHSG", font=font("Bold", 40), fill=MUTED)
    draw.text((PAD, 220), num(r.ihsg_close, 2), font=font("ExtraBold", 120), fill=WHITE)
    up = r.ihsg_change >= 0
    color = GREEN if up else RED
    triangle(draw, PAD + 4, 380, 40, up, color)
    draw.text((PAD + 60, 368), pct(r.ihsg_change), font=font("ExtraBold", 56), fill=color)
    draw.text((PAD, 452), tanggal(r.day), font=font("Medium", 30), fill=MUTED)

    col_w = (W - 2 * PAD - 40) // 2
    for ci, (title, rows, color) in enumerate((("TOP GAINERS", r.gainers, GREEN), ("TOP LOSERS", r.losers, RED))):
        x = PAD + ci * (col_w + 40)
        y = 560
        draw.rounded_rectangle((x, y, x + col_w, y + 470), radius=28, fill=(255, 255, 255, 18))
        draw.text((x + 30, y + 26), title, font=font("ExtraBold", 28), fill=color)
        y += 90
        for t, p, c in rows[:5]:
            draw.text((x + 30, y), t, font=font("ExtraBold", 36), fill=WHITE)
            pc = pct(c)
            fpc = font("Bold", 32)
            draw.text((x + col_w - 30 - draw.textlength(pc, font=fpc), y + 2), pc, font=fpc, fill=color)
            draw.text((x + 30, y + 42), num(p), font=font("Medium", 22), fill=DIM)
            y += 74
        if not rows:
            draw.text((x + 30, y), "—", font=font("Bold", 36), fill=DIM)

    sentiment_bar(draw, 1070, r.sentiment, "Sentimen berita saham hari ini")
    footer(draw, "Bukan rekomendasi investasi · Data: Yahoo Finance", theme, acct)
    img.save(path, "JPEG", quality=92, optimize=True)
    return path


def crypto_recap_card(r, path, acct):
    theme = THEME["crypto"]
    img, _ = base_canvas(theme)
    _photo_area(img, theme, None, height=520)
    draw = ImageDraw.Draw(img, "RGBA")
    header(draw, theme, acct, "REKAP CRYPTO")
    now = wib(r.captured_at)
    draw.text((PAD, 160), f"{tanggal(now.date())} · {now:%H.%M} WIB", font=font("Medium", 30), fill=MUTED)

    y = 225
    if r.fear_greed:
        v, cls, _ = r.fear_greed
        draw.text((PAD, y), "FEAR & GREED INDEX", font=font("Bold", 28), fill=MUTED)
        draw.text((PAD, y + 40), str(v), font=font("ExtraBold", 110), fill=WHITE)
        vx = PAD + draw.textlength(str(v), font=font("ExtraBold", 110)) + 30
        draw.text((vx, y + 92), FG_ID.get(cls, cls), font=font("ExtraBold", 44), fill=theme["accent"])
        bar_y, x0, x1 = y + 190, PAD, W - PAD
        grad = Image.new("RGB", (x1 - x0, 22))
        for x in range(x1 - x0):
            t = x / (x1 - x0)
            c = tuple(int(RED[i] + (GREEN[i] - RED[i]) * t) for i in range(3)) if t < 1 else GREEN
            ImageDraw.Draw(grad).line((x, 0, x, 22), fill=c)
        mask = Image.new("L", grad.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, grad.size[0] - 1, 21), radius=11, fill=255)
        img.paste(grad, (x0, bar_y), mask)
        mx = x0 + (x1 - x0) * v / 100
        draw.ellipse((mx - 18, bar_y - 7, mx + 18, bar_y + 29), fill=WHITE, outline=(0, 0, 0), width=4)
        y = bar_y + 70

    row = 64
    draw.rounded_rectangle((PAD - 10, y, W - PAD + 10, y + row * len(r.coins) + 30), radius=28,
                           fill=(255, 255, 255, 18))
    y += 22
    for sym, name, p, c in r.coins:
        color = GREEN if c > 0 else RED if c < 0 else GREY
        draw.text((PAD + 20, y + 4), sym, font=font("ExtraBold", 34), fill=WHITE)
        if name and name.upper() != sym:
            draw.text((PAD + 170, y + 12), name[:14], font=font("Medium", 24), fill=DIM)
        pr = rupiah(p)
        fp = font("Bold", 32)
        draw.text((W - PAD - 220 - draw.textlength(pr, font=fp), y + 6), pr, font=fp, fill=WHITE)
        pc = pct(c)
        fc = font("Bold", 30)
        draw.text((W - PAD - 20 - draw.textlength(pc, font=fc), y + 8), pc, font=fc, fill=color)
        y += row
    sentiment_bar(draw, max(y + 40, 1060), r.sentiment, "Sentimen berita crypto 24 jam")
    footer(draw, "Bukan rekomendasi investasi · Data: CoinGecko", theme, acct)
    img.save(path, "JPEG", quality=92, optimize=True)
    return path


# ---------------------------------------------------------------- Promo Steam: cover + slide grid 2x2
STEAM_GREEN, STEAM_GREEN_TXT = (76, 107, 34), (164, 208, 7)
PER_SLIDE = 4


def _rounded_paste(img, tile, xy, radius=22):
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius=radius, fill=255)
    img.paste(tile, xy, mask)


def _steam_cover(appid, w, h):
    """Sampul game ukuran (w, h): sampul portrait Steam di-crop; bila tidak ada, header dipasang di atas latar blur."""
    from ..media import steam_art
    rel = steam_art(appid, "library_600x900.jpg")
    if rel:
        return ImageOps.fit(Image.open(image_abspath(rel)).convert("RGB"), (w, h), centering=(0.5, 0.4))
    rel = steam_art(appid, "header.jpg")
    bg = Image.new("RGB", (w, h), (30, 24, 64))
    if rel:
        hd = Image.open(image_abspath(rel)).convert("RGB")
        bg = ImageOps.fit(hd, (w, h)).filter(ImageFilter.GaussianBlur(18))
        fitted = hd.resize((w, int(hd.height * w / hd.width)))
        bg.paste(fitted, (0, (h - fitted.height) // 2))
    return bg


def _steam_cell(item, w, h, theme):
    info_h = 112
    cell = Image.new("RGB", (w, h), (24, 19, 52))
    cell.paste(_steam_cover(item["appid"], w, h - info_h), (0, 0))
    d = ImageDraw.Draw(cell, "RGBA")
    if item.get("rating"):  # chip rating ulasan di pojok kiri atas sampul
        txt = f"{item['rating']}% positif"
        f = font("SemiBold", 20)
        tw = d.textlength(txt, font=f)
        d.rounded_rectangle((12, 12, 12 + tw + 24, 48), radius=18, fill=(0, 0, 0, 165))
        d.text((24, 17), txt, font=f, fill=WHITE)
    y = h - info_h
    d.rectangle((0, y, w, h), fill=(26, 21, 56))
    f_title, lines = fit_text(d, item["title"], "SemiBold", (26, 24, 22), w - 28, 1)
    d.text((14, y + 8), lines[0], font=f_title, fill=WHITE)
    badge = f"-{item['disc']}%"
    fb = font("ExtraBold", 34)
    bw = d.textlength(badge, font=fb) + 26
    d.rectangle((14, y + 50, 14 + bw, y + 100), fill=STEAM_GREEN)
    d.text((27, y + 56), badge, font=fb, fill=STEAM_GREEN_TXT)
    px = 14 + bw + 14
    if item.get("orig") and item["orig"] != item["final"]:
        old = "Rp" + num(item["orig"])
        fo = font("Medium", 19)
        d.text((px, y + 44), old, font=fo, fill=DIM)
        d.line((px, y + 55, px + d.textlength(old, font=fo), y + 55), fill=DIM, width=2)
    price = "Gratis" if not item["final"] else "Rp" + num(item["final"])
    f_price = font("ExtraBold", 30)
    while d.textlength(price, font=f_price) > w - px - 12 and f_price.size > 22:
        f_price = font("ExtraBold", f_price.size - 2)
    d.text((px, y + 68), price, font=f_price, fill=WHITE)
    return cell


def steam_cover(deals, path, acct, swipe_hint=True):
    """Slide pembuka promo Steam. swipe_hint=False untuk Reel (tidak bisa digeser)."""
    from ..media import steam_art
    theme = THEME["game"]
    items = deals.items
    img, _ = base_canvas(theme)
    hero = steam_art(items[0]["appid"], "library_hero.jpg") or steam_art(items[0]["appid"], "header.jpg")
    _photo_area(img, theme, hero, height=640, use_photo=bool(hero))
    draw = ImageDraw.Draw(img, "RGBA")
    header(draw, theme, acct, "PROMO STEAM")
    y = 610
    draw.text((PAD, y), "DISKON", font=font("ExtraBold", 120), fill=WHITE)
    draw.text((PAD, y + 118), "STEAM", font=font("ExtraBold", 120), fill=theme["accent"])
    draw.text((PAD, y + 262), f"{len(items)} game pilihan · harga Indonesia", font=font("SemiBold", 36), fill=MUTED)
    draw.text((PAD, y + 312), tanggal(wib(deals.captured_at).date()), font=font("Medium", 30), fill=DIM)
    cx, cy = PAD, y + 378
    min_price = min((i["final"] for i in items if i["final"]), default=0)
    for label in (f"hingga -{max(i['disc'] for i in items)}%", f"mulai Rp{num(min_price)}",
                  f"rating {min((i['rating'] or 0) for i in items)}%+ positif"):
        cx = chip(draw, cx, cy, label, STEAM_GREEN, STEAM_GREEN_TXT, size=26) + 14
    if swipe_hint:
        hint = "Geser »"
        fh = font("Bold", 24)
        tw = draw.textlength(hint, font=fh)
        draw.rounded_rectangle((W - PAD - tw - 36, H - PAD - 128, W - PAD, H - PAD - 86), radius=21, fill=theme["accent"])
        draw.text((W - PAD - tw - 18, H - PAD - 121), hint, font=fh, fill=(10, 10, 10))
    footer(draw, "Harga dapat berubah · Data: Steam Store", theme, acct)
    img.save(path, "JPEG", quality=92, optimize=True)
    return path


def steam_promo_slides(deals, paths, acct):
    """Cover + slide 2x2. `paths`: daftar path JPEG, panjang = 1 + ceil(jumlah game / 4). Return paths."""
    theme = THEME["game"]
    items = deals.items
    total = len(paths)
    steam_cover(deals, paths[0], acct, swipe_hint=total > 1)

    # ---- slide grid
    gap, cw = 24, (W - 2 * PAD - 24) // 2
    top, bottom = 160, H - PAD - 110
    ch = (bottom - top - gap) // 2
    for si, path in enumerate(paths[1:], start=2):
        group = items[(si - 2) * PER_SLIDE:(si - 1) * PER_SLIDE]
        img, _ = base_canvas(theme)
        draw = ImageDraw.Draw(img, "RGBA")
        header(draw, theme, acct, "PROMO STEAM")
        chip(draw, PAD + draw.textlength("PROMO STEAM", font=font("Bold", 26)) + 70, PAD, f"{si}/{total}",
             (255, 255, 255, 40), WHITE, size=26)
        for k, item in enumerate(group):
            x = PAD + (k % 2) * (cw + gap)
            yy = top + (k // 2) * (ch + gap)
            _rounded_paste(img, _steam_cell(item, cw, ch, theme), (x, yy))
        footer(draw, "Harga dapat berubah · Data: Steam Store", theme, acct)
        img.save(path, "JPEG", quality=92, optimize=True)
    return paths
