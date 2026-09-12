import json
import math
import time
import requests
from datetime import datetime, timedelta, timezone
from database import get_connection
import config


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _fetch_chain_from_osm(chain_name):
    brand = config.SUPERMARKET_CHAINS[chain_name]['brand']
    query = f"""
[out:json][timeout:{config.OVERPASS_TIMEOUT}];
area["ISO3166-1"="CZ"]->.cz;
(
  nwr["brand"="{brand}"](area.cz);
  nwr["name"="{brand}"](area.cz);
);
out center;
"""
    try:
        resp = requests.post(
            config.OVERPASS_URL,
            data={'data': query},
            timeout=config.OVERPASS_TIMEOUT + 5,
            headers={'User-Agent': 'FlatRadar/1.0 (apartment search tool)'}
        )
        if resp.status_code != 200:
            print(f'Overpass error for {chain_name}: {resp.status_code}')
            return []
        elements = resp.json().get('elements', [])
        results = []
        for el in elements:
            if el['type'] == 'node':
                lat, lng = el.get('lat'), el.get('lon')
            else:
                center = el.get('center', {})
                lat, lng = center.get('lat'), center.get('lon')
            if not lat or not lng:
                continue
            tags = el.get('tags', {})
            results.append({
                'chain': chain_name,
                'osm_id': str(el.get('id', '')),
                'lat': lat,
                'lng': lng,
                'name': tags.get('name', chain_name),
                'address': tags.get('addr:street', ''),
                'city': tags.get('addr:city', ''),
            })
        return results
    except Exception as e:
        print(f'Overpass fetch failed for {chain_name}: {e}')
        return []


def _detect_chain(brand_str):
    s = (brand_str or '').lower()
    for key, chain in {
        'globus': 'Globus',
        'kaufland': 'Kaufland',
        'albert': 'Albert',
        'billa': 'Billa',
        'lidl': 'Lidl',
        'penny': 'Penny Market',
        'tesco': 'Tesco',
        'rohlik': 'Rohlik',
        'rohlík': 'Rohlik',
        'coop': 'Coop',
        'žabka': 'Žabka',
        'zabka': 'Žabka',
    }.items():
        if key in s:
            return chain
    return None


def _nearest_from_cache(lat: float, lng: float, km: float) -> list[dict]:
    """Return nearest supermarket per chain from DB cache."""
    conn = get_connection()
    rows = conn.execute('SELECT chain, name, lat, lng FROM supermarkets').fetchall()
    conn.close()
    best = {}
    for loc in rows:
        dist = haversine_km(lat, lng, loc['lat'], loc['lng'])
        if dist <= km:
            chain = loc['chain']
            if chain not in best or dist < best[chain]['distance_km']:
                best[chain] = {
                    'chain': chain,
                    'name': loc['name'],
                    'distance_km': round(dist, 2),
                }
    return sorted(best.values(), key=lambda x: x['distance_km'])


def fetch_area(lat, lng, km=3.0):
    """
    Fetch all known supermarket chains within km radius of lat/lng.
    Checks the DB cache first; only queries Overpass (and updates the
    cache) when the cache has nothing within range. Detects chains by
    brand/name tag, saves new locations to the supermarkets table, and
    returns one entry per chain (the nearest location), sorted by distance.
    """
    # Check cache first
    cached = _nearest_from_cache(lat, lng, km)
    if cached:
        return cached

    # Cache empty – fetch from Overpass
    lat_d = km / 111.0
    lng_d = km / (111.0 * math.cos(math.radians(lat)))
    s, n, w, e = lat - lat_d, lat + lat_d, lng - lng_d, lng + lng_d

    query = f"""
[out:json][timeout:20];
(
  nwr["shop"~"supermarket|hypermarket|discount|convenience"]({s},{w},{n},{e});
);
out center;
"""
    try:
        resp = requests.post(
            config.OVERPASS_URL,
            data={'data': query},
            timeout=25,
            headers={'User-Agent': 'FlatRadar/1.0 (apartment search)'}
        )
        if resp.status_code != 200:
            print(f'Overpass area fetch: HTTP {resp.status_code}')
            return _nearest_from_cache(lat, lng, km)
        elements = resp.json().get('elements', [])
    except Exception as e:
        print(f'Overpass area fetch failed: {e}')
        cached = _nearest_from_cache(lat, lng, km)
        return cached  # return whatever is in cache, even if empty

    conn = get_connection()
    for el in elements:
        if el['type'] == 'node':
            elat, elng = el.get('lat'), el.get('lon')
        else:
            c = el.get('center', {})
            elat, elng = c.get('lat'), c.get('lon')
        if not elat or not elng:
            continue

        tags = el.get('tags', {})
        brand = tags.get('brand') or tags.get('name') or ''
        chain = _detect_chain(brand)
        if not chain:
            continue

        dist = haversine_km(lat, lng, elat, elng)
        if dist > km:
            continue

        osm_id = str(el.get('id', ''))
        try:
            conn.execute(
                'INSERT OR IGNORE INTO supermarkets (chain, osm_id, lat, lng, name, address, city) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (chain, osm_id, elat, elng,
                 tags.get('name', chain),
                 tags.get('addr:street', ''),
                 tags.get('addr:city', ''))
            )
        except Exception:
            pass

    conn.commit()
    conn.close()

    # On success, return from fresh cache
    fresh = _nearest_from_cache(lat, lng, km)
    return fresh if fresh else []


def needs_refresh():
    conn = get_connection()
    row = conn.execute(
        'SELECT MAX(fetched_at) AS last FROM supermarkets'
    ).fetchone()
    conn.close()
    if not row or not row['last']:
        return True
    try:
        last = datetime.fromisoformat(row['last'])
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last > timedelta(days=config.SUPERMARKET_CACHE_DAYS)
    except Exception:
        return True


def refresh_all():
    results = {}
    all_locations = []
    for chain_name in config.SUPERMARKET_CHAINS:
        print(f'Fetching {chain_name}...')
        locations = _fetch_chain_from_osm(chain_name)
        results[chain_name] = len(locations)
        all_locations.extend(locations)
        time.sleep(2)

    conn = get_connection()
    try:
        conn.execute('DELETE FROM supermarkets')
        for loc in all_locations:
            conn.execute(
                '''INSERT INTO supermarkets (chain, osm_id, lat, lng, name, address, city)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (loc['chain'], loc['osm_id'], loc['lat'], loc['lng'],
                 loc['name'], loc['address'], loc['city'])
            )
        conn.commit()
        return {'chains': results, 'total': len(all_locations), 'error': None}
    except Exception as e:
        return {'chains': results, 'total': 0, 'error': str(e)}
    finally:
        conn.close()


def nearest_by_chain(lat, lng, chains):
    if lat is None or lng is None:
        return []
    if not chains:
        return []
    conn = get_connection()
    all_locations = conn.execute(
        f'SELECT * FROM supermarkets WHERE chain IN ({",".join("?" * len(chains))})',
        chains
    ).fetchall()
    conn.close()

    best = {}
    for loc in all_locations:
        chain = loc['chain']
        dist = haversine_km(lat, lng, loc['lat'], loc['lng'])
        if chain not in best or dist < best[chain]['distance_km']:
            best[chain] = {
                'chain': chain,
                'name': loc['name'],
                'city': loc['city'],
                'distance_km': round(dist, 2),
            }
    return sorted(best.values(), key=lambda x: x['distance_km'])


def get_chain_stats():
    conn = get_connection()
    rows = conn.execute(
        'SELECT chain, COUNT(*) as count FROM supermarkets GROUP BY chain ORDER BY chain'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
