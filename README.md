# scraper-data-gitgit

Mengumpulkan data **game, politik, crypto, dan saham Indonesia** lalu menyimpannya ke MySQL.

## Sumber data

| Kategori | Website | Metode | Data |
|---|---|---|---|
| Politik | CNN Indonesia (Nasional), Antara (Politik), Republika (Politik), Detik News, CNBC Indonesia (News), Okezone | RSS + scraping isi artikel | Berita |
| Saham | CNBC Indonesia (Market), Antara (Bursa), Detik Finance (Bursa & Valas), IDX Channel, CNN Indonesia (Ekonomi), Tempo (Bisnis) | RSS + scraping isi artikel | Berita |
| Saham | Yahoo Finance (`*.JK`, `^JKSE`, `^JKLQ45`) | API JSON | OHLCV harian 55 saham besar BEI + IHSG & LQ45 |
| Crypto | Blockchain Media Indonesia, CoinDesk, Cointelegraph, Decrypt, The Block | RSS + scraping isi artikel | Berita |
| Crypto | CoinGecko | API JSON | Harga IDR, market cap, volume, perubahan 24 jam (top 250) |
| Crypto | Indodax | API JSON | Harga semua pair IDR di exchange Indonesia |
| Game | Gamebrott, JagatPlay, RevivalTV, Detik Inet Games, Antara Tekno & Game, IGN, GameSpot, Polygon, PC Gamer, Eurogamer | RSS + scraping isi artikel | Berita |
| Saham | CNBC Indonesia Research, Bloomberg Technoz, Antara Finansial, Investing.com Indonesia | RSS | Berita pasar |
| Saham & Crypto | **Google News** (pencarian per kode saham / koin, 7 hari terakhir) | RSS | Berita yang khusus membahas tiap aset |
| Crypto | NewsBTC | RSS | Berita |
| Crypto | **Alternative.me Crypto Fear & Greed Index** | API JSON | Indeks sentimen pasar crypto harian (0–100) sejak 2018 |
| Crypto | CoinGecko `market_chart` | API JSON | Harga harian 15 koin utama (90 hari) untuk dibandingkan dengan sentimen |
| Game · VALORANT | **playvalorant.com/id-id/news** (resmi, Bahasa Indonesia), Dexerto VALORANT, VLR.gg, PCGamesN VALORANT | Web JSON + RSS | Berita, patch, agen, VCT |
| Game · Dota 2 | **Steam News Dota 2** (pengumuman resmi Valve), Gamebrott tag Dota 2, PCGamesN Dota 2 | API JSON + RSS | Patch, event, The International |
| Game | Dexerto Esports | RSS | Berita esports (ditandai VALORANT/Dota 2 bila relevan) |
| Game | FreeToGame | API JSON | Katalog ±400 game (genre, platform, publisher, rilis) |
| Game | Steam Store (region ID) | API JSON | Specials, Top Sellers, New Releases, Coming Soon + harga IDR |

Dicoba tapi tidak dipakai (memblokir bot / tidak ada feed): Kompas, Bisnis.com, Kontan, Liputan6, Suara, Kotaku, situs IDX (`idx.co.id`, diproteksi Cloudflare).
Semua sumber dapat diubah di `scraper/config.py`.

## Struktur database (`scraper_data`)

| Tabel | Isi |
|---|---|
| `sources` | Daftar sumber (nama, url, kategori, rss/api, bahasa) |
| `articles` | Berita semua kategori: judul, url (unik), ringkasan, isi lengkap, penulis, tag, gambar, waktu terbit (UTC) |
| `crypto_coins` | Master koin (id CoinGecko, simbol, nama) |
| `crypto_prices` | Snapshot harga per run (sumber `coingecko` / `indodax`) |
| `stocks` | Master saham/indeks BEI |
| `stock_prices` | Harga harian (unik per `ticker` + `trade_date`, otomatis diperbarui) |
| `games` | Katalog game (FreeToGame & Steam) |
| `game_store_snapshots` | Posisi & harga game di daftar Steam per run |
| `article_assets` | Tautan artikel ↔ aset (`BBCA`, `^JKSE`, `bitcoin`, …); `matched_by` = `query` (hasil pencarian Google News) atau `text` (kode/nama disebut di teks) |
| `article_sentiments` | Sentimen per artikel: `score` −1..+1, `label` positif/negatif/netral, kata kunci pemicu, `news_date` (WIB) |
| `market_sentiment_index` | Crypto Fear & Greed Index harian |
| `crypto_daily_prices` | Harga harian koin yang dilacak (tanggal UTC) |
| `scrape_runs` | Log setiap job: waktu, status, jumlah item, pesan error |

