import json
import time

import requests

BZ_ENDPOINT = 'https://api.bezrealitky.cz/graphql/'

BZ_HEADERS = {
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.bezrealitky.cz/',
    'Origin': 'https://www.bezrealitky.cz',
}

OFFER_TYPE = {'rent': 'PRONAJEM', 'buy': 'PRODEJ'}
ESTATE_TYPE = {'flat': 'BYT', 'house': 'DUM'}

BZ_PER_PAGE = 40
BZ_MAX_PAGES = 5
BZ_DELAY_SECONDS = 2

_QUERY = """
query AdvertList($offerType: [OfferType], $estateType: [EstateType], $limit: Int, $offset: Int) {
  listAdverts(offerType: $offerType, estateType: $estateType, limit: $limit, offset: $offset, order: TIMEORDER_DESC) {
    totalCount
    list {
      id
      uri
      title
      offerType
      estateType
      disposition
      price
      currency
      surface
      etage
      address(locale: CS)
      gps { lat lng }
      mainImage { url(filter: RECORD_MAIN) }
    }
  }
}
"""

_OFFER_LABEL = {'PRONAJEM': 'Pronájem', 'PRODEJ': 'Prodej'}
_ESTATE_LABEL = {'BYT': 'bytu', 'DUM': 'domu'}
_DISP_LABEL = {
    'GARSONIERA': 'garsoniéra', 'DISP_1_KK': '1+kk', 'DISP_1_1': '1+1',
    'DISP_2_KK': '2+kk', 'DISP_2_1': '2+1', 'DISP_3_KK': '3+kk', 'DISP_3_1': '3+1',
    'DISP_4_KK': '4+kk', 'DISP_4_1': '4+1', 'DISP_5_KK': '5+kk', 'DISP_5_1': '5+1',
    'DISP_6_KK': '6+kk', 'DISP_6_1': '6+1', 'DISP_7_KK': '7+kk', 'DISP_7_1': '7+1',
}


def _build_bz_title(advert):
    title = (advert.get('title') or '').strip()
    if title:
        return title
    parts = [
        _OFFER_LABEL.get(advert.get('offerType'), advert.get('offerType') or ''),
        _ESTATE_LABEL.get(advert.get('estateType'), advert.get('estateType') or ''),
        _DISP_LABEL.get(advert.get('disposition'), ''),
    ]
    label = ' '.join(p for p in parts if p).strip()
    surface = advert.get('surface')
    if surface:
        label = f'{label}, {int(surface)} m²'.strip(', ')
    return label or f"{advert.get('offerType', '')} {advert.get('estateType', '')}".strip()


def _extract_bz_locality(advert):
    address = advert.get('address')
    if isinstance(address, str):
        return address.strip()
    if isinstance(address, dict):
        parts = [address.get('city'), address.get('district'), address.get('street')]
        return ', '.join(p for p in parts if p)
    return ''


def _build_bz_image_url(advert):
    image = advert.get('mainImage') or {}
    url = image.get('url')
    if url:
        return url
    key = image.get('key')
    if key:
        return f'https://api.bezrealitky.cz/media/cache/record_main/data/images/{key}'
    return ''


def fetch_bz_listings(listing_type, property_type):
    offer = OFFER_TYPE[listing_type]
    estate = ESTATE_TYPE[property_type]
    results = []

    for page in range(BZ_MAX_PAGES):
        offset = page * BZ_PER_PAGE
        payload = {
            'query': _QUERY,
            'variables': {
                'offerType': [offer],
                'estateType': [estate],
                'limit': BZ_PER_PAGE,
                'offset': offset,
            },
        }
        try:
            response = requests.post(BZ_ENDPOINT, headers=BZ_HEADERS, json=payload, timeout=20)
        except Exception as e:
            print(f'Bezrealitky fetch error page {page}: {e}')
            break

        if response.status_code != 200:
            print(f'Bezrealitky status {response.status_code} page {page}')
            break

        try:
            data = response.json()
        except Exception as e:
            print(f'Bezrealitky fetch error page {page}: {e}')
            break

        if data.get('errors'):
            print(f'Bezrealitky graphql error page {page}: {data["errors"]}')
            break

        block = (data.get('data') or {}).get('listAdverts') or {}
        adverts = block.get('list') or []
        if not adverts:
            break

        for advert in adverts:
            advert_id = advert.get('id')
            if not advert_id:
                continue
            results.append({
                'hash_id': f'bz_{advert_id}',
                'source': 'bezrealitky',
                'title': _build_bz_title(advert),
                'locality': _extract_bz_locality(advert),
                'price': int(advert.get('price') or 0),
                'price_currency': 'CZK',
                'listing_type': listing_type,
                'property_type': property_type,
                'size_m2': int(advert.get('surface') or 0),
                'floor_number': int(advert.get('etage') or 0),
                'image_url': _build_bz_image_url(advert),
                'url': f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{advert.get('uri', '')}",
                'lat': float((advert.get('gps') or {}).get('lat') or 0) or None,
                'lng': float((advert.get('gps') or {}).get('lng') or 0) or None,
                'raw_data': json.dumps(advert),
            })

        if len(adverts) < BZ_PER_PAGE:
            break

        total = block.get('totalCount') or 0
        if offset + len(adverts) >= total:
            break

        if page < BZ_MAX_PAGES - 1:
            time.sleep(BZ_DELAY_SECONDS)

    return results


def run_all_bezrealitky():
    try:
        combos = [('rent', 'flat'), ('buy', 'flat'), ('rent', 'house'), ('buy', 'house')]
        seen = set()
        combined = []
        for listing_type, property_type in combos:
            for item in fetch_bz_listings(listing_type, property_type):
                if item['hash_id'] in seen:
                    continue
                seen.add(item['hash_id'])
                combined.append(item)
        return combined
    except Exception as e:
        print(f'Bezrealitky run error: {e}')
        return []


if __name__ == '__main__':
    probe_query = """
    query {
      listAdverts(offerType: [PRONAJEM], estateType: [BYT], limit: 1, offset: 0) {
        totalCount
        list {
          id
          uri
          title
          offerType
          estateType
          disposition
          price
          currency
          surface
          etage
          address(locale: CS)
          mainImage { url(filter: RECORD_MAIN) }
        }
      }
    }
    """
    r = requests.post(BZ_ENDPOINT, headers=BZ_HEADERS, json={'query': probe_query}, timeout=20)
    print('HTTP', r.status_code)
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
