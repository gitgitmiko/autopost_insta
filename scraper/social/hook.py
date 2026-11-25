"""Hook kartu & baris pertama caption, ditulis LLM (via 9router, model gratis) dari judul + ringkasan berita.

Judul media jarang ditulis untuk feed Instagram: panjang, kadang berbahasa Inggris, tanpa sudut pandang pembaca.
Akun pesaing yang berhasil memakai hook pendek dengan nama/angka di depan (lihat `viral`). Modul ini meminta LLM
menulis hook seperti itu, lalu MEMERIKSA hasilnya dengan kode sebelum dipakai:

- tiap angka di hook harus ada di sumber;
- tiap kata berhuruf kapital (nama, kode saham, singkatan) selain kata pertama harus ada di sumber;
- panjang <= 12 kata / 90 karakter, satu baris;
- tanpa kata clickbait, dan untuk saham/crypto tanpa ajakan membeli.

Gagal diperiksa, semua model error/lambat, atau LLM tidak dikonfigurasi → None, pemanggil memakai judul asli.
Posting tidak pernah gagal gara-gara hook.
"""
import logging
import os
import re
import time

import requests

from . import settings  # noqa: F401  (memuat .env sebelum variabel LLM_* dibaca)

log = logging.getLogger(__name__)

BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:20128/v1").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODELS = [m.strip() for m in os.getenv(
    "LLM_HOOK_MODELS", "gemini/gemini-3.5-flash-lite,model-free,gemini/gemini-3.1-flash-lite-preview").split(",")
    if m.strip()]
TIMEOUT = float(os.getenv("LLM_HOOK_TIMEOUT", "12"))  # per model
TOTAL_BUDGET = float(os.getenv("LLM_HOOK_BUDGET", "25"))  # semua model, detik
MAX_WORDS, MAX_CHARS = 12, 90

STYLE = {
    "game": "Gaya santai ala media game Indonesia (boleh 'kamu').",
    "politik": "Gaya netral dan sopan, tidak memihak, tanpa opini.",
    "saham": "Gaya media pasar modal: lugas. JANGAN mengajak membeli/menjual atau menilai layak tidaknya investasi.",
    "crypto": "Gaya media kripto: lugas. JANGAN mengajak membeli/menjual atau menilai layak tidaknya investasi.",
}
SYSTEM = """Kamu editor media sosial akun berita Indonesia. Ubah judul + ringkasan berita menjadi HOOK untuk kartu Instagram.
Aturan:
- Bahasa Indonesia yang wajar; terjemahkan bila sumber berbahasa Inggris. Maks. 12 kata.
- Huruf kapital hanya di awal kalimat dan untuk nama/singkatan (bukan Title Case).
- Konkret: nama atau angka terpenting di awal. Boleh diakhiri pertanyaan singkat yang memancing komentar.
- HANYA fakta, angka, dan nama yang tertulis di sumber. Jangan menambah, membesar-besarkan, atau mengubah makna.
- Tanpa emoji, tanpa tanda kutip, tanpa hashtag.
Contoh gaya: "Yield SBN tembus 7,5%, tekanan atau peluang?" / "NPC GTA VI mendadak viral gara-gara pipa"
Jawab HANYA hook-nya, satu baris."""

BANNED = re.compile(r"(?i)\b(pasti|dijamin|wajib|heboh|gempar|viral abis|cuan|klik|link di bio)\b")
BANNED_MARKET = re.compile(r"(?i)\b(beli|borong|serok|koleksi|layak|untung besar|jangan sampai ketinggalan|"
                           r"to the moon|fomo|saatnya)\b")
# kata pembuka kalimat yang boleh berhuruf kapital meski tidak ada di sumber (selain ini: harus ada di sumber)
STARTERS = {"resmi", "ternyata", "akhirnya", "kabar", "siap", "mulai", "kenapa", "mengapa", "apa", "bagaimana",
            "begini", "ini", "inilah", "ada", "hari", "baru", "bocoran", "segera", "jadi", "makin", "kini", "sudah",
            "belum", "tak", "tidak", "bukan", "giliran", "usai", "setelah", "jelang", "demi", "gara-gara", "harga",
            "sempat", "masih", "bakal", "akan"}
