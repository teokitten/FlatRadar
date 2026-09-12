import os
import shutil
import sqlite3
import config

SETTING_DEFAULTS = {
    'smtp_host': 'smtp.mail.yahoo.com',
    'smtp_port': '587',
    'smtp_user': '',
    'smtp_password': '',
    'email_from': '',
    'email_to': '',
    'notifications_enabled': '0',
    'scheduler_interval_minutes': '20',
    'notification_frequency': 'daily',
    'last_notification_sent': '',
}


def get_connection():
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


def seed_defaults():
    conn = get_connection()
    for key, value in SETTING_DEFAULTS.items():
        conn.execute(
            'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
            (key, value),
        )
    conn.commit()
    conn.close()


def _backup_db():
    """On startup, copy the DB to a timestamped backup if it has real data."""
    if not os.path.exists(config.DATABASE_PATH):
        return
    if os.path.getsize(config.DATABASE_PATH) < 8192:
        return  # empty or schema-only, not worth backing up
    backup_path = config.DATABASE_PATH + '.backup'
    try:
        shutil.copy2(config.DATABASE_PATH, backup_path)
    except Exception as e:
        print(f'DB backup failed: {e}')


def init_db():
    _backup_db()
    with open(config.SCHEMA_PATH, 'r') as f:
        schema = f.read()
    conn = get_connection()
    conn.executescript(schema)
    conn.commit()

    migrations = [
        'ALTER TABLE listings ADD COLUMN lat REAL',
        'ALTER TABLE listings ADD COLUMN lng REAL',
        "ALTER TABLE profiles ADD COLUMN supermarket_chains TEXT DEFAULT '[]'",
        'ALTER TABLE profiles ADD COLUMN supermarket_max_km REAL DEFAULT 0',
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # Column already exists

    new_migrations = [
        'ALTER TABLE listings ADD COLUMN room_type TEXT',
        "ALTER TABLE listings ADD COLUMN features_parsed TEXT DEFAULT '{}'",
        "ALTER TABLE profiles ADD COLUMN room_types TEXT DEFAULT '[]'",
        "ALTER TABLE profiles ADD COLUMN feature_balcony INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_terrace INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_parking INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_cellar INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_bathtub INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_dishwasher INTEGER DEFAULT 0",
        "ALTER TABLE profiles ADD COLUMN feature_furnished TEXT DEFAULT 'any'",
        "ALTER TABLE profiles ADD COLUMN feature_building_age TEXT DEFAULT 'any'",
    ]
    for sql in new_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    park_migrations = [
        'ALTER TABLE profiles ADD COLUMN park_max_km REAL DEFAULT 0',
    ]
    for sql in park_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    commute_migrations = [
        'ALTER TABLE profiles ADD COLUMN workplace_address TEXT',
        'ALTER TABLE profiles ADD COLUMN workplace_lat REAL',
        'ALTER TABLE profiles ADD COLUMN workplace_lng REAL',
    ]
    for sql in commute_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    selection_migrations = [
        "ALTER TABLE profiles ADD COLUMN metro_stops TEXT DEFAULT '[]'",
        "ALTER TABLE profiles ADD COLUMN selected_neighborhoods TEXT DEFAULT '[]'",
        "ALTER TABLE profiles ADD COLUMN selected_cities TEXT DEFAULT '[]'",
    ]
    for sql in selection_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS scraper_runs (
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
        )''')
        conn.commit()
    except Exception:
        pass

    furnished_migrations = [
        "ALTER TABLE profiles ADD COLUMN feature_furnished_v2 TEXT DEFAULT '[]'",
        "ALTER TABLE profiles ADD COLUMN feature_building_age_v2 TEXT DEFAULT '[]'",
    ]
    for sql in furnished_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass

    conn.close()

    img_dir = os.path.join(os.path.dirname(config.DATABASE_PATH), 'static', 'listing_images')
    os.makedirs(img_dir, exist_ok=True)

    seed_defaults()

    # Only run furnished/age migration once
    already_migrated = get_setting('furnished_migration_done', '0')
    if already_migrated != '1':
        conn = get_connection()
        try:
            conn.execute("""
                UPDATE profiles
                SET feature_furnished_v2 = CASE
                    WHEN feature_furnished IS NULL OR feature_furnished = 'any' OR feature_furnished = '' THEN '[]'
                    WHEN feature_furnished LIKE '[%' THEN feature_furnished
                    ELSE json_array(feature_furnished)
                END
                WHERE feature_furnished_v2 = '[]'
            """)
            conn.execute("""
                UPDATE profiles
                SET feature_building_age_v2 = CASE
                    WHEN feature_building_age IS NULL OR feature_building_age = 'any' OR feature_building_age = '' THEN '[]'
                    WHEN feature_building_age LIKE '[%' THEN feature_building_age
                    ELSE json_array(feature_building_age)
                END
                WHERE feature_building_age_v2 = '[]'
            """)
            conn.commit()
            set_setting('furnished_migration_done', '1')
        except Exception as e:
            print(f'Furnished migration: {e}')
        finally:
            conn.close()


def get_setting(key, default=''):
    conn = get_connection()
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key, value):
    conn = get_connection()
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()