**View siap pakai**

| View | Isi |
|---|---|
| `v_asset_daily_sentiment` | Per aset per hari: jumlah artikel, rata-rata sentimen, jumlah positif/negatif, harga, % perubahan harga, dan `sentiment_vs_price` (searah/berlawanan) |
| `v_asset_news_sentiment` | Daftar berita per aset beserta label, skor, kata kunci, penerbit, dan URL |

## Analisis sentimen

`scraper/sentiment.py` memakai kamus istilah pasar bahasa Indonesia & Inggris
(naik/menguat/melonjak/ARA/net buy/buyback/rebound vs. turun/anjlok/koreksi/ARB/net sell/likuidasi/peretasan, dll.),
dengan bobot untuk istilah kuat, deteksi negasi ("tidak naik", "belum pulih"), prioritas frasa
("suku bunga naik" dihitung negatif, bukan "naik"), dan judul berbobot 2×.
Skor diredam bila buktinya sedikit; label positif bila skor ≥ 0,2, negatif bila ≤ −0,2.

Keterbatasan: sentimen dihitung per artikel, jadi artikel yang menyebut beberapa aset memberi skor yang sama
untuk semuanya. Kamus juga bisa salah membaca sarkasme atau konteks rumit. Setelah mengubah kamus, jalankan
`--sentiment-only --reanalyze`.

## Cara pakai

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# .env berisi DATABASE_URL=mysql+pymysql://user:pass@localhost/scraper_data?charset=utf8mb4
# (tanpa .env otomatis memakai SQLite di data/scraper.db)

.venv/bin/python -m scraper                          # semua kategori
.venv/bin/python -m scraper -c crypto saham          # kategori tertentu
.venv/bin/python -m scraper --full-text              # + ambil isi lengkap artikel (maks 50/kategori/run)
.venv/bin/python -m scraper --no-news -c saham       # harga saham + berita per aset + sentimen (tanpa RSS umum)
.venv/bin/python -m scraper --no-sentiment           # tanpa Google News / Fear & Greed / analisis sentimen
.venv/bin/python -m scraper --sentiment-only --reanalyze   # hitung ulang sentimen semua artikel (tanpa scraping)
```

Menjalankan ulang aman: artikel didedup lewat hash URL, harga saham di-upsert per hari,
sedangkan harga crypto & daftar Steam disimpan sebagai snapshot berwaktu (riwayat).

Contoh jadwal cron (tiap jam):

```
0 * * * * cd /home/gitgitmiko/github-repos/scraper-data-gitgit && .venv/bin/python -m scraper --full-text >> data/cron.log 2>&1
```

## Contoh query

```sql
-- Berita politik terbaru
SELECT a.published_at, s.name, a.title FROM articles a JOIN sources s ON s.id = a.source_id
WHERE a.category = 'politik' ORDER BY a.published_at DESC LIMIT 20;

-- Harga crypto terbaru dari CoinGecko
SELECT c.symbol, c.name, p.price_idr, p.change_24h_pct FROM crypto_prices p JOIN crypto_coins c ON c.id = p.coin_id
WHERE p.source = 'coingecko' AND p.captured_at = (SELECT MAX(captured_at) FROM crypto_prices WHERE source = 'coingecko')
ORDER BY p.market_cap_rank LIMIT 20;

-- Penutupan saham terakhir
SELECT s.ticker, s.name, p.trade_date, p.close, p.volume FROM stock_prices p JOIN stocks s USING (ticker)
WHERE p.trade_date = (SELECT MAX(trade_date) FROM stock_prices) ORDER BY p.volume DESC;