NUM_WORDS = {"satu": "1", "dua": "2", "tiga": "3", "empat": "4", "lima": "5", "enam": "6", "tujuh": "7",
             "delapan": "8", "sembilan": "9", "sepuluh": "10", "sebelas": "11", "seratus": "100", "seribu": "1000",
             "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
             "nine": "9", "ten": "10"}
SCALE_WORDS = ("puluh", "belas", "ratus", "ribu", "juta", "miliar", "triliun")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
CAP_RE = re.compile(r"\b[A-Z][\w\-]*")


def enabled():
    return bool(API_KEY and MODELS)


def _norm_num(s):
    return re.sub(r"[.,]", "", s)


def check(hook, source, category):
    """Return alasan penolakan, atau None bila hook lolos."""
    if not hook:
        return "kosong"
    if "\n" in hook or len(hook) > MAX_CHARS or len(hook.split()) > MAX_WORDS:
        return "terlalu panjang"
    if BANNED.search(hook) or (category in ("saham", "crypto") and BANNED_MARKET.search(hook)):
        return "kata terlarang"
    src_nums = {_norm_num(n) for n in NUM_RE.findall(source)}
    for n in NUM_RE.findall(hook):
        if _norm_num(n) not in src_nums:
            return f"angka '{n}' tidak ada di sumber"
    low = source.lower()
    src_words = set(re.findall(r"[a-z]+", low))
    for w in re.findall(r"[a-z]+", hook.lower()):  # angka yang ditulis dengan kata
        if w in NUM_WORDS and w not in src_words and NUM_WORDS[w] not in src_nums:
            return f"angka '{w}' tidak ada di sumber"
        if any(w.endswith(sc) for sc in SCALE_WORDS) and w not in src_words:
            return f"angka '{w}' tidak ada di sumber"
    words = CAP_RE.findall(hook)
    for i, w in enumerate(words):
        first = i == 0 and hook.startswith(w)
        if w.lower() not in low and not (first and w.lower() in STARTERS):
            return f"nama '{w}' tidak ada di sumber"
    return None


def _clean(text):
    lines = [ln.strip() for ln in (text or "").strip().splitlines() if ln.strip()]
    hook = lines[-1] if lines else ""
    hook = re.sub(r"^(hook\s*:\s*)", "", hook, flags=re.I).strip().strip('"“”\'').strip()
    return re.sub(r"\s+", " ", hook)


def make(title, summary, category):
    """Hook untuk satu berita → (hook, model) atau (None, alasan)."""
    if not enabled():
        return None, "LLM tidak dikonfigurasi"
    source = f"{title}. {summary or ''}"[:1500]
    messages = [{"role": "system", "content": f"{SYSTEM}\n{STYLE.get(category, '')}"},
                {"role": "user", "content": f"Akun: {category}\nSumber: {source}"}]
    start, reasons = time.time(), []
    for model in MODELS:
        left = TOTAL_BUDGET - (time.time() - start)
        if left < 2:
            reasons.append("waktu habis")
            break
        try:
            r = requests.post(f"{BASE_URL}/chat/completions", timeout=min(TIMEOUT, left),
                              headers={"Authorization": f"Bearer {API_KEY}"},
                              json={"model": model, "messages": messages, "max_tokens": 600, "stream": False})
            r.raise_for_status()
            hook = _clean(r.json()["choices"][0]["message"].get("content"))
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            reasons.append(f"{model}: {str(e)[:80]}")
            continue
        why = check(hook, source, category)
        if why is None:
            return hook, model
        reasons.append(f"{model}: ditolak ({why}): {hook[:80]}")
    log.info("hook AI tidak dipakai: %s", " | ".join(reasons))
    return None, "; ".join(reasons)
