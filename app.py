from flask import Flask, jsonify, request, render_template, Response
import json
import csv
import io
import os
import threading
import time as _time
from datetime import datetime
from database import init_db, get_connection, get_setting, set_setting, SETTING_DEFAULTS
import database
import scheduler as sched
import scoring
import notifier
import config
import supermarkets as sm

app = Flask(__name__)

init_db()

# Ensure static directory exists
os.makedirs(os.path.join(os.path.dirname(__file__), 'static', 'listing_images'), exist_ok=True)


class _SrealitySession:
    """Maintains a persistent requests session with sreality.cz cookies."""
    def __init__(self):
        self._session = None
        self._lock = threading.Lock()
        self._last_refresh = 0

    def _build_session(self):
        import requests as req
        s = req.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept-Language': 'cs-CZ,cs;q=0.9,en;q=0.8',
        })
        try:
            s.get('https://www.sreality.cz/', timeout=10,
                  headers={'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'})
            print('Sreality session established')
        except Exception as e:
            print(f'Sreality session init failed: {e}')
        return s

    def get(self, url, **kwargs):
        with self._lock:
            now = _time.time()
            if self._session is None or now - self._last_refresh > 3600:
                self._session = self._build_session()
                self._last_refresh = now
        return self._session.get(url, **kwargs)

sreality_session = _SrealitySession()

PROFILE_FIELDS = [
    'name', 'active', 'listing_type', 'property_type', 'price_min', 'price_max',
    'size_min', 'size_max', 'districts', 'floor_min', 'score_threshold', 'notify_email',
    'supermarket_chains', 'supermarket_max_km',
    'room_types', 'feature_balcony', 'feature_terrace', 'feature_parking',
    'feature_cellar', 'feature_bathtub', 'feature_dishwasher',
    'feature_furnished', 'feature_building_age', 'park_max_km',
    'workplace_address', 'workplace_lat', 'workplace_lng',
    'metro_stops', 'selected_neighborhoods', 'selected_cities',
    'feature_furnished_v2', 'feature_building_age_v2',
]

_FEATURE_BOOL_FIELDS = (
    'feature_balcony', 'feature_terrace', 'feature_parking',
    'feature_cellar', 'feature_bathtub', 'feature_dishwasher',
)


def _profile_row_to_dict(row):
    d = dict(row)
    try:
        d['districts'] = json.loads(d.get('districts') or '[]')
    except (ValueError, TypeError):
        d['districts'] = []
    return d