-- Sentimen harian IHSG vs perubahan harga
SELECT day, n_articles, avg_sentiment, n_positif, n_negatif, price_change_pct, sentiment_vs_price
FROM v_asset_daily_sentiment WHERE asset_code = '^JKSE' ORDER BY day DESC LIMIT 14;

-- Berita paling negatif tentang Bitcoin minggu ini
SELECT published_at, score, title, publisher, keywords FROM v_asset_news_sentiment
WHERE asset_code = 'bitcoin' AND news_date >= CURDATE() - INTERVAL 7 DAY ORDER BY score, published_at DESC LIMIT 10;

-- Saham dengan sentimen terburuk 3 hari terakhir (min. 5 berita)
SELECT asset_code, SUM(n_articles) n, ROUND(AVG(avg_sentiment), 3) sentimen FROM v_asset_daily_sentiment
WHERE asset_type = 'saham' AND day >= CURDATE() - INTERVAL 3 DAY GROUP BY asset_code HAVING n >= 5 ORDER BY sentimen LIMIT 10;

-- Fear & Greed crypto vs harga Bitcoin
SELECT f.index_date, f.value, f.classification, p.price_idr FROM market_sentiment_index f
JOIN crypto_daily_prices p ON p.coin_id = 'bitcoin' AND p.price_date = f.index_date
WHERE f.name = 'crypto_fear_greed' ORDER BY f.index_date DESC LIMIT 30;
```

## Gambar berita

Gambar utama tiap berita diunduh ke `data/images/YYYY/MM/DD/<hash>.<ext>` dan dicatat di tabel
`article_images` (URL asli, lokasi file, sha256, dimensi, ukuran, status). Berita yang RSS-nya tidak menyertakan
gambar dilengkapi dari `og:image` halamannya. Tidak bisa: Google News (link redirect), Tempo & gambar
Investing.com (memblokir bot).

### Gambar & video di dalam isi artikel (saat scraping)

Untuk kategori yang punya akun posting aktif (sekarang: game), setiap run per jam membuka artikel yang terbit
≤ 48 jam (maks. 60 artikel/run) lalu menyimpan isi lengkap, **gambar** (`article_images.kind = 'body'`) dan
**file video** yang di-host situs berita (`kind = 'video'`, maks. 100 MB, `MAX_VIDEO_MB`). Penanda:
`articles.details_fetched_at`.

- **Retensi video 7 hari** (`VIDEO_KEEP_DAYS`): file dihapus 7 hari setelah artikelnya diposting, atau 7 hari setelah
  diunduh bila tidak pernah diposting. Barisnya tetap ada (`status = 'expired'`, URL asli, sha256, ukuran).
  Slide video (mp4) di folder media publik juga dihapus setelah 7 hari.
- **YouTube**: hanya metadata di tabel `article_youtube` (ID, judul, channel, thumbnail, link) lewat oEmbed resmi;
  video tidak diunduh/diunggah ulang (ketentuan YouTube & risiko klaim hak cipta di Instagram).

## Posting otomatis Instagram (via n8n) — satu akun per kategori

```
cron tiap jam (:05) ── scripts/run_scrape.sh ──► MySQL (berita, gambar, harga, sentimen)

