import json
import re
from datetime import datetime, timezone

from supermarkets import nearest_by_chain


def _recency_score(first_seen_at_str):
    """Returns 0-10 based on listing age. Newer = higher."""
    try:
        first_seen = datetime.fromisoformat(first_seen_at_str)
        if first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - first_seen).total_seconds() / 3600
        if age_hours < 6:
            return 10
        elif age_hours < 24:
            return 8
        elif age_hours < 72:
            return 5
        elif age_hours < 168:
            return 2
        else:
            return 0
    except Exception:
        return 5


def _extract_features(listing):
    """
    Parse room_type and boolean features from listing title and raw_data.
    Returns a dict of extracted features.
    """
    title = listing.get('title', '') or ''
    raw = listing.get('raw_data', '') or ''

    # Room type from title - matches patterns like 2+kk, 3+1, 4+kk, garsoniéra
    room_match = re.search(r'(\d+\+(?:kk|\d+))', title, re.IGNORECASE)
    if room_match:
        room_type = room_match.group(1).lower()
    elif re.search(r'gars', title, re.IGNORECASE):
        room_type = 'studio'
    else:
        room_type = None

    # Parse labelsAll from raw_data (sreality)
    labels = []
    try:
        raw_data = json.loads(raw) if isinstance(raw, str) else raw
        labels_all = raw_data.get('labelsAll', [])
        for group in labels_all:
            if isinstance(group, list):
                labels.extend([str(l).lower() for l in group])
            elif isinstance(group, str):
                labels.append(group.lower())
    except Exception:
        pass

    # Bezrealitky equipped field
    try:
        raw_data = json.loads(raw) if isinstance(raw, str) else {}
        equipped = str(raw_data.get('equipped', '') or '').lower()
    except Exception:
        equipped = ''

    def has(*keywords):
        return any(k in ' '.join(labels) for k in keywords)

    # Furnished status
    if 'zařízen' in ' '.join(labels) or 'furnished' in ' '.join(labels) or equipped in ('vybavený', 'vybaveno', 'furnished'):
        furnished = 'furnished'
    elif 'částečně' in ' '.join(labels) or 'partial' in ' '.join(labels) or 'partially' in ' '.join(labels):
        furnished = 'partial'
    elif 'nezařízen' in ' '.join(labels) or 'unfurnished' in ' '.join(labels) or equipped in ('nevybavený', 'nevybaveno'):
        furnished = 'unfurnished'
    else:
        furnished = 'unknown'

    # Building age
    if has('novostavba', 'new build', 'newly built'):
        building_age = 'new'
    elif has('rekonstruovaný', 'rekonstrukce', 'renovated', 'renovovaný'):
        building_age = 'renovated'
    elif has('moderní', 'modern'):
        building_age = 'modern'
    else:
        building_age = 'unknown'

    return {
        'room_type': room_type,
        'balcony': has('balkon', 'lodžie', 'balcony', 'loggia'),
        'terrace': has('terasa', 'terrace', 'patio'),
        'parking': has('garáž', 'garážové stání', 'parkovací', 'parking', 'garage'),
        'cellar': has('sklep', 'cellar', 'storage'),
        'bathtub': has('vana', 'bathtub', 'bath'),
        'dishwasher': has('myčka', 'dishwasher'),
        'furnished': furnished,
        'building_age': building_age,
    }


def _parse_multi(val, default='any'):
    if not val:
        return []
    val = str(val).strip()
    if val.startswith('['):
        try:
            return [v for v in json.loads(val) if v and v != 'any']
        except Exception:
            return []
    if val == 'any':
        return []
    return [val]


