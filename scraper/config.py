"""Daftar sumber data per kategori."""

CATEGORIES = ("game", "politik", "crypto", "saham")

# Sumber berita (RSS). Setiap entri: nama, url feed, kategori, bahasa.
NEWS_FEEDS = [
    # --- Politik ---
    {"name": "CNN Indonesia - Nasional", "url": "https://www.cnnindonesia.com/nasional/rss", "category": "politik", "lang": "id", "topic": "politik"},
    {"name": "Antara - Politik", "url": "https://www.antaranews.com/rss/politik.xml", "category": "politik", "lang": "id"},
    {"name": "Republika - Politik", "url": "https://www.republika.co.id/rss/news/politik", "category": "politik", "lang": "id"},
    {"name": "Detik News - Berita", "url": "https://news.detik.com/berita/rss", "category": "politik", "lang": "id", "topic": "politik"},
    {"name": "CNBC Indonesia - News", "url": "https://www.cnbcindonesia.com/news/rss", "category": "politik", "lang": "id", "topic": "politik"},
    {"name": "Okezone - News", "url": "https://sindikasi.okezone.com/index.php/rss/1/RSS2.0", "category": "politik", "lang": "id", "topic": "politik"},
    # --- Saham Indonesia ---
    {"name": "CNBC Indonesia - Market", "url": "https://www.cnbcindonesia.com/market/rss", "category": "saham", "lang": "id"},
    {"name": "Antara - Bursa", "url": "https://www.antaranews.com/rss/ekonomi-bursa.xml", "category": "saham", "lang": "id"},
    {"name": "Detik Finance - Bursa & Valas", "url": "https://finance.detik.com/bursa-dan-valas/rss", "category": "saham", "lang": "id"},
    {"name": "IDX Channel", "url": "https://www.idxchannel.com/rss", "category": "saham", "lang": "id"},
    {"name": "CNN Indonesia - Ekonomi", "url": "https://www.cnnindonesia.com/ekonomi/rss", "category": "saham", "lang": "id"},
    {"name": "Tempo - Bisnis", "url": "https://rss.tempo.co/bisnis", "category": "saham", "lang": "id"},
    {"name": "CNBC Indonesia - Research", "url": "https://www.cnbcindonesia.com/research/rss", "category": "saham", "lang": "id"},
    {"name": "Bloomberg Technoz", "url": "https://www.bloombergtechnoz.com/rss", "category": "saham", "lang": "id"},
    {"name": "Antara - Finansial", "url": "https://www.antaranews.com/rss/ekonomi-finansial.xml", "category": "saham", "lang": "id"},
    {"name": "Investing.com Indonesia - Saham", "url": "https://id.investing.com/rss/news_25.rss", "category": "saham", "lang": "id"},
    # --- Crypto ---
    {"name": "Blockchain Media Indonesia", "url": "https://www.blockchainmedia.id/feed/", "category": "crypto", "lang": "id"},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "category": "crypto", "lang": "en"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "category": "crypto", "lang": "en"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "category": "crypto", "lang": "en"},
    {"name": "The Block", "url": "https://www.theblock.co/rss.xml", "category": "crypto", "lang": "en"},
    {"name": "NewsBTC", "url": "https://www.newsbtc.com/feed/", "category": "crypto", "lang": "en"},
    # --- Game ---
    {"name": "Gamebrott", "url": "https://www.gamebrott.com/feed", "category": "game", "lang": "id"},
    {"name": "JagatPlay", "url": "https://www.jagatplay.com/feed", "category": "game", "lang": "id"},
    {"name": "Detik Inet - Games", "url": "https://inet.detik.com/games/rss", "category": "game", "lang": "id"},
    {"name": "Antara - Tekno & Game", "url": "https://www.antaranews.com/rss/tekno-game.xml", "category": "game", "lang": "id",
     "topic": "game"},  # feed campuran teknologi: hanya artikel yang memang tentang game yang boleh diposting
    {"name": "RevivalTV", "url": "https://www.revivaltv.id/feed/", "category": "game", "lang": "id"},
    # --- Game khusus (semua artikelnya otomatis ditandai topik game_topic) ---
    {"name": "Dexerto - VALORANT", "url": "https://www.dexerto.com/valorant/feed/", "category": "game", "lang": "en",
     "game_topic": "valorant"},
    {"name": "VLR.gg", "url": "https://www.vlr.gg/rss", "category": "game", "lang": "en", "game_topic": "valorant",
     "timeout": 45},
    {"name": "Gamebrott - Dota 2", "url": "https://gamebrott.com/tag/dota-2/feed", "category": "game", "lang": "id",
     "game_topic": "dota2"},
    {"name": "PCGamesN - VALORANT", "url": "https://www.pcgamesn.com/valorant/feed", "category": "game", "lang": "en",
     "game_topic": "valorant"},
    {"name": "PCGamesN - Dota 2", "url": "https://www.pcgamesn.com/dota-2/feed", "category": "game", "lang": "en",
     "game_topic": "dota2"},
    {"name": "Dexerto - Esports", "url": "https://www.dexerto.com/esports/feed/", "category": "game", "lang": "en"},
    {"name": "IGN", "url": "https://feeds.feedburner.com/ign/games-all", "category": "game", "lang": "en"},
    {"name": "GameSpot", "url": "https://www.gamespot.com/feeds/mashup/", "category": "game", "lang": "en"},
    {"name": "Polygon", "url": "https://www.polygon.com/rss/index.xml", "category": "game", "lang": "en"},
    {"name": "PC Gamer", "url": "https://www.pcgamer.com/rss/", "category": "game", "lang": "en"},
    {"name": "Eurogamer", "url": "https://www.eurogamer.net/feed/news", "category": "game", "lang": "en"},
]

