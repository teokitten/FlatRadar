import math
import requests
import config
from database import get_connection

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def fetch_parks_area(lat: float, lng: float, km: float = 2.0) -> list[dict]:
    """
    Fetch parks within km radius of lat/lng from Overpass.
    Checks the DB cache first; only queries Overpass (and updates the
    cache) when the cache has nothing within range.
    Returns list of {name, distance_km} sorted by distance.
    """
    # Check cache first
    cached = nearest_parks(lat, lng, km)
    if cached:
        return cached

    # Cache empty – fetch from Overpass
    lat_d = km / 111.0
    lng_d = km / (111.0 * math.cos(math.radians(lat)))
    s, n, w, e = lat - lat_d, lat + lat_d, lng - lng_d, lng + lng_d

    query = f"""
[out:json][timeout:20];
(
  way["leisure"="park"]({s},{w},{n},{e});
  way["leisure"="garden"]({s},{w},{n},{e});
  way["landuse"="recreation_ground"]({s},{w},{n},{e});
  node["leisure"="park"]({s},{w},{n},{e});
);
out center;
"""
    try:
        resp = requests.post(
            config.OVERPASS_URL,
            data={'data': query},
            timeout=25,
            headers={'User-Agent': 'FlatRadar/1.0'}
        )
        if resp.status_code != 200:
            return nearest_parks(lat, lng, km)
        elements = resp.json().get('elements', [])
    except Exception as e:
        print(f'Parks fetch failed: {e}')
        return nearest_parks(lat, lng, km)  # return cache on error

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
        name = tags.get('name', '')
        osm_id = str(el.get('id', ''))
        dist = haversine_km(lat, lng, elat, elng)
        if dist > km:
            continue

        try:
            conn.execute(
                'INSERT OR IGNORE INTO parks (osm_id, name, lat, lng) '
                'VALUES (?, ?, ?, ?)',
                (osm_id, name, elat, elng)
            )
        except Exception:
            pass

    conn.commit()
    conn.close()

    # After inserting to DB, return from cache
    return nearest_parks(lat, lng, km)

def nearest_parks(lat: float, lng: float, km: float = 1.0, limit: int = 8) -> list[dict]:
    """Return nearest parks from cache within km."""
    if lat is None or lng is None:
        return []
    conn = get_connection()
    rows = conn.execute('SELECT name, lat, lng FROM parks').fetchall()
    conn.close()
    results = []
    for r in rows:
        dist = haversine_km(lat, lng, r['lat'], r['lng'])
        if dist <= km:
            results.append({
                'name': r['name'] or '',
                'distance_km': round(dist, 2),
            })
    return sorted(results, key=lambda x: x['distance_km'])[:limit]
