CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER DEFAULT 1,
    listing_type TEXT DEFAULT 'both',
    property_type TEXT DEFAULT 'both',
    price_min INTEGER DEFAULT 0,
    price_max INTEGER DEFAULT 0,
    size_min INTEGER DEFAULT 0,
    size_max INTEGER DEFAULT 0,
    districts TEXT DEFAULT '[]',
    floor_min INTEGER DEFAULT 0,
    score_threshold INTEGER DEFAULT 60,
    notify_email INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash_id TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    locality TEXT,
    price INTEGER DEFAULT 0,
    price_currency TEXT DEFAULT 'CZK',
    listing_type TEXT,
    property_type TEXT,
    size_m2 INTEGER DEFAULT 0,
    floor_number INTEGER DEFAULT 0,
    image_url TEXT,
    url TEXT,
    raw_data TEXT,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT NOT NULL,
    price INTEGER,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (listing_hash_id) REFERENCES listings(hash_id)
);

CREATE TABLE IF NOT EXISTS listing_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT NOT NULL,
    profile_id INTEGER NOT NULL,
    score INTEGER,
    score_breakdown TEXT,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(listing_hash_id, profile_id)
);

CREATE TABLE IF NOT EXISTS seen_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT NOT NULL,
    profile_id INTEGER NOT NULL,
    seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(listing_hash_id, profile_id)
);

CREATE TABLE IF NOT EXISTS saved_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'interested',
    notes TEXT DEFAULT '[]',
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hidden_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT NOT NULL UNIQUE,
    hidden_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_hash_id TEXT,
    profile_id INTEGER,
    notification_type TEXT,
    channel TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success INTEGER DEFAULT 1,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS supermarkets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT NOT NULL,
    osm_id TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    name TEXT,
    address TEXT,
    city TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id TEXT UNIQUE,
    name TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    area_m2 REAL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scraper_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    sreality_fetched INTEGER DEFAULT 0,
    bezrealitky_fetched INTEGER DEFAULT 0,
    expats_fetched INTEGER DEFAULT 0,
    new_listings INTEGER DEFAULT 0,
    deduplicated INTEGER DEFAULT 0,
    profile_matches TEXT DEFAULT '{}',
    errors TEXT DEFAULT '[]',
    status TEXT DEFAULT 'ok'
);
