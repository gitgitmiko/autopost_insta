"""Kartu carousel sale besar (Steam / Xbox ID / Xbox TR), 1080x1350: cover heboh + slide 2x2 per 4 game."""
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..media import image_abspath, steam_art
from . import settings
from .captions import num, wib
from .cards import PAD, W, H, font

PER_SLIDE = 4
BLACK, WHITE = (12, 12, 14), (255, 255, 255)
PALETTE = {  # bg, ray, accent (stiker/teks kedua), hot (pita/label)
    "BLACK FRIDAY": ((14, 14, 16), (34, 34, 40), (255, 230, 0), (255, 40, 90)),
    "WINTER SALE": ((10, 38, 92), (22, 72, 148), (150, 232, 255), (255, 70, 100)),
    "SUMMER SALE": ((250, 110, 0), (255, 154, 30), (255, 244, 90), (220, 0, 90)),
    "SPRING SALE": ((40, 150, 80), (74, 190, 110), (255, 224, 242), (255, 60, 140)),
    "AUTUMN SALE": ((118, 38, 10), (160, 70, 22), (255, 192, 60), (230, 40, 40)),
    "COUNTDOWN SALE": ((44, 10, 86), (76, 22, 128), (255, 214, 0), (255, 60, 120)),
    "LUNAR NEW YEAR": ((150, 0, 8), (196, 22, 22), (255, 212, 80), (255, 240, 200)),
    "ULTIMATE GAME SALE": ((10, 80, 22), (16, 124, 16), (190, 255, 80), (255, 60, 60)),
    "MEGA SALE": ((10, 80, 22), (16, 124, 16), (190, 255, 80), (255, 60, 60)),
}
STORE_LABEL = {("steam", "ID"): "STEAM", ("xbox", "ID"): "XBOX INDONESIA", ("xbox", "TR"): "XBOX TURKI"}


def anton(size):
    path = os.path.join(settings.FONT_DIR, "Anton-Regular.ttf")
    return ImageFont.truetype(path, size) if os.path.exists(path) else font("ExtraBold", size)


def palette(deals):
    return PALETTE.get(deals.event.name, PALETTE["MEGA SALE"])


def price_text(deals, value):
    if not value:
        return "GRATIS"
    if deals.currency == "TRY":
        return f"{num(value, 2)} TL"
    return "Rp" + num(value)


def idr_hint(deals, value):
    if deals.currency == "IDR" or not deals.idr_rate or not value:
        return None
    return "≈ Rp" + num(round(value * deals.idr_rate, -2))


