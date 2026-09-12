import json
import os
import re
import time

import requests
import requests as _req

import config

_AREA_RE = re.compile(r'(\d+)\s*m')

_session = _req.Session()
_session.headers.update(config.SREALITY_HEADERS)


def download_image(url: str, hash_id: str, session=None) -> str:
    """
    Download image to local cache. Returns local URL path or original URL on failure.
    Uses the provided session (with sreality.cz cookies) for the request.
    """
    if not url:
        return url
    local_path = os.path.join(config.IMAGE_CACHE_DIR, f'{hash_id}.jpg')
    if os.path.exists(local_path):
        return config.IMAGE_CACHE_URL + f'{hash_id}.jpg'
    try:
        s = session or requests
        resp = s.get(url, headers={
            'Referer': 'https://www.sreality.cz/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        }, timeout=8)
        if resp.status_code == 200 and resp.content:
            os.makedirs(config.IMAGE_CACHE_DIR, exist_ok=True)
            with open(local_path, 'wb') as f:
                f.write(resp.content)
            return config.IMAGE_CACHE_URL + f'{hash_id}.jpg'
    except Exception as e:
        print(f'Image download failed for {hash_id}: {e}')
    return url  # Fall back to original URL


def _extract_price(estate):
    value = int(estate.get('price_czk') or 0)
    if value == 0:
        value = int(estate.get('price') or 0)
    return value


def _extract_size(estate):
    match = _AREA_RE.search(estate.get('advert_name', '') or '')
    if match:
        return int(match.group(1))
    price_czk = estate.get('price_czk') or 0
    price_m2 = estate.get('price_czk_m2') or 0
    if price_czk and price_m2:
        return int(round(price_czk / price_m2))
    return 0


def _extract_image(estate):
    images = estate.get('advert_images') or []
    if not images:
        return ''
    href = images[0]
    if href.startswith('//'):
        href = 'https:' + href
    return href


def _extract_locality(estate):
    loc = estate.get('locality') or {}
    parts = []
    for key in ('street', 'citypart', 'city', 'district'):
        val = loc.get(key)
        if val and val not in parts:
            parts.append(val)
    return ', '.join(parts)


def _extract_lat(result):
    loc = result.get('locality') or {}
    if isinstance(loc, dict) and loc.get('gps_lat') is not None:
        return loc['gps_lat']
    gps = result.get('gps') or result.get('_source', {}).get('gps') or {}
    if isinstance(gps, dict):
        return gps.get('lat') or gps.get('latitude')
    return None


def _extract_lng(result):
    loc = result.get('locality') or {}
    if isinstance(loc, dict) and loc.get('gps_lon') is not None:
        return loc['gps_lon']
    gps = result.get('gps') or result.get('_source', {}).get('gps') or {}
    if isinstance(gps, dict):
        return gps.get('lng') or gps.get('lon') or gps.get('longitude')
    return None


def _build_url(estate, listing_type, property_type):
    type_slug = config.SREALITY_TYPE_SLUG[config.SREALITY_CATEGORY_TYPE[listing_type]]
    main_slug = config.SREALITY_MAIN_SLUG[config.SREALITY_CATEGORY_MAIN[property_type]]
    hash_id = str(estate.get('hash_id', ''))
    if not hash_id:
        return ''
    sub_slug = (estate.get('category_sub_cb') or {}).get('name', '') or 'x'
    loc = estate.get('locality') or {}
    loc_parts = [loc.get('city_seo_name'), loc.get('citypart_seo_name'), loc.get('street_seo_name')]
    loc_slug = '-'.join([p for p in loc_parts if p]) or 'x'
    return f'https://www.sreality.cz/detail/{type_slug}/{main_slug}/{sub_slug}/{loc_slug}/{hash_id}'


def fetch_listings(listing_type, property_type):
    category_type = config.SREALITY_CATEGORY_TYPE[listing_type]
    category_main = config.SREALITY_CATEGORY_MAIN[property_type]
    results = []

    for page in range(1, config.SREALITY_MAX_PAGES + 1):
        offset = (page - 1) * config.SREALITY_PER_PAGE
        params = {
            'category_main_cb': category_main,
            'category_type_cb': category_type,
            'per_page': config.SREALITY_PER_PAGE,
            'limit': config.SREALITY_PER_PAGE,
            'offset': offset,
            'page': page,
            'lang': config.SREALITY_LANG,
        }
        try:
            response = _session.get(
                config.SREALITY_API_BASE,
                params=params,
                headers=config.SREALITY_HEADERS,
                timeout=15,
            )
        except Exception as e:
            print(f'Sreality fetch error page {page}: {e}')
            break

        if response.status_code != 200:
            print(f'Sreality status {response.status_code} page {page}')
            break

        try:
            data = response.json()
        except Exception as e:
            print(f'Sreality fetch error page {page}: {e}')
            break

        estates = data.get('results')
        if estates is None:
            break
        if not estates:
            break

        for estate in estates:
            hash_id = str(estate.get('hash_id', ''))
            if not hash_id:
                continue
            results.append({
                'hash_id': hash_id,
                'source': 'sreality',
                'title': estate.get('advert_name', ''),
                'locality': _extract_locality(estate),
                'price': _extract_price(estate),
                'price_currency': 'CZK',
                'listing_type': listing_type,
                'property_type': property_type,
                'size_m2': _extract_size(estate),
                'floor_number': int(estate.get('floor_number') or 0),
                'image_url': _extract_image(estate),
                'url': _build_url(estate, listing_type, property_type),
                'lat': _extract_lat(estate),
                'lng': _extract_lng(estate),
                'raw_data': json.dumps(estate),
            })

        total = data.get('pagination', {}).get('total', 0)
        if offset + len(estates) >= total:
            break

        if page < config.SREALITY_MAX_PAGES:
            time.sleep(config.SREALITY_DELAY_SECONDS)

    return results


def run_all_sreality():
    combos = [('rent', 'flat'), ('buy', 'flat'), ('rent', 'house'), ('buy', 'house')]
    seen = set()
    combined = []
    for listing_type, property_type in combos:
        for item in fetch_listings(listing_type, property_type):
            if item['hash_id'] in seen:
                continue
            seen.add(item['hash_id'])
            combined.append(item)
    return combined