# Saham Bursa Efek Indonesia (kode Yahoo Finance: <KODE>.JK) + indeks.
IDX_INDICES = {"^JKSE": "IHSG (Jakarta Composite Index)", "^JKLQ45": "LQ45"}
IDX_TICKERS = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BBTN", "BRIS", "ARTO", "TLKM", "EXCL", "ISAT",
    "TOWR", "TBIG", "ASII", "UNTR", "UNVR", "ICBP", "INDF", "MYOR", "KLBF", "SIDO",
    "HMSP", "GGRM", "CPIN", "JPFA", "AMRT", "MAPI", "ACES", "GOTO", "BUKA", "EMTK",
    "ADRO", "PTBA", "ITMG", "ANTM", "INCO", "MDKA", "MBMA", "AMMN", "MEDC", "PGAS",
    "AKRA", "BRPT", "TPIA", "BREN", "CUAN", "PGEO", "ESSA", "INKP", "SMGR", "INTP",
    "JSMR", "CTRA", "BSDE", "PWON", "SMRA",
]
STOCK_HISTORY_RANGE = "3mo"  # rentang data harian yang diambil setiap run

COINGECKO_PAGES = 1  # 250 koin per halaman

# --- Sentimen ---
# Alias nama perusahaan (dicocokkan tanpa beda huruf besar/kecil). Kode saham sendiri
# dicocokkan case-sensitive (harus huruf besar) agar "BUKA"/"CUAN" tidak cocok dengan kata biasa.
STOCK_ALIASES = {
    "^JKSE": ["IHSG", "Indeks Harga Saham Gabungan", "Jakarta Composite"],
    "^JKLQ45": ["LQ45"],
    "BBCA": ["Bank Central Asia", "BCA"], "BBRI": ["Bank Rakyat Indonesia", "BRI"],
    "BMRI": ["Bank Mandiri"], "BBNI": ["Bank Negara Indonesia", "BNI"], "BBTN": ["Bank Tabungan Negara", "BTN"],
    "BRIS": ["Bank Syariah Indonesia", "BSI"], "ARTO": ["Bank Jago"], "TLKM": ["Telkom Indonesia", "Telkom"],
    "EXCL": ["XL Axiata", "XLSmart"], "ISAT": ["Indosat"], "TOWR": ["Sarana Menara"], "TBIG": ["Tower Bersama"],
    "ASII": ["Astra International"], "UNTR": ["United Tractors"], "UNVR": ["Unilever Indonesia"],
    "ICBP": ["Indofood CBP"], "INDF": ["Indofood Sukses"], "MYOR": ["Mayora"], "KLBF": ["Kalbe Farma"],
    "SIDO": ["Sido Muncul"], "HMSP": ["Sampoerna"], "GGRM": ["Gudang Garam"], "CPIN": ["Charoen Pokphand"],
    "JPFA": ["Japfa"], "AMRT": ["Alfamart", "Sumber Alfaria"], "MAPI": ["Mitra Adiperkasa"], "ACES": ["Ace Hardware"],
    "GOTO": ["GoTo Gojek", "GoTo"], "BUKA": ["Bukalapak"], "EMTK": ["Elang Mahkota"], "ADRO": ["Adaro", "AlamTri"],
    "PTBA": ["Bukit Asam"], "ITMG": ["Indo Tambangraya"], "ANTM": ["Aneka Tambang", "Antam"], "INCO": ["Vale Indonesia"],
    "MDKA": ["Merdeka Copper"], "MBMA": ["Merdeka Battery"], "AMMN": ["Amman Mineral"], "MEDC": ["Medco Energi"],
    "PGAS": ["Perusahaan Gas Negara", "PGN"], "AKRA": ["AKR Corporindo"], "BRPT": ["Barito Pacific"],
    "TPIA": ["Chandra Asri"], "BREN": ["Barito Renewables"], "CUAN": ["Petrindo Jaya"], "PGEO": ["Pertamina Geothermal"],
    "ESSA": ["ESSA Industries"], "INKP": ["Indah Kiat"], "SMGR": ["Semen Indonesia"], "INTP": ["Indocement"],
    "JSMR": ["Jasa Marga"], "CTRA": ["Ciputra Development"], "BSDE": ["Bumi Serpong"], "PWON": ["Pakuwon"],
    "SMRA": ["Summarecon"],
}

