import math
import requests

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'
OSRM_URL = 'https://router.project-osrm.org/route/v1/foot'
HEADERS = {'User-Agent': 'FlatRadar/1.0 (apartment search tool)'}

def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlng/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def walk_minutes_estimate(dist_km: float) -> int:
    """Estimate walking time at 4.5 km/h."""
    return max(1, round((dist_km / 4.5) * 60))

def geocode(address: str) -> tuple | None:
    """
    Geocode an address using Nominatim.
    Returns (lat, lng) or None on failure.
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={'q': address, 'format': 'json', 'limit': 1,
                    'countrycodes': 'cz'},
            headers=HEADERS,
            timeout=10
        )
        results = resp.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
        # Try without country restriction
        resp = requests.get(
            NOMINATIM_URL,
            params={'q': address, 'format': 'json', 'limit': 1},
            headers=HEADERS,
            timeout=10
        )
        results = resp.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    except Exception as e:
        print(f'Geocoding failed: {e}')
    return None

def walk_route_minutes(from_lat, from_lng, to_lat, to_lng) -> int | None:
    """
    Get actual walking route time from OSRM public API.
    Returns minutes or None on failure.
    """
    try:
        url = f'{OSRM_URL}/{from_lng},{from_lat};{to_lng},{to_lat}'
        resp = requests.get(
            url,
            params={'overview': 'false'},
            headers=HEADERS,
            timeout=8
        )
        data = resp.json()
        if data.get('code') == 'Ok' and data.get('routes'):
            seconds = data['routes'][0]['duration']
            return max(1, round(seconds / 60))
    except Exception as e:
        print(f'OSRM route failed: {e}')
    return None