n8n (stack ~/github-repos/n8n), satu workflow per akun: "sdg-social-<akun>"
  Jadwal ─► POST /prepare ke API Python ─► kartu JPEG ditulis ke n8n/media/public/social/<akun>/…
         ─► Instagram: buat container (image_url = https://media.gitgitmiko.my.id/media/social/…)
            ─► tunggu FINISHED ─► publish ─► permalink ─► POST /report (tabel social_posts)
         ─► Facebook Page (opsional per akun) ─► POST /report
```

- **API Python** `scraper.social.api` berjalan sebagai service systemd `scraper-social-api`, hanya mendengarkan di
  `172.18.0.1:8791` (gateway jaringan Docker n8n) dan wajib header `X-API-Key` (`SOCIAL_API_KEY` di `.env`).
- **Gambar publik** disajikan nginx `media` milik stack n8n lewat Cloudflare Tunnel `media.gitgitmiko.my.id`;
  file lebih dari 14 hari dihapus otomatis.
- **Token Meta** hanya disimpan sebagai credential n8n terenkripsi (`Meta Page Token - <akun>`), tidak di file.

### Akun & jadwal — `social_accounts.json`

Satu entri = satu akun Instagram. Kolom: `key`, `category` (game/politik/saham/crypto), `brand_name`,
`brand_handle`, `ig_user_id`/`page_id` (diisi otomatis oleh `setup-token`), `facebook` (ikut posting ke Page),
`use_article_photo`, `languages` (urutan prioritas bahasa berita), `hashtags`, `schedule`.

Jenis konten (`kind`): `news` (semua kategori), `steam_deals` (game), `recap_saham`, `recap_crypto`.

Akun **game** @gitgit_infogame (Instagram + Facebook Page "Gitgit Info Game"), jadwal WIB:
berita 08:00, 11:00, 14:00, 17:00, 21:00 · **VALORANT** 09:30 & 18:00 (berita ≤ 48 jam) ·
**Dota 2** 15:30 (berita ≤ 7 hari) · Promo Steam 19:00 (dilewati bila daftar promonya sama dengan sebelumnya).

**Topik game khusus** (`GAME_TOPICS` di `scraper/config.py`): artikel game ditandai `valorant`/`dota2` di
`article_assets` (`asset_type = 'game'`) — otomatis untuk sumber khusus, atau lewat kata kunci (Valorant, VCT,
Dota 2, The International) untuk semua berita game. Slot jadwal topik: `{"time": "09:30", "kind": "news",
"topic": "valorant", "max_age_hours": 48}`; kartu memakai label & warna topik dan hashtag khusus. Slot dilewati
bila tidak ada berita topik itu yang belum diposting.

Aturan pemilihan berita: maks. 18 jam terakhir, belum pernah diposting akun itu, tidak mirip postingan 3 hari
terakhir, bahasa sesuai prioritas (Indonesia dulu), variasi media, ramai diberitakan; untuk game panduan/
artikel promo/kode redeem disaring, dan feed campuran (Antara Tekno) hanya diambil yang bertopik game.

### Isi postingan berita

- **Caption** memuat isi artikel selengkap mungkin (paragraf, poin list, subjudul) — diambil ulang dari halaman
  artikel saat akan diposting. Instagram maks. 2.200 karakter: bila `comment_overflow: true`, sisanya diposting
  sebagai maks. 2 **komentar lanjutan** (butuh izin `instagram_manage_comments`); bila `false`, caption dipotong rapi.
  Facebook memuat isi lengkap langsung di postingan.
- **Carousel**: bila `use_article_photo: true`, gambar **dan video** di dalam isi artikel (bukan logo/ikon/thumbnail,
  gambar lebar ≥ 500 px, bukan duplikat gambar utama) menjadi slide 2…N sesuai urutan di artikel
  (maks. `max_extra_slides`, default 3), ditampilkan utuh dengan judul & kredit sumber.
  Dicatat di `article_images` (`kind = 'body'` gambar / `'video'` video, urut `position`).
  - **Video**: hanya file yang di-host situs berita (mp4/webm/mov, maks. 200 MB). Diolah ffmpeg menjadi slide
    1080×1350 H.264/AAC ≤ 60 detik; n8n menunggu Instagram selesai memproses video sebelum membuat carousel.
    Video **YouTube tidak diunduh** (ketentuan YouTube & hak cipta) — tautannya dicantumkan di caption (🎬 Video).
  - **Facebook**: album multi-foto (hanya gambar; API album Facebook tidak mendukung video).
  - **Filter non-isi**: gambar dibuang bila berada di kotak "baca juga/lihat juga"/terkait/rekomendasi/iklan/widget/
    embed (kecuali wadah yang memuat ≥ 3 paragraf panjang = isi artikel), dibungkus link ke artikel lain di situs
    yang sama atau ke toko/afiliasi, muncul setelah paragraf terakhir, sama dengan gambar sampul (dibandingkan per
    path, tanpa host & akhiran ukuran), nama URL mencurigakan (iklan/popup/placeholder/default.jpg), atau gambar
    polos (keragaman < 12 / < 150 warna). `media.recheck_body_media()` menerapkan ulang filter ke data lama
    (status `rejected`).
  - **Narasi berlanjut di slide 2+**: sisa ringkasan slide 1 lalu paragraf berikutnya ditulis di bawah gambar/video,
    dipotong di batas kalimat dan diteruskan ke slide berikutnya.
- Posting ulang artikel tertentu: `POST /prepare {"account": "game", "article_id": 123}` (lewat API lokal).

### Promo Steam (carousel)

Setiap jam (`steam_promo`) dan sesaat sebelum posting, 300 game diskon teratas Steam region Indonesia (urut ulasan)
disaring: diskon ≥ 60%, ulasan positif ≥ 80%, ≥ 1.000 ulasan, bukan DLC/soundtrack/bundle, satu game per waralaba,
dan game yang tampil 3 hari terakhir dikesampingkan. 16 teratas (peringkat = jumlah ulasan × diskon) disimpan sebagai
`game_store_snapshots.list_type = 'promo_picks'` (dengan `rating_pct`, `reviews`).
Postingan: cover "DISKON STEAM" + 4 slide berisi 4 game (sampul resmi Steam, badge diskon, harga lama/baru,
rating). Gambar Steam di-cache di `data/images/steam/`. Halaman bio menampilkan daftar game + link ke tiap halaman Steam.

### Halaman "link di bio"

Link di caption Instagram tidak bisa diklik, jadi tiap akun dengan `bio_slug` punya halaman statis
`https://media.gitgitmiko.my.id/l/<bio_slug>/` (akun game: `/l/infogame/`) berisi postingan terbaru + tombol
Baca artikel / Tonton video (YouTube dari `article_youtube`) / Lihat di Instagram. Dibuat ulang otomatis setiap
postingan Instagram terbit (`python -m scraper.social bio --account game` untuk manual). Caption Instagram akun ini
menulis "link ada di bio"; caption Facebook tetap memuat link langsung.

### Menyalakan akun baru (mis. game)

1. Akun Instagram → **profesional** (Bisnis/Kreator) dan hubungkan ke sebuah **Facebook Page**.
2. <https://developers.facebook.com/apps> → *Create App* (Business) dengan izin `pages_show_list`,
   `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`,
   `business_management`. Untuk akun milik sendiri, mode Development cukup.
3. Graph API Explorer → pilih app → *Generate Access Token* (izin di atas) → jalankan:
   ```bash
   .venv/bin/python -m scraper.social setup-token --account game \
       --app-id APP_ID --app-secret APP_SECRET --user-token TOKEN_DARI_EXPLORER
   ```
   Perintah ini menukar token menjadi Page token permanen, mengisi `ig_user_id`/`page_id`, menyimpan token ke
   n8n, memasang ulang workflow, **mengaktifkannya**, dan me-restart n8n. (Butuh password sudo untuk docker.)

Menambah akun kategori lain: tambahkan entri di `social_accounts.json`, lalu
`.venv/bin/python -m scraper.social n8n-sync --account <key>` dan `setup-token --account <key> …`.
Setelah mengubah jadwal: `n8n-sync` lagi (workflow dibuat ulang dari file).

### Perintah

```bash
.venv/bin/python -m scraper.social preview --account game            # contoh gambar+caption → data/outbox/preview/
.venv/bin/python -m scraper.social preview --account game --kind steam_deals
.venv/bin/python -m scraper.social status --account game             # status jadwal hari ini
.venv/bin/python -m scraper.social n8n-sync [--account game]         # pasang/perbarui workflow & credential
sudo systemctl status scraper-social-api                             # API untuk n8n
```

Editor n8n hanya di `http://127.0.0.1:5678` (tidak dibuka ke internet). Dari komputer lain:
`ssh -L 5678:127.0.0.1:5678 gitgitmiko@<server>` lalu buka `http://localhost:5678`. Di sana terlihat riwayat
eksekusi tiap posting; tombol *Test workflow* (pemicu "Tes manual") memposting satu berita sekarang juga.

Log: `data/logs/scrape-YYYY-MM-DD.log`, `journalctl -u scraper-social-api`, riwayat eksekusi di n8n.