def _normalize_profile_body(body):
    values = {}
    for key in PROFILE_FIELDS:
        if key not in body:
            continue
        val = body[key]
        if key == 'districts':
            if isinstance(val, list):
                val = json.dumps([str(x).strip() for x in val if str(x).strip()])
            else:
                val = json.dumps([])
        elif key == 'supermarket_chains':
            if isinstance(val, list):
                val = json.dumps([str(x).strip() for x in val if str(x).strip()])
            elif not isinstance(val, str):
                val = json.dumps([])
        elif key == 'supermarket_max_km':
            try:
                val = float(val or 0)
            except (ValueError, TypeError):
                val = 0
        elif key == 'park_max_km':
            try:
                val = float(val or 0)
            except (ValueError, TypeError):
                val = 0
        elif key == 'room_types':
            if isinstance(val, list):
                val = json.dumps([str(x).strip() for x in val if str(x).strip()])
            elif not isinstance(val, str):
                val = json.dumps([])
        elif key in _FEATURE_BOOL_FIELDS:
            try:
                val = 1 if int(val) else 0
            except (ValueError, TypeError):
                val = 0
        elif key in ('feature_furnished', 'feature_building_age'):
            val = str(val or 'any')
        values[key] = val
    return values


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/feed')
def api_feed():
    profile_id = request.args.get('profile_id', type=int)
    listing_type = request.args.get('listing_type', default='', type=str)
    sort = request.args.get('sort', default='score', type=str)
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=24, type=int)

    order_map = {
        'score': 'score DESC, l.first_seen_at DESC',
        'date': 'l.first_seen_at DESC',
        'price_asc': 'l.price ASC',
        'price_desc': 'l.price DESC',
    }
    order_by = order_map.get(sort, order_map['score'])

    conn = get_connection()

    # Step 1 - fetch the active profile, if any, for hard-filtering
    profile = None
    if profile_id is not None:
        prow = conn.execute('SELECT * FROM profiles WHERE id = ?', (profile_id,)).fetchone()
        profile = dict(prow) if prow else None

    params = {'profile_id': profile_id}
    where = "WHERE l.active = 1 AND l.hash_id NOT IN (SELECT listing_hash_id FROM hidden_listings)"
    if listing_type and listing_type != 'both':
        where += " AND l.listing_type = :listing_type"
        params['listing_type'] = listing_type
    if profile_id is not None:
        where += """ AND COALESCE(ls.score, 0) >= (
            SELECT score_threshold FROM profiles WHERE id = :profile_id
        )"""

    # Step 2 - hard filters derived from the profile's constraints
    hard_filters = []
    if profile and profile['listing_type'] != 'both':
        hard_filters.append('l.listing_type = :hf_listing_type')
        params['hf_listing_type'] = profile['listing_type']
    if profile and profile['price_max'] > 0:
        hard_filters.append('(l.price = 0 OR l.price <= :price_max)')
        params['price_max'] = profile['price_max']
    if profile and profile['size_min'] > 0:
        hard_filters.append('(l.size_m2 = 0 OR l.size_m2 >= :size_min)')
        params['size_min'] = profile['size_min']
    for cond in hard_filters:
        where += f' AND {cond}'

    score_join = """
        LEFT JOIN listing_scores ls ON l.hash_id = ls.listing_hash_id
            AND ls.profile_id = COALESCE(:profile_id, (
                SELECT id FROM profiles WHERE active=1 ORDER BY id LIMIT 1
            ))
    """

    base = f"""
        SELECT
            l.*,
            COALESCE(ls.score, 0) AS score,
            COALESCE(ls.score_breakdown, '{{}}') AS score_breakdown,
            CASE WHEN sl.listing_hash_id IS NOT NULL THEN 1 ELSE 0 END AS is_saved,
            sl.status AS saved_status
        FROM listings l
        {score_join}
        LEFT JOIN saved_listings sl ON l.hash_id = sl.listing_hash_id
        {where}
    """

    # Step 3 - districts require Python-side matching against free-text locality
    districts = json.loads(profile.get('districts', '[]')) if profile else []
    districts = [d for d in districts if d]

    # Room type hard filter also requires Python-side matching (parsed column)
    room_types = json.loads(profile.get('room_types', '[]')) if profile else []
    room_types = [r for r in room_types if r]

    # Free-text locality search also requires Python-side matching
    locality_q = request.args.get('locality', '').strip().lower()

    # Commute sort requires Python-side sorting against workplace coords
    wp_lat = profile.get('workplace_lat') if profile else None
    wp_lng = profile.get('workplace_lng') if profile else None
    sort_by_commute = bool(sort == 'commute' and wp_lat and wp_lng)

    needs_python_filter = bool(districts or room_types or locality_q or sort_by_commute)

    if needs_python_filter:
        # Location/room-type filtering happens in Python, so fetch every matching
        # row first (no SQL-level pagination) and paginate after filtering below.
        rows = conn.execute(base + f" ORDER BY {order_by}", params).fetchall()
    else:
        total = conn.execute(
            f"SELECT COUNT(*) FROM listings l {score_join} {where}", params
        ).fetchone()[0]
        query = base + f" ORDER BY {order_by} LIMIT :limit OFFSET :offset"
        params['limit'] = per_page
        params['offset'] = (page - 1) * per_page
        rows = conn.execute(query, params).fetchall()

    # Get seen listing hash_ids for active profiles
    seen_ids = set()
    if profile_id:
        seen_rows = conn.execute(
            'SELECT listing_hash_id FROM seen_listings WHERE profile_id=?',
            (profile_id,)
        ).fetchall()
        seen_ids = {r['listing_hash_id'] for r in seen_rows}
    else:
        seen_rows = conn.execute(
            'SELECT DISTINCT listing_hash_id FROM seen_listings'
        ).fetchall()
        seen_ids = {r['listing_hash_id'] for r in seen_rows}

    listings = []
    for row in rows:
        d = dict(row)
        try:
            d['score_breakdown'] = json.loads(d.get('score_breakdown') or '{}')
        except (ValueError, TypeError):
            d['score_breakdown'] = {}
        d['is_hidden'] = False
        d['is_new'] = d['hash_id'] not in seen_ids

        ph = conn.execute(
            'SELECT price FROM price_history WHERE listing_hash_id = ? ORDER BY recorded_at DESC LIMIT 2',
            (d['hash_id'],),
        ).fetchall()
        d['price_drop'] = bool(len(ph) >= 2 and ph[0]['price'] is not None
                               and ph[1]['price'] is not None
                               and ph[0]['price'] < ph[1]['price'])
        listings.append(d)

    from commute import haversine_km, walk_minutes_estimate
    for listing in listings:
        if wp_lat and wp_lng and listing.get('lat') and listing.get('lng'):
            dist = haversine_km(
                listing['lat'], listing['lng'], wp_lat, wp_lng
            )
            listing['commute_km'] = round(dist, 2)
            listing['commute_walk_est'] = walk_minutes_estimate(dist)
        else:
            listing['commute_km'] = None
            listing['commute_walk_est'] = None

    if locality_q:
        listings = [
            l for l in listings
            if locality_q in (l.get('locality') or '').lower()
            or locality_q in (l.get('title') or '').lower()
        ]

    if districts:
        # Step 3 - keep only listings whose locality mentions a selected district
        listings = [
            l for l in listings
            if any(d.lower() in (l.get('locality') or '').lower() for d in districts)
        ]

    if room_types:
        # Hard filter on room type; listings with no room_type extracted are
        # let through (incomplete data shouldn't be excluded outright)
        listings = [
            l for l in listings
            if not l.get('room_type') or l.get('room_type') in room_types
        ]

    if sort_by_commute:
        listings = sorted(
            listings,
            key=lambda l: l.get('commute_km') or 999
        )

    if needs_python_filter:
        # Step 4 - paginate the filtered list; total reflects the filtered count
        total = len(listings)
        offset = (page - 1) * per_page
        listings = listings[offset:offset + per_page]

    prof = conn.execute(
        'SELECT supermarket_chains, supermarket_max_km FROM profiles '
        'WHERE id = COALESCE(:profile_id, '
        '(SELECT id FROM profiles WHERE active=1 ORDER BY id LIMIT 1))',
        {'profile_id': profile_id},
    ).fetchone()
    sm_chains = []
    sm_max_km = 0.0
    if prof:
        try:
            sm_chains = json.loads(prof['supermarket_chains'] or '[]')
        except (ValueError, TypeError):
            sm_chains = []
        sm_max_km = float(prof['supermarket_max_km'] or 0)

    if sm_chains and sm_max_km > 0:
        placeholders = ','.join('?' * len(sm_chains))
        sm_locs = conn.execute(
            f'SELECT chain, lat, lng, name, city FROM supermarkets WHERE chain IN ({placeholders})',
            sm_chains,
        ).fetchall()
        for d in listings:
            lat, lng = d.get('lat'), d.get('lng')
            if lat is None or lng is None or not sm_locs:
                d['nearest_supermarket'] = None
                continue
            best = None
            for loc in sm_locs:
                dist = sm.haversine_km(lat, lng, loc['lat'], loc['lng'])
                if best is None or dist < best['distance_km']:
                    best = {
                        'chain': loc['chain'], 'name': loc['name'],
                        'city': loc['city'], 'distance_km': round(dist, 2),
                    }
            d['nearest_supermarket'] = best
    else:
        for d in listings:
            d['nearest_supermarket'] = None

    conn.close()

    return jsonify({
        'listings': listings,
        'total': total,
        'page': page,
        'per_page': per_page,
    })