# Koin yang dilacak sentimen & harga hariannya: id CoinGecko -> (simbol, [alias nama])
TRACKED_COINS = {
    "bitcoin": ("BTC", ["Bitcoin"]), "ethereum": ("ETH", ["Ethereum", "Ether"]),
    "binancecoin": ("BNB", ["Binance Coin"]), "solana": ("SOL", ["Solana"]), "ripple": ("XRP", ["Ripple"]),
    "dogecoin": ("DOGE", ["Dogecoin"]), "cardano": ("ADA", ["Cardano"]), "tron": ("TRX", ["TRON"]),
    "avalanche-2": ("AVAX", ["Avalanche"]), "chainlink": ("LINK", ["Chainlink"]),
    "shiba-inu": ("SHIB", ["Shiba Inu"]), "polkadot": ("DOT", ["Polkadot"]), "sui": ("SUI", []),
    "pepe": ("PEPE", []), "hyperliquid": ("HYPE", ["Hyperliquid"]),
}

# Google News RSS: berita per aset dalam rentang waktu ini.
GOOGLE_NEWS_WINDOW = "7d"

# Kata kunci topik untuk feed campuran (lihat kunci "topic" di NEWS_FEEDS).
TOPIC_KEYWORDS = {
    # feed berita umum di kategori politik: hanya artikel yang benar-benar tentang politik/pemerintahan
    "politik": r"\b(politik|politisi|partai|dpr|dprd|mpr|dpd|presiden|wapres|wakil presiden|menteri|kabinet|"
               r"pemerintah|istana|prabowo|gibran|gubernur|bupati|wali ?kota|pilkada|pemilu|kpu|bawaslu|"
               r"koalisi|oposisi|ruu|undang-undang|perppu|perpres|mk|mahkamah konstitusi|kpk|korupsi|"
               r"legislatif|parlemen|fraksi|reshuffle|kebijakan|anggaran|apbn|demo|unjuk rasa|"
               r"kementerian|diplomasi|dubes|pdip|gerindra|golkar|nasdem|pkb|pks|demokrat|pan|psi)\b",
    "game": r"\b(game|gaming|gamer|games|esports?|e-sports|konsol|playstation|ps5|ps4|xbox|nintendo|switch 2|steam|"
            r"mobile legends|mlbb|mpl|free fire|pubg|genshin|honkai|valorant|dota|roblox|minecraft|fortnite|"
            r"call of duty|gta|epic games|ubisoft|capcom|square enix|bandai|sega|konami|riot|blizzard|"
            r"turnamen|rpg|fps|moba)\b",
}

# Topik game khusus: dipakai untuk menandai artikel (tabel article_assets, asset_type="game")
# dan untuk slot jadwal khusus di social_accounts.json ({"kind": "news", "topic": "valorant"}).
GAME_TOPICS = {
    "valorant": {
        "label": "VALORANT",
        "pattern": r"\bvalorant\b|\bVCT\b|valorant champions|game changers championship",
        "hashtags": ["valorant", "valorantindonesia", "VCT", "valorantclips", "riotgames"],
    },
    "dota2": {
        "label": "DOTA 2",
        "pattern": r"\bdota ?2\b|\bdota\b|the international 20\d\d|\bTI ?20\d\d\b",
        "hashtags": ["dota2", "dota2indonesia", "dota", "TheInternational", "valve"],
    },
}