# ------------------------------------------------------------------------------------------- gambar game
def poster(deals, item, w, h):
    """Sampul portrait game ukuran (w, h)."""
    rel = None
    if deals.store == "steam":
        rel = steam_art(item["id"], "library_600x900.jpg")
        if not rel:
            hd = steam_art(item["id"], "header.jpg")
            if hd:
                img = Image.open(image_abspath(hd)).convert("RGB")
                bg = ImageOps.fit(img, (w, h)).filter(ImageFilter.GaussianBlur(18))
                fitted = img.resize((w, int(img.height * w / img.width)))
                bg.paste(fitted, (0, (h - fitted.height) // 2))
                return bg
    elif item.get("image"):
        from .sales import remote_image
        rel = remote_image(item["image"])
    if rel:
        return ImageOps.fit(Image.open(image_abspath(rel)).convert("RGB"), (w, h), centering=(0.5, 0.4))
    return Image.new("RGB", (w, h), (40, 40, 48))


# ------------------------------------------------------------------------------------------- primitif
def sunburst(size, c1, c2, center, rays=28, spin=0):
    img = Image.new("RGB", size, c1)
    d = ImageDraw.Draw(img)
    cx, cy = center
    r = int(math.hypot(*size)) + 50
    for k in range(rays):
        if k % 2:
            continue
        a0 = math.radians(spin + k * 360 / rays)
        a1 = math.radians(spin + (k + 1) * 360 / rays)
        d.polygon([(cx, cy), (cx + r * math.cos(a0), cy + r * math.sin(a0)), (cx + r * math.cos(a1), cy + r * math.sin(a1))],
                  fill=c2)
    return img


def halftone(img, color, alpha=40, step=26):
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for y in range(0, img.height, step):
        for x in range((y // step % 2) * step // 2, img.width, step):
            r = 2 + 4 * (y / img.height)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(*color, alpha))
    img.paste(over, (0, 0), over)


def burst_polygon(cx, cy, r_out, r_in, spikes, rot=0):
    pts = []
    for k in range(spikes * 2):
        r = r_out if k % 2 == 0 else r_in
        a = math.radians(rot + k * 180 / spikes)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def paste_rotated(base, layer, center, angle):
    rot = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    base.paste(rot, (int(center[0] - rot.width / 2), int(center[1] - rot.height / 2)), rot)


def shadowed(layer, offset=(10, 14), blur=12, opacity=150):
    """Layer RGBA + bayangan lembut di bawahnya (kanvas diperbesar)."""
    pad = blur * 3
    out = Image.new("RGBA", (layer.width + pad * 2 + abs(offset[0]), layer.height + pad * 2 + abs(offset[1])), (0, 0, 0, 0))
    a = layer.split()[-1].point(lambda v: v * opacity // 255)
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 255))
    sh.putalpha(a)
    out.paste(sh, (pad + offset[0], pad + offset[1]), sh)
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.paste(layer, (pad, pad), layer)
    return out


def text_layer(text, fnt, fill, stroke=0, stroke_fill=BLACK, shadow=0, shadow_fill=BLACK):
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = d0.textbbox((0, 0), text, font=fnt, stroke_width=stroke)
    w, h = r - l + shadow + 4, b - t + shadow + 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((-l + shadow, -t + shadow), text, font=fnt, fill=shadow_fill, stroke_width=stroke, stroke_fill=shadow_fill)
    d.text((-l, -t), text, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return img


def fit_anton(text, max_w, start, stroke=0, min_size=40):
    size = start
    while size > min_size:
        f = anton(size)
        if ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=f) + 2 * stroke <= max_w:
            return f
        size -= 4
    return anton(min_size)


def flag(region, w=66, h=44):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if region == "ID":
        d.rectangle((0, 0, w, h // 2), fill=(220, 20, 40))
        d.rectangle((0, h // 2, w, h), fill=WHITE)
    elif region == "TR":
        red = (227, 10, 23)
        d.rectangle((0, 0, w, h), fill=red)
        cx, cy, r = w * 0.38, h / 2, h * 0.3
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE)
        r2 = r * 0.8
        d.ellipse((cx - r2 + r * 0.32, cy - r2, cx + r2 + r * 0.32, cy + r2), fill=red)
        d.polygon(burst_polygon(w * 0.62, cy, h * 0.15, h * 0.06, 5, rot=-90), fill=WHITE)
    d.rectangle((0, 0, w - 1, h - 1), outline=(0, 0, 0, 90), width=2)
    return img


def store_badge(img, deals, x, y, accent):
    d = ImageDraw.Draw(img, "RGBA")
    label = STORE_LABEL.get((deals.store, deals.region), deals.store.upper())
    f = anton(46)
    tw = d.textlength(label, font=f)
    fw = 66 + 16 if deals.store == "xbox" else 0
    d.rounded_rectangle((x, y, x + tw + fw + 44, y + 70), radius=14, fill=BLACK)
    d.rounded_rectangle((x, y, x + tw + fw + 44, y + 70), radius=14, outline=accent, width=4)
    if fw:
        img.paste(flag(deals.region), (x + 22, y + 13), flag(deals.region))
    d.text((x + 22 + fw, y + 5), label, font=f, fill=WHITE)
    return x + tw + fw + 44


def urgency(deals, now):
    ev = deals.event
    left = ev.days_left(now)
    if ev.day_number(now) == 1:
        return "BARU MULAI!"
    if left <= 0:
        return "HARI TERAKHIR!"
    if left == 1:
        return "BERAKHIR BESOK!"
    return f"SISA {left} HARI!"


def tape(img, text, y, color, txt_color, angle=-6):
    layer = Image.new("RGBA", (W + 400, 96), (*color, 255))
    d = ImageDraw.Draw(layer)
    f = anton(58)
    unit = f"  {text}  "
    uw = d.textlength(unit, font=f) + 44
    x = -(uw / 2)
    while x < layer.width:
        d.text((x, 10), unit, font=f, fill=txt_color)
        d.polygon(burst_polygon(x + uw - 22, 48, 20, 8, 5, rot=-90), fill=txt_color)
        x += uw
    d.line((0, 4, layer.width, 4), fill=(0, 0, 0, 120), width=4)
    d.line((0, 91, layer.width, 91), fill=(0, 0, 0, 120), width=4)
    paste_rotated(img, shadowed(layer, (0, 8), 8, 120), (W / 2, y), angle)


def chip(img, x, y, text, bg, fg, size=34):
    d = ImageDraw.Draw(img, "RGBA")
    f = font("ExtraBold", size)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle((x, y, x + tw + 36, y + size + 26), radius=(size + 26) // 2, fill=bg)
    d.text((x + 18, y + 10), text, font=f, fill=fg)
    return x + tw + 36


# ------------------------------------------------------------------------------------------- cover
def sale_cover(deals, path, acct, swipe_hint=True, now=None):
    from datetime import datetime, timezone
    now = now or datetime.now(timezone.utc)
    bg, ray, accent, hot = palette(deals)
    items = deals.items
    rnd = random.Random(deals.key)
    img = sunburst((W, H), bg, ray, (W / 2, 470), rays=32, spin=rnd.uniform(0, 10)).convert("RGBA")
    halftone(img, accent, alpha=28)

    # kipas sampul game di bagian atas
    fan = items[:5]
    pw, ph = 300, 450
    n = len(fan)
    for k, it in enumerate(fan):
        t = (k - (n - 1) / 2) / max(1, (n - 1) / 2)
        p = poster(deals, it, pw, ph).convert("RGBA")
        frame = Image.new("RGBA", (pw + 16, ph + 16), (*WHITE, 255))
        frame.paste(p, (8, 8))
        paste_rotated(img, shadowed(frame, (8, 14), 14, 170), (W / 2 + t * 330, 420 + abs(t) * 46), -t * 13)

    d = ImageDraw.Draw(img, "RGBA")
    # gelapkan bagian bawah agar judul terbaca
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        grad.putpixel((0, y), int(max(0, min(1, (y - 560) / 360)) * 215))
    img.paste(Image.new("RGBA", (W, H), (*bg, 255)), (0, 0), grad.resize((W, H)))

    store_badge(img, deals, PAD - 10, PAD - 14, accent)
    # nama akun kanan atas
    fb = font("ExtraBold", 26)
    bw = d.textlength(acct.brand_name, font=fb)
    d.rounded_rectangle((W - PAD - bw - 36, PAD - 4, W - PAD + 10, PAD + 46), radius=25, fill=(0, 0, 0, 170))
    d.text((W - PAD - bw - 18, PAD + 5), acct.brand_name, font=fb, fill=WHITE)

    # stiker diskon raksasa
    top = max(i["disc"] for i in items)
    sticker = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sticker)
    sd.polygon(burst_polygon(200, 200, 196, 160, 22), fill=BLACK)
    sd.polygon(burst_polygon(200, 200, 184, 150, 22), fill=accent)
    f_small = anton(44)
    sd.text((200, 120), "HINGGA", font=f_small, fill=BLACK, anchor="mm")
    sd.text((200, 218), f"-{top}%", font=fit_anton(f"-{top}%", 300, 140), fill=BLACK, anchor="mm")
    paste_rotated(img, shadowed(sticker, (10, 14), 12, 160), (W - 205, 690), 12)

    # judul event miring
    words = deals.event.name.split()
    line1 = " ".join(words[:-1]) if len(words) > 1 else words[0]
    line2 = words[-1] if len(words) > 1 else "SALE"
    title = Image.new("RGBA", (W, 460), (0, 0, 0, 0))
    l1 = text_layer(line1, fit_anton(line1, 700, 170, 8), WHITE, stroke=8, shadow=12, shadow_fill=hot)
    l2 = text_layer(line2, fit_anton(line2, 700, 180, 8), accent, stroke=8, shadow=12)
    title.paste(l1, (0, 0), l1)
    title.paste(l2, (0, l1.height - 18), l2)
    title = title.crop(title.getbbox())
    rot = title.rotate(4, resample=Image.BICUBIC, expand=True)
    img.paste(rot, (PAD - 6, 1000 - rot.height), rot)

    # pita urgensi
    tape(img, urgency(deals, now), 1058, hot, WHITE if sum(hot) < 600 else BLACK)

    # info bawah
    d = ImageDraw.Draw(img, "RGBA")
    finals = [i["final"] for i in items if i["final"]]
    x, y = PAD, 1118
    x = chip(img, x, y, f"{len(items)} GAME", accent, BLACK) + 14
    if finals:
        mp = min(finals)
        hint = idr_hint(deals, mp)
        chip(img, x, y, f"MULAI {price_text(deals, mp)}" + (f" ({hint})" if hint else ""), WHITE, BLACK,
             size=34 if not hint else 28)
    end = wib(deals.event.end.replace(tzinfo=None)) if deals.event.end.tzinfo is None else deals.event.end.astimezone(settings.TZ)
    bulan = ("Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des").split()
    note = f"Berakhir {end.day} {bulan[end.month - 1]} {end:%H:%M} WIB"
    d.text((PAD, 1200), note, font=font("SemiBold", 28), fill=(235, 235, 240))
    d.text((PAD, H - PAD - 30), acct.brand_handle, font=font("Bold", 26), fill=accent)
    if swipe_hint:
        f = anton(54)
        txt = "GESER"
        tw = d.textlength(txt, font=f)
        bx = W - PAD - tw - 130
        d.rounded_rectangle((bx, H - PAD - 96, W - PAD + 10, H - PAD - 8), radius=44, fill=accent)
        d.text((bx + 30, H - PAD - 92), txt, font=f, fill=BLACK)
        ax = bx + 42 + tw
        for k in range(2):
            x0 = ax + k * 26
            d.polygon([(x0, H - PAD - 74), (x0 + 22, H - PAD - 52), (x0, H - PAD - 30)], fill=BLACK)
    img.convert("RGB").save(path, "JPEG", quality=92, optimize=True)
    return path


# ------------------------------------------------------------------------------------------- grid
def _cell(deals, item, w, h, accent, hot):
    info_h = 150
    cell = Image.new("RGBA", (w, h), (18, 18, 22, 255))
    cell.paste(poster(deals, item, w, h - info_h), (0, 0))
    d = ImageDraw.Draw(cell, "RGBA")
    y = h - info_h
    d.rectangle((0, y, w, h), fill=(16, 16, 20, 255))
    d.rectangle((0, y, w, y + 6), fill=accent)
    title = item["title"]
    f = font("Bold", 26)
    while d.textlength(title, font=f) > w - 28 and len(title) > 4:
        title = title[:-2].rstrip() + "…"
    d.text((14, y + 16), title, font=f, fill=WHITE)
    if item.get("orig") and item["orig"] != item["final"]:
        old = price_text(deals, item["orig"])
        fo = font("Medium", 22)
        d.text((14, y + 54), old, font=fo, fill=(150, 150, 160))
        d.line((14, y + 67, 14 + d.textlength(old, font=fo), y + 67), fill=hot, width=3)
    price = price_text(deals, item["final"])
    fp = anton(46)
    while d.textlength(price, font=fp) > w - 28 and fp.size > 28:
        fp = anton(fp.size - 4)
    d.text((14, y + 78), price, font=fp, fill=accent)
    hint = idr_hint(deals, item["final"])
    if hint:
        fh = font("SemiBold", 20)
        d.text((w - 14 - d.textlength(hint, font=fh), y + 58), hint, font=fh, fill=WHITE)
    # stiker diskon di pojok kanan atas sampul
    s = Image.new("RGBA", (170, 170), (0, 0, 0, 0))
    sd = ImageDraw.Draw(s)
    sd.polygon(burst_polygon(85, 85, 82, 66, 16), fill=BLACK)
    sd.polygon(burst_polygon(85, 85, 76, 61, 16), fill=hot)
    sd.text((85, 86), f"-{item['disc']}%", font=anton(44), fill=WHITE, anchor="mm")
    paste_rotated(cell, s, (w - 70, 72), -12)
    if item.get("rating") and deals.store == "steam":
        txt = f"{item['rating']}% positif"
    elif item.get("rating") and item.get("reviews", 0) >= 20:
        txt = f"   {item['rating']:.1f}"
    else:
        txt = None
    if txt:
        fr = font("Bold", 20)
        tw = d.textlength(txt, font=fr)
        d.rounded_rectangle((12, 12, 12 + tw + 24, 48), radius=18, fill=(0, 0, 0, 180))
        d.text((24, 17), txt, font=fr, fill=WHITE)
        if txt.startswith("   "):
            d.polygon(burst_polygon(34, 30, 11, 4.5, 5, rot=-90), fill=(255, 210, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=22, fill=255)
    cell.putalpha(mask)
    return cell


def sale_slides(deals, paths, acct, now=None):
    """Cover + slide 2x2. paths: 1 + ceil(jumlah game / 4) path JPEG."""
    bg, ray, accent, hot = palette(deals)
    total = len(paths)
    sale_cover(deals, paths[0], acct, swipe_hint=total > 1, now=now)
    gap, cw = 24, (W - 2 * PAD - 24) // 2
    top, bottom = 170, H - PAD - 90
    ch = (bottom - top - gap) // 2
    label = f"{deals.event.name} · {STORE_LABEL.get((deals.store, deals.region), deals.store.upper())}"
    for si, path in enumerate(paths[1:], start=2):
        group = deals.items[(si - 2) * PER_SLIDE:(si - 1) * PER_SLIDE]
        img = sunburst((W, H), bg, ray, (W / 2, -200), rays=36).convert("RGBA")
        img.paste(Image.new("RGBA", (W, H), (0, 0, 0, 120)), (0, 0), Image.new("L", (W, H), 120))
        d = ImageDraw.Draw(img, "RGBA")
        f = anton(48)
        tw = d.textlength(label, font=f)
        if tw > W - 2 * PAD - 120:
            f = fit_anton(label, W - 2 * PAD - 120, 48)
            tw = d.textlength(label, font=f)
        d.rounded_rectangle((PAD - 10, PAD - 12, PAD + tw + 24, PAD + 66), radius=14, fill=accent)
        d.text((PAD + 7, PAD - 6), label, font=f, fill=BLACK)
        pg = f"{si}/{total}"
        fpg = font("ExtraBold", 28)
        pw = d.textlength(pg, font=fpg)
        d.rounded_rectangle((W - PAD - pw - 30, PAD, W - PAD + 6, PAD + 50), radius=25, fill=(0, 0, 0, 170))
        d.text((W - PAD - pw - 12, PAD + 8), pg, font=fpg, fill=WHITE)
        for k, it in enumerate(group):
            x = PAD + (k % 2) * (cw + gap)
            yy = top + (k // 2) * (ch + gap)
            c = shadowed(_cell(deals, it, cw, ch, accent, hot), (6, 10), 10, 150)
            img.paste(c, (x - 30, yy - 30), c)
        foot = "Harga dapat berubah · Data: " + ("Steam Store" if deals.store == "steam" else
                                                 f"Xbox Store {deals.region}")
        if deals.currency == "TRY" and deals.idr_rate:
            foot += f" · 1 TL ≈ Rp{num(deals.idr_rate)}"
        d.text((PAD, H - PAD - 34), foot, font=font("Medium", 24), fill=(225, 225, 232))
        hw = d.textlength(acct.brand_handle, font=font("Bold", 24))
        d.text((W - PAD - hw, H - PAD - 34), acct.brand_handle, font=font("Bold", 24), fill=accent)
        img.convert("RGB").save(path, "JPEG", quality=92, optimize=True)
    return paths