@app.route('/api/image-proxy')
def image_proxy():
    url = request.args.get('url', '')
    if not url or not url.startswith('https://'):
        return '', 400
    try:
        resp = sreality_session.get(url, headers={
            'Referer': 'https://www.sreality.cz/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }, timeout=10)
        if resp.status_code == 200 and resp.content:
            return resp.content, 200, {
                'Content-Type': resp.headers.get('Content-Type', 'image/jpeg'),
                'Cache-Control': 'public, max-age=86400',
            }
    except Exception as e:
        print(f'Image proxy error: {e}')
    return '', 404


@app.route('/api/admin/backfill-images', methods=['POST'])
def backfill_images():
    import threading
    def _backfill():
        import requests as req
        import os
        conn = get_connection()
        # Skip sreality – their CDN blocks all non-browser requests
        # Cache bezrealitky and expats images which load fine
        rows = conn.execute(
            'SELECT hash_id, image_url, source FROM listings '
            'WHERE source IN ("bezrealitky", "expats") '
            'AND image_url LIKE "https://%" '
            'AND image_url != "" '
            'LIMIT 1000'
        ).fetchall()
        print(f'[backfill] {len(rows)} images to cache')
        updated = 0
        for row in rows:
            hash_id = row['hash_id']
            url = row['image_url']
            local_path = os.path.join(config.IMAGE_CACHE_DIR, f'{hash_id}.jpg')
            if os.path.exists(local_path):
                continue
            try:
                resp = req.get(url, timeout=8, headers={
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
                })
                if resp.status_code == 200 and resp.content:
                    os.makedirs(config.IMAGE_CACHE_DIR, exist_ok=True)
                    with open(local_path, 'wb') as f:
                        f.write(resp.content)
                    local_url = config.IMAGE_CACHE_URL + f'{hash_id}.jpg'
                    conn.execute(
                        'UPDATE listings SET image_url = ? WHERE hash_id = ?',
                        (local_url, hash_id)
                    )
                    updated += 1
                    if updated % 50 == 0:
                        conn.commit()
                        print(f'[backfill] {updated} cached so far')
            except Exception as e:
                print(f'[backfill] failed {hash_id}: {e}')
        conn.commit()
        conn.close()
        print(f'[backfill] complete: {updated} images cached')
    threading.Thread(target=_backfill, daemon=True).start()
    return jsonify({'started': True, 'message': 'Backfilling up to 500 images in background'})


@app.route('/api/profiles')
def api_profiles():
    conn = get_connection()
    rows = conn.execute('SELECT * FROM profiles ORDER BY id').fetchall()
    conn.close()
    return jsonify([_profile_row_to_dict(r) for r in rows])


@app.route('/api/profiles', methods=['POST'])
def api_create_profile():
    body = request.get_json(force=True) or {}
    if not body.get('name'):
        return jsonify({'error': 'name is required'}), 400

    values = _normalize_profile_body(body)
    values.setdefault('name', body['name'])
    cols = list(values.keys())
    placeholders = ', '.join(['?'] * len(cols))
    conn = get_connection()
    cur = conn.execute(
        f"INSERT INTO profiles ({', '.join(cols)}) VALUES ({placeholders})",
        [values[c] for c in cols],
    )
    conn.commit()
    row = conn.execute('SELECT * FROM profiles WHERE id = ?', (cur.lastrowid,)).fetchone()
    conn.close()
    return jsonify(_profile_row_to_dict(row)), 201


@app.route('/api/profiles/<int:id>', methods=['PUT'])
def api_update_profile(id):
    body = request.get_json(force=True) or {}
    values = _normalize_profile_body(body)
    if not values:
        conn = get_connection()
        row = conn.execute('SELECT * FROM profiles WHERE id = ?', (id,)).fetchone()
        conn.close()
        return jsonify(_profile_row_to_dict(row)) if row else (jsonify({'error': 'not found'}), 404)

    set_clause = ', '.join([f"{c} = ?" for c in values.keys()])
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    conn = get_connection()
    conn.execute(
        f"UPDATE profiles SET {set_clause} WHERE id = ?",
        [*values.values(), id],
    )
    conn.commit()
    row = conn.execute('SELECT * FROM profiles WHERE id = ?', (id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'not found'}), 404
    return jsonify(_profile_row_to_dict(row))


@app.route('/api/profiles/<int:id>', methods=['DELETE'])
def api_delete_profile(id):
    conn = get_connection()
    conn.execute('DELETE FROM profiles WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return jsonify({'deleted': True})


@app.route('/api/profiles/<int:id>/toggle', methods=['PATCH'])
def api_toggle_profile(id):
    conn = get_connection()
    conn.execute('UPDATE profiles SET active = 1 - active, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (id,))
    conn.commit()
    row = conn.execute('SELECT * FROM profiles WHERE id = ?', (id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': 'not found'}), 404
    return jsonify(_profile_row_to_dict(row))


@app.route('/api/status')
def api_status():
    conn = get_connection()
    total = conn.execute('SELECT COUNT(*) FROM listings WHERE active=1').fetchone()[0]
    new_today = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE first_seen_at >= datetime('now', '-24 hours')"
    ).fetchone()[0]
    active_profiles = conn.execute('SELECT COUNT(*) FROM profiles WHERE active=1').fetchone()[0]
    source_rows = conn.execute(
        "SELECT source, COUNT(*) AS n FROM listings WHERE active=1 GROUP BY source"
    ).fetchall()
    conn.close()
    counts = {row['source']: row['n'] for row in source_rows}
    return jsonify({
        'scheduler': sched.get_status(),
        'db': {
            'total_listings': total,
            'new_today': new_today,
            'active_profiles': active_profiles,
            'sources': {
                'sreality': counts.get('sreality', 0),
                'bezrealitky': counts.get('bezrealitky', 0),
                'expats': counts.get('expats', 0),
            },
        },
    })


@app.route('/api/scheduler/trigger', methods=['POST'])
def api_scheduler_trigger():
    sched.trigger_now()
    return jsonify({'triggered': True})


@app.route('/api/scheduler/toggle', methods=['POST'])
def api_scheduler_toggle():
    if sched.get_status()['running']:
        sched.stop_scheduler()
    else:
        sched.start_scheduler()
    return jsonify(sched.get_status())


@app.route('/api/scheduler/config', methods=['POST'])
def set_scheduler_config():
    data = request.get_json()
    allowed = ['scheduler_interval_minutes', 'notification_frequency']
    for key in allowed:
        if key in data:
            set_setting(key, str(data[key]))
    sched.restart_scheduler()
    return jsonify(sched.get_status())


@app.route('/api/listings/<hash_id>/hide', methods=['POST'])
def api_hide_listing(hash_id):
    conn = get_connection()
    conn.execute('INSERT OR IGNORE INTO hidden_listings (listing_hash_id) VALUES (?)', (hash_id,))
    conn.commit()
    conn.close()
    return jsonify({'hidden': True})


@app.route('/api/listings/<hash_id>/hide', methods=['DELETE'])
def api_unhide_listing(hash_id):
    conn = get_connection()
    conn.execute('DELETE FROM hidden_listings WHERE listing_hash_id = ?', (hash_id,))
    conn.commit()
    conn.close()
    return jsonify({'hidden': False})


@app.route('/api/listings/<hash_id>/save', methods=['POST'])
def api_save_listing(hash_id):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO saved_listings (listing_hash_id, status) VALUES (?, 'interested')",
        (hash_id,),
    )
    conn.commit()
    conn.close()
    return jsonify({'saved': True})


@app.route('/api/listings/<hash_id>/save', methods=['DELETE'])
def api_unsave_listing(hash_id):
    conn = get_connection()
    conn.execute('DELETE FROM saved_listings WHERE listing_hash_id = ?', (hash_id,))
    conn.commit()
    conn.close()
    return jsonify({'saved': False})


@app.route('/api/listings/<hash_id>/seen', methods=['POST'])
def api_seen_listing(hash_id):
    conn = get_connection()
    profiles = conn.execute('SELECT id FROM profiles WHERE active=1').fetchall()
    for p in profiles:
        conn.execute(
            'INSERT OR IGNORE INTO seen_listings (listing_hash_id, profile_id) VALUES (?, ?)',
            (hash_id, p['id']),
        )
    conn.commit()
    conn.close()
    return jsonify({'seen': True})


@app.route('/api/listings/seen-batch', methods=['POST'])
def seen_batch():
    data = request.get_json()
    hash_ids = data.get('hash_ids', [])
    profile_id = data.get('profile_id')
    if not hash_ids:
        return jsonify({'seen': 0})
    conn = get_connection()
    # Get all active profile ids if no specific profile
    if profile_id:
        profile_ids = [profile_id]
    else:
        profiles = conn.execute(
            'SELECT id FROM profiles WHERE active=1'
        ).fetchall()
        profile_ids = [p['id'] for p in profiles]
    count = 0
    for hid in hash_ids:
        for pid in profile_ids:
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO seen_listings '
                    '(listing_hash_id, profile_id) VALUES (?,?)',
                    (hid, pid)
                )
                count += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    return jsonify({'seen': count})


@app.route('/api/scores/recalculate', methods=['POST'])
def api_recalculate():
    conn = get_connection()
    scoring.score_all_listings(conn)
    conn.close()
    return jsonify({'recalculated': True})


SAVED_STATUSES = ('interested', 'visited', 'contacted', 'rejected')

_SAVED_QUERY = """
    SELECT l.*, sl.status, sl.notes, sl.saved_at, sl.updated_at AS tracker_updated,
      COALESCE(ls.score, 0) AS score,
      COALESCE(ls.score_breakdown, '{}') AS score_breakdown
    FROM saved_listings sl
    JOIN listings l ON l.hash_id = sl.listing_hash_id
    LEFT JOIN listing_scores ls ON ls.listing_hash_id = l.hash_id
      AND ls.profile_id = (SELECT id FROM profiles WHERE active=1 ORDER BY id LIMIT 1)
    ORDER BY sl.saved_at DESC
"""


def _saved_rows():
    conn = get_connection()
    rows = conn.execute(_SAVED_QUERY).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d['notes'] = json.loads(d.get('notes') or '[]')
        except (ValueError, TypeError):
            d['notes'] = []
        try:
            d['score_breakdown'] = json.loads(d.get('score_breakdown') or '{}')
        except (ValueError, TypeError):
            d['score_breakdown'] = {}
        result.append(d)
    return result


@app.route('/api/saved')
def api_saved():
    return jsonify(_saved_rows())


@app.route('/api/saved/<hash_id>/status', methods=['PATCH'])
def api_saved_status(hash_id):
    body = request.get_json(force=True) or {}
    status = body.get('status')
    if status not in SAVED_STATUSES:
        return jsonify({'error': 'invalid status'}), 400
    conn = get_connection()
    conn.execute(
        'UPDATE saved_listings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE listing_hash_id = ?',
        (status, hash_id),
    )
    conn.commit()
    conn.close()
    return jsonify({'status': status})


@app.route('/api/saved/<hash_id>/notes', methods=['POST'])
def api_saved_add_note(hash_id):
    body = request.get_json(force=True) or {}
    text = (body.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text is required'}), 400

    conn = get_connection()
    row = conn.execute(
        'SELECT notes FROM saved_listings WHERE listing_hash_id = ?', (hash_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    try:
        notes = json.loads(row['notes'] or '[]')
    except (ValueError, TypeError):
        notes = []
    notes.append({'text': text, 'timestamp': datetime.utcnow().isoformat()})
    conn.execute(
        'UPDATE saved_listings SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE listing_hash_id = ?',
        (json.dumps(notes), hash_id),
    )
    conn.commit()
    conn.close()
    return jsonify({'notes': notes})


@app.route('/api/saved/<hash_id>/notes/<int:note_index>', methods=['DELETE'])
def api_saved_delete_note(hash_id, note_index):
    conn = get_connection()
    row = conn.execute(
        'SELECT notes FROM saved_listings WHERE listing_hash_id = ?', (hash_id,)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'not found'}), 404
    try:
        notes = json.loads(row['notes'] or '[]')
    except (ValueError, TypeError):
        notes = []
    if 0 <= note_index < len(notes):
        notes.pop(note_index)
        conn.execute(
            'UPDATE saved_listings SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE listing_hash_id = ?',
            (json.dumps(notes), hash_id),
        )
        conn.commit()
    conn.close()
    return jsonify({'notes': notes})


@app.route('/api/saved/export')
def api_saved_export():
    rows = _saved_rows()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'Title', 'Locality', 'Price (CZK)', 'Type', 'Size (m²)', 'Score',
        'Status', 'Notes', 'URL', 'Source', 'Saved at',
    ])
    for r in rows:
        note_texts = ' | '.join(n.get('text', '') for n in r.get('notes', []))
        writer.writerow([
            r.get('title', ''), r.get('locality', ''), r.get('price', 0),
            r.get('listing_type', ''), r.get('size_m2', 0), r.get('score', 0),
            r.get('status', ''), note_texts, r.get('url', ''), r.get('source', ''),
            r.get('saved_at', ''),
        ])
    filename = f"flatradar-saved-{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        buf.getvalue().encode('utf-8'),
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8',
        },
    )


@app.route('/api/settings')
def api_get_settings():
    conn = get_connection()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    result = {row['key']: row['value'] for row in rows}
    for key in SETTING_DEFAULTS:
        result.setdefault(key, SETTING_DEFAULTS[key])
    result['smtp_password'] = ''
    return jsonify(result)


@app.route('/api/settings', methods=['POST'])
def api_post_settings():
    body = request.get_json(force=True) or {}
    for key, value in body.items():
        set_setting(key, '' if value is None else str(value))
    return jsonify({'saved': True})


@app.route('/api/notifications/test', methods=['POST'])
def api_notifications_test():
    ok, err = notifier.test_email()
    return jsonify({'success': ok, 'error': err})


@app.route('/api/notifications/log')
def api_notifications_log():
    offset = request.args.get('offset', 0, type=int)
    limit = request.args.get('limit', 50, type=int)
    type_filter = request.args.get('type', 'all')

    conn = get_connection()

    where = ''
    params = []
    if type_filter == 'failed':
        where = 'WHERE n.success = 0'
    elif type_filter in ('new_match', 'price_drop'):
        where = 'WHERE n.notification_type = ?'
        params.append(type_filter)

    rows = conn.execute(f'''
        SELECT
            n.id, n.notification_type, n.sent_at, n.success, n.error_message,
            l.title, l.locality, l.price, l.url, l.source,
            p.name as profile_name
        FROM notifications_log n
        LEFT JOIN listings l ON l.hash_id = n.listing_hash_id
        LEFT JOIN profiles p ON p.id = n.profile_id
        {where}
        ORDER BY n.sent_at DESC
        LIMIT ? OFFSET ?
    ''', params + [limit, offset]).fetchall()

    total = conn.execute(
        f'SELECT COUNT(*) FROM notifications_log n {where}', params
    ).fetchone()[0]

    conn.close()
    return jsonify({
        'items': [dict(r) for r in rows],
        'total': total,
        'offset': offset,
        'limit': limit,
    })


@app.route('/api/logs/runs')
def logs_runs():
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    conn = get_connection()
    rows = conn.execute(
        'SELECT * FROM scraper_runs ORDER BY started_at DESC LIMIT ? OFFSET ?',
        (limit, offset)
    ).fetchall()
    total = conn.execute(
        'SELECT COUNT(*) FROM scraper_runs'
    ).fetchone()[0]
    conn.close()
    return jsonify({
        'items': [dict(r) for r in rows],
        'total': total,
    })


@app.route('/api/logs/price-changes')
def logs_price_changes():
    conn = get_connection()
    rows = conn.execute('''
        SELECT
            l.hash_id, l.title, l.locality, l.url, l.source,
            l.price AS current_price,
            ph_prev.price AS previous_price,
            ph_prev.recorded_at AS changed_at
        FROM listings l
        JOIN price_history ph_curr ON ph_curr.listing_hash_id = l.hash_id
        JOIN price_history ph_prev ON ph_prev.listing_hash_id = l.hash_id
        WHERE ph_curr.recorded_at = (
            SELECT MAX(recorded_at) FROM price_history
            WHERE listing_hash_id = l.hash_id
        )
        AND ph_prev.recorded_at = (
            SELECT MAX(recorded_at) FROM price_history
            WHERE listing_hash_id = l.hash_id
            AND recorded_at < (
                SELECT MAX(recorded_at) FROM price_history
                WHERE listing_hash_id = l.hash_id
            )
        )
        AND ph_curr.price != ph_prev.price
        AND ph_prev.recorded_at >= datetime('now', '-7 days')
        ORDER BY ph_prev.recorded_at DESC
        LIMIT 50
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/logs/errors')
def logs_errors():
    import json
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, started_at, errors, status FROM scraper_runs "
        "WHERE status='error' OR errors != '[]' "
        "ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['errors'] = json.loads(d['errors'] or '[]')
        result.append(d)
    return jsonify(result)


@app.route('/api/insights/price-by-district')
def api_insights_price_by_district():
    listing_type = request.args.get('listing_type', default='rent', type=str)
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            TRIM(CASE
                WHEN locality LIKE '% - %' THEN SUBSTR(locality, 1, INSTR(locality, ' - ') - 1)
                WHEN locality LIKE '%, %'  THEN SUBSTR(locality, 1, INSTR(locality, ', ') - 1)
                ELSE locality
            END) AS district,
            ROUND(AVG(CAST(price AS FLOAT) / NULLIF(size_m2, 0))) AS avg_price_per_m2,
            COUNT(*) AS listing_count
        FROM listings
        WHERE price > 0
          AND size_m2 > 0
          AND active = 1
          AND listing_type = :listing_type
        GROUP BY district
        HAVING listing_count >= 3
        ORDER BY avg_price_per_m2 DESC
        LIMIT 20
        """,
        {'listing_type': listing_type},
    ).fetchall()
    conn.close()
    return jsonify({
        'labels': [r['district'] for r in rows],
        'values': [int(r['avg_price_per_m2'] or 0) for r in rows],
        'counts': [r['listing_count'] for r in rows],
        'listing_type': listing_type,
    })


@app.route('/api/insights/listings-by-day')
def api_insights_listings_by_day():
    from datetime import date, timedelta

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT date(first_seen_at) AS day, source, COUNT(*) AS count
        FROM listings
        WHERE first_seen_at >= date('now', '-14 days')
        GROUP BY day, source
        ORDER BY day ASC
        """
    ).fetchall()
    conn.close()

    counts = {(r['source'], r['day']): r['count'] for r in rows}
    labels = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    sources = ['sreality', 'bezrealitky', 'expats']
    datasets = {s: [counts.get((s, d), 0) for d in labels] for s in sources}
    return jsonify({'labels': labels, 'datasets': datasets})


@app.route('/api/insights/source-health')
def api_insights_source_health():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT source, COUNT(*) AS total_active, MAX(last_seen_at) AS last_active
        FROM listings
        WHERE active = 1
        GROUP BY source
        """
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/insights/market-pulse')
def api_insights_market_pulse():
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            CASE
                WHEN first_seen_at >= date('now', '-7 days') THEN 'this_week'
                ELSE 'last_week'
            END AS period,
            COUNT(*) AS new_listings,
            ROUND(AVG(price)) AS avg_price
        FROM listings
        WHERE first_seen_at >= date('now', '-14 days')
          AND price > 0
        GROUP BY period
        """
    ).fetchall()
    conn.close()

    data = {r['period']: r for r in rows}
    this_week = {
        'new_listings': data['this_week']['new_listings'] if 'this_week' in data else 0,
        'avg_price': int(data['this_week']['avg_price'] or 0) if 'this_week' in data else 0,
    }
    last_week = {
        'new_listings': data['last_week']['new_listings'] if 'last_week' in data else 0,
        'avg_price': int(data['last_week']['avg_price'] or 0) if 'last_week' in data else 0,
    }

    listing_delta = this_week['new_listings'] - last_week['new_listings']
    price_delta = this_week['avg_price'] - last_week['avg_price']
    listing_delta_pct = (
        round(listing_delta / last_week['new_listings'] * 100, 1)
        if last_week['new_listings'] else 0
    )
    price_delta_pct = (
        round(price_delta / last_week['avg_price'] * 100, 1)
        if last_week['avg_price'] else 0
    )

    return jsonify({
        'this_week': this_week,
        'last_week': last_week,
        'listing_delta': listing_delta,
        'listing_delta_pct': listing_delta_pct,
        'price_delta': price_delta,
        'price_delta_pct': price_delta_pct,
    })


@app.route('/api/insights/time-on-market')
def insights_time_on_market():
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            TRIM(CASE
                WHEN locality LIKE '% - %' THEN SUBSTR(locality, 1, INSTR(locality, ' - ') - 1)
                WHEN locality LIKE '%, %'  THEN SUBSTR(locality, 1, INSTR(locality, ', ') - 1)
                ELSE locality
            END) AS district,
            ROUND(AVG(julianday(last_seen_at) - julianday(first_seen_at)), 1) AS avg_days,
            COUNT(*) AS count
        FROM listings
        WHERE active = 0
          AND last_seen_at != first_seen_at
          AND julianday(last_seen_at) - julianday(first_seen_at) > 0
        GROUP BY district
        HAVING count >= 3
        ORDER BY avg_days ASC
        LIMIT 15
    """).fetchall()
    conn.close()
    return jsonify({
        'labels': [r['district'] for r in rows],
        'values': [r['avg_days'] for r in rows],
        'counts': [r['count'] for r in rows],
    })


@app.route('/api/insights/day-of-week')
def insights_day_of_week():
    conn = get_connection()
    rows = conn.execute("""
        SELECT strftime('%w', first_seen_at) AS dow, COUNT(*) AS count
        FROM listings
        WHERE first_seen_at >= date('now', '-30 days')
        GROUP BY dow ORDER BY dow
    """).fetchall()
    conn.close()
    labels = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    counts = {r['dow']: r['count'] for r in rows}
    return jsonify({
        'labels': labels,
        'values': [counts.get(str(i), 0) for i in range(7)],
    })


@app.route('/api/insights/price-distribution')
def insights_price_distribution():
    listing_type = request.args.get('listing_type', 'rent')
    if listing_type == 'rent':
        bands = [
            ('Under 10k', 0, 10000),
            ('10–15k', 10000, 15000),
            ('15–20k', 15000, 20000),
            ('20–25k', 20000, 25000),
            ('25–30k', 25000, 30000),
            ('30–40k', 30000, 40000),
            ('Over 40k', 40000, 999999999),
        ]
    else:
        bands = [
            ('Under 1M', 0, 1000000),
            ('1–2M', 1000000, 2000000),
            ('2–3M', 2000000, 3000000),
            ('3–5M', 3000000, 5000000),
            ('5–10M', 5000000, 10000000),
            ('Over 10M', 10000000, 999999999),
        ]
    conn = get_connection()
    values = []
    for label, lo, hi in bands:
        count = conn.execute(
            'SELECT COUNT(*) as c FROM listings WHERE price > ? AND price <= ? AND listing_type = ? AND active = 1',
            (lo, hi, listing_type)
        ).fetchone()['c']
        values.append(count)
    conn.close()
    return jsonify({
        'labels': [b[0] for b in bands],
        'values': values,
        'listing_type': listing_type,
    })


@app.route('/api/insights/profile-match-rate')
def insights_profile_match_rate():
    conn = get_connection()
    total = conn.execute('SELECT COUNT(*) as c FROM listings WHERE active=1').fetchone()['c']
    profiles = conn.execute('SELECT id, name, score_threshold FROM profiles WHERE active=1').fetchall()
    result = []
    for p in profiles:
        matching = conn.execute(
            'SELECT COUNT(*) as c FROM listing_scores WHERE profile_id = ? AND score >= ?',
            (p['id'], p['score_threshold'])
        ).fetchone()['c']
        result.append({
            'profile': p['name'],
            'matching': matching,
            'total': total,
            'pct': round(100 * matching / total, 1) if total else 0,
        })
    conn.close()
    return jsonify(result)


@app.route('/api/supermarkets/refresh', methods=['POST'])
def refresh_supermarkets():
    t = threading.Thread(target=sm.refresh_all, daemon=True)
    t.start()
    return jsonify({'started': True})


@app.route('/api/supermarkets/chains')
def get_supermarket_chains():
    stats = sm.get_chain_stats()
    return jsonify({
        'chains': stats,
        'needs_refresh': sm.needs_refresh(),
        'available': [c for c in config.SUPERMARKET_CHAINS.keys()],
    })


@app.route('/api/listings/<hash_id>/supermarkets')
def listing_supermarkets(hash_id):
    chains_param = request.args.get('chains', '')
    chains = [c.strip() for c in chains_param.split(',') if c.strip()]
    if not chains:
        return jsonify([])
    conn = get_connection()
    listing = conn.execute('SELECT lat, lng FROM listings WHERE hash_id = ?', (hash_id,)).fetchone()
    conn.close()
    if not listing or listing['lat'] is None:
        return jsonify([])
    result = sm.nearest_by_chain(listing['lat'], listing['lng'], chains)
    return jsonify(result)


@app.route('/api/supermarkets/near')
def supermarkets_near():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
        km = float(request.args.get('km', 3))
    except (TypeError, ValueError):
        return jsonify([])
    conn = get_connection()
    locations = conn.execute('SELECT chain, lat, lng FROM supermarkets').fetchall()
    conn.close()
    from supermarkets import haversine_km
    nearby_chains = set()
    for loc in locations:
        if haversine_km(lat, lng, loc['lat'], loc['lng']) <= km:
            nearby_chains.add(loc['chain'])
    return jsonify(sorted(nearby_chains))


@app.route('/api/supermarkets/fetch-area')
def fetch_area_supermarkets():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
        km = float(request.args.get('km', 3.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lng required'}), 400
    from supermarkets import fetch_area
    results = fetch_area(lat, lng, km)
    return jsonify(results)


@app.route('/api/parks/fetch-area')
def fetch_parks_area_route():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
        km = float(request.args.get('km', 2.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'lat, lng required'}), 400
    from parks import fetch_parks_area
    results = fetch_parks_area(lat, lng, km)
    return jsonify(results[:8])


@app.route('/api/listings/<hash_id>/parks')
def listing_parks(hash_id):
    km = float(request.args.get('km', 1.0))
    conn = get_connection()
    listing = conn.execute(
        'SELECT lat, lng FROM listings WHERE hash_id = ?', (hash_id,)
    ).fetchone()
    conn.close()
    if not listing or listing['lat'] is None:
        return jsonify([])
    from parks import nearest_parks
    return jsonify(nearest_parks(listing['lat'], listing['lng'], km))


@app.route('/api/geocode')
def geocode_address():
    address = request.args.get('address', '').strip()
    if not address:
        return jsonify({'error': 'address required'}), 400
    from commute import geocode
    result = geocode(address)
    if result:
        return jsonify({'lat': result[0], 'lng': result[1], 'found': True})
    return jsonify({'found': False})


@app.route('/api/listings/<hash_id>/commute')
def listing_commute(hash_id):
    to_lat = request.args.get('to_lat', type=float)
    to_lng = request.args.get('to_lng', type=float)
    if not to_lat or not to_lng:
        return jsonify({'error': 'to_lat, to_lng required'}), 400
    conn = get_connection()
    listing = conn.execute(
        'SELECT lat, lng FROM listings WHERE hash_id = ?', (hash_id,)
    ).fetchone()
    conn.close()
    if not listing or listing['lat'] is None:
        return jsonify({'available': False})
    from commute import walk_route_minutes, haversine_km
    dist = haversine_km(listing['lat'], listing['lng'], to_lat, to_lng)
    minutes = walk_route_minutes(listing['lat'], listing['lng'], to_lat, to_lng)
    return jsonify({
        'available': True,
        'distance_km': round(dist, 2),
        'walk_minutes': minutes,
    })


@app.route('/api/db/restore-backup', methods=['POST'])
def restore_backup():
    backup = config.DATABASE_PATH + '.backup'
    if not os.path.exists(backup):
        return jsonify({'error': 'No backup found'}), 404
    import shutil
    shutil.copy2(backup, config.DATABASE_PATH)
    database.init_db()
    return jsonify({'restored': True, 'backup': backup})


if __name__ == '__main__':
    init_db()
    sched.start_scheduler()
    # Warm up sreality session in background so it's ready before first image request
    threading.Thread(target=sreality_session.get,
        args=('https://www.sreality.cz/',), daemon=True).start()
    app.run(debug=True, port=5001, use_reloader=False)