def score_listing(listing, profile):
    chains = json.loads(profile.get('supermarket_chains', '[]') or '[]')
    max_km = float(profile.get('supermarket_max_km') or 0)
    use_proximity = bool(chains and max_km > 0)

    req_rooms = json.loads(profile.get('room_types', '[]') or '[]')
    req_balcony = int(profile.get('feature_balcony', 0) or 0)
    req_terrace = int(profile.get('feature_terrace', 0) or 0)
    req_parking = int(profile.get('feature_parking', 0) or 0)
    req_cellar = int(profile.get('feature_cellar', 0) or 0)
    req_bathtub = int(profile.get('feature_bathtub', 0) or 0)
    req_dishwasher = int(profile.get('feature_dishwasher', 0) or 0)
    req_furnished = profile.get('feature_furnished', 'any') or 'any'
    req_building_age = profile.get('feature_building_age', 'any') or 'any'

    has_feature_prefs = any([
        req_rooms, req_balcony, req_terrace, req_parking,
        req_cellar, req_bathtub, req_dishwasher,
        req_furnished != 'any', req_building_age != 'any'
    ])

    if has_feature_prefs:
        w_price, w_size, w_loc, w_type, w_recency = 25, 18, 18, 8, 8
    elif use_proximity:
        w_price, w_size, w_loc, w_type, w_recency = 25, 20, 20, 10, 10
    else:
        w_price, w_size, w_loc, w_type, w_recency = 30, 25, 25, 10, 10

    def half(x):
        return round(x * 0.5)

    price_max = profile['price_max']
    price_min = profile['price_min']
    price = listing['price']
    if price_max == 0:
        p = w_price
    elif price == 0:
        p = half(w_price)
    elif price_min <= price <= price_max:
        p = w_price
    elif price <= price_max * 1.10:
        p = half(w_price)
    else:
        p = 0

    size_min = profile['size_min']
    size_max = profile['size_max']
    size = listing['size_m2']
    if size_min == 0 and size_max == 0:
        s = w_size
    elif size == 0:
        s = half(w_size)
    elif (size_min == 0 or size >= size_min) and (size_max == 0 or size <= size_max):
        s = w_size
    elif size >= size_min * 0.9:
        s = half(w_size)
    else:
        s = 0

    districts = json.loads(profile.get('districts', '[]') or '[]')
    districts = [d.strip() for d in districts if d and d.strip()]
    locality = listing.get('locality', '') or ''
    if not districts:
        l = w_loc
    elif any(d.lower() in locality.lower() for d in districts):
        l = w_loc
    else:
        l = 0

    pref = profile['listing_type']
    if pref == 'both' or pref == listing['listing_type']:
        t = w_type
    else:
        t = 0

    r = round(_recency_score(listing.get('first_seen_at', '')) * w_recency / 10)

    breakdown = {'price': p, 'size': s, 'location': l, 'type': t, 'recency': r}

    if use_proximity:
        w_proximity = 13 if has_feature_prefs else 15
        lat = listing.get('lat')
        lng = listing.get('lng')
        if lat is None or lng is None:
            breakdown['proximity'] = round(w_proximity * 7 / 15)  # neutral: no GPS available
        else:
            nearest = nearest_by_chain(lat, lng, chains)
            if not nearest:
                breakdown['proximity'] = round(w_proximity * 7 / 15)  # no data yet
            else:
                dist = nearest[0]['distance_km']
                if dist <= max_km:
                    breakdown['proximity'] = w_proximity
                elif dist <= max_km * 1.5:
                    breakdown['proximity'] = round(w_proximity * 8 / 15)
                elif dist <= max_km * 2:
                    breakdown['proximity'] = round(w_proximity * 3 / 15)
                else:
                    breakdown['proximity'] = 0
    else:
        breakdown['proximity'] = None

    # Park proximity
    park_max_km = float(profile.get('park_max_km') or 0)
    if park_max_km > 0:
        # Redistribute: take 5 pts from recency
        breakdown['recency'] = max(0, breakdown.get('recency', 10) - 5)
        lat = listing.get('lat')
        lng = listing.get('lng')
        if lat is None or lng is None:
            breakdown['parks'] = 3  # neutral
        else:
            from parks import nearest_parks
            nearby = nearest_parks(lat, lng, park_max_km)
            if nearby:
                dist = nearby[0]['distance_km']
                if dist <= park_max_km * 0.5:
                    breakdown['parks'] = 10
                elif dist <= park_max_km:
                    breakdown['parks'] = 6
                else:
                    breakdown['parks'] = 0
            else:
                breakdown['parks'] = 0
    else:
        breakdown['parks'] = None

    # Commute distance
    wp_lat = profile.get('workplace_lat')
    wp_lng = profile.get('workplace_lng')

    if wp_lat and wp_lng:
        from commute import haversine_km
        lat = listing.get('lat')
        lng = listing.get('lng')
        if lat is None or lng is None:
            breakdown['commute'] = 5  # neutral
        else:
            dist = haversine_km(lat, lng, float(wp_lat), float(wp_lng))
            if dist <= 1.0:
                breakdown['commute'] = 10
            elif dist <= 2.0:
                breakdown['commute'] = 8
            elif dist <= 3.5:
                breakdown['commute'] = 5
            elif dist <= 6.0:
                breakdown['commute'] = 2
            else:
                breakdown['commute'] = 0
        # Redistribute: take 5 pts from size
        existing_size = breakdown.get('size', 25)
        breakdown['size'] = max(0, existing_size - 5)
    else:
        breakdown['commute'] = None

    if has_feature_prefs:
        feats = _extract_features(listing)
        feature_pts = 0
        feature_total = 0

        bool_checks = [
            (req_balcony, feats.get('balcony')),
            (req_terrace, feats.get('terrace')),
            (req_parking, feats.get('parking')),
            (req_cellar, feats.get('cellar')),
            (req_bathtub, feats.get('bathtub')),
            (req_dishwasher, feats.get('dishwasher')),
        ]
        active_bool = [(rq, v) for rq, v in bool_checks if rq]
        for _, has_it in active_bool:
            feature_total += 1
            if has_it:
                feature_pts += 1

        req_furnished_list = _parse_multi(
            profile.get('feature_furnished_v2') or profile.get('feature_furnished', '[]')
        )
        if req_furnished_list:
            feature_total += 1
            f = feats.get('furnished', 'unknown')
            if f in req_furnished_list:
                feature_pts += 1
            elif f == 'unknown':
                feature_pts += 0.5

        req_building_age_list = _parse_multi(
            profile.get('feature_building_age_v2') or profile.get('feature_building_age', '[]')
        )
        if req_building_age_list:
            feature_total += 1
            a = feats.get('building_age', 'unknown')
            if a in req_building_age_list:
                feature_pts += 1
            elif a == 'unknown':
                feature_pts += 0.5

        breakdown['features'] = round(
            10 * (feature_pts / feature_total) if feature_total else 10
        )
    else:
        breakdown['features'] = None

    total = min(sum(v for v in breakdown.values() if v is not None), 100)
    return total, breakdown


def score_all_listings(conn):
    listings = conn.execute('SELECT * FROM listings WHERE active = 1').fetchall()
    profiles = conn.execute('SELECT * FROM profiles WHERE active = 1').fetchall()

    listing_dicts = []
    for listing in listings:
        ld = dict(listing)
        feats = _extract_features(ld)
        if feats['room_type'] and not ld.get('room_type'):
            conn.execute(
                'UPDATE listings SET room_type = ?, features_parsed = ? WHERE hash_id = ?',
                (feats['room_type'], json.dumps(feats), ld['hash_id'])
            )
            ld['room_type'] = feats['room_type']
            ld['features_parsed'] = json.dumps(feats)
        listing_dicts.append(ld)

    rows = []
    for ld in listing_dicts:
        for profile in profiles:
            pd = dict(profile)
            total, breakdown = score_listing(ld, pd)
            rows.append((ld['hash_id'], pd['id'], total, json.dumps(breakdown)))

    for hash_id, profile_id, score, breakdown in rows:
        conn.execute(
            'INSERT OR REPLACE INTO listing_scores '
            '(listing_hash_id, profile_id, score, score_breakdown, calculated_at) '
            'VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)',
            (hash_id, profile_id, score, breakdown),
        )
    conn.commit()
