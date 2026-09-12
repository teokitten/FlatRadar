import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

EXPATS_SITE = 'https://www.expats.cz'
EXPATS_BASE_URL = 'https://www.expats.cz/praguerealestate/apartments/for-rent'
EXPATS_SECTIONS = [
    'https://www.expats.cz/praguerealestate/apartments/for-rent',
    'https://www.expats.cz/praguerealestate/apartments/for-sale',
    'https://www.expats.cz/praguerealestate/houses/for-rent',
    'https://www.expats.cz/praguerealestate/houses/for-sale',
]
EXPATS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}
EXPATS_MAX_PAGES = 5
EXPATS_DELAY_SECONDS = 2

_DETAIL_RE = re.compile(r'/praguerealestate/for-(rent|sale)/(apartments|houses)/')
_ID_RE = re.compile(r'/(\d+)-')
_AREA_RE = re.compile(r'(\d[\d\s.,]*)\s*(m2|m²|m\b|sqm|sq\s?ft|sqft)', re.IGNORECASE)
_NUM_RE = re.compile(r'\d[\d\s.,]*')


def _parse_price(text):
    if not text:
        return 0
    lowered = text.lower()
    if 'request' in lowered or 'on request' in lowered:
        return 0
    match = _NUM_RE.search(text)
    if not match:
        return 0
    digits = re.sub(r'[^\d]', '', match.group(0))
    if not digits:
        return 0
    value = int(digits)
    if 'eur' in lowered or '€' in text:
        value = value * 25
    return value


def _parse_size(text):
    if not text:
        return 0
    match = _AREA_RE.search(text)
    if not match:
        return 0
    digits = re.sub(r'[^\d]', '', match.group(1))
    if not digits:
        return 0
    value = int(digits)
    unit = match.group(2).lower().replace(' ', '')
    if unit in ('sqft', 'sqft', 'sq ft'.replace(' ', '')):
        value = int(round(value * 0.0929))
    return value


def _absolute(url):
    if not url:
        return ''
    return urljoin(EXPATS_SITE, url)


def _parse_page(html):
    soup = BeautifulSoup(html, 'lxml')
    listings = []
    seen_on_page = set()

    headings = [
        h for h in soup.find_all(['h1', 'h2', 'h3'])
        if h.find('a', href=_DETAIL_RE)
    ]

    for heading in headings:
        anchor = heading.find('a', href=_DETAIL_RE)
        href = anchor.get('href') or ''
        url = _absolute(href)
        if not url or url in seen_on_page:
            continue

        card = heading.find_parent('div')
        seen_on_page.add(url)

        id_match = _ID_RE.search(href)
        if id_match:
            slug = id_match.group(1)
        else:
            slug = href.rstrip('/').split('/')[-1]
        if not slug:
            continue
        hash_id = f'ex_{slug}'

        title = anchor.get_text(' ', strip=True)
        title = re.sub(r'\s*m\s*2\b', ' m²', title)
        title = re.sub(r'\s+', ' ', title).strip()

        locality = ''
        sib = heading.find_next_sibling(['h3', 'h4', 'p', 'span'])
        if sib is not None:
            locality = sib.get_text(' ', strip=True)

        price = 0
        if card is not None:
            price_el = card.find('strong')
            if price_el is not None:
                price = _parse_price(price_el.get_text(' ', strip=True))

        blob = ' '.join(filter(None, [title, href.lower()]))
        alt_text = ''
        img = card.find('img') if card is not None else None
        if img is not None:
            alt_text = img.get('alt') or ''
        size_m2 = _parse_size(' '.join([title, alt_text]))

        lowered = blob.lower()
        if 'sale' in lowered or '/for-sale/' in href or 'buy' in lowered:
            listing_type = 'buy'
        elif 'rent' in lowered or '/for-rent/' in href:
            listing_type = 'rent'
        else:
            listing_type = 'rent'

        if 'house' in lowered or 'villa' in lowered or '/houses/' in href:
            property_type = 'house'
        else:
            property_type = 'flat'

        image_url = _absolute(img.get('src')) if img is not None and img.get('src') else ''

        listings.append({
            'hash_id': hash_id,
            'source': 'expats',
            'title': title,
            'locality': locality,
            'price': price,
            'price_currency': 'CZK',
            'listing_type': listing_type,
            'property_type': property_type,
            'size_m2': size_m2,
            'floor_number': 0,
            'image_url': image_url,
            'url': url,
            'raw_data': json.dumps({'title': title, 'locality': locality, 'price_raw': price}),
        })

    return listings


def _find_next_url(html, current_url):
    soup = BeautifulSoup(html, 'lxml')
    for anchor in soup.find_all('a', href=True):
        label = anchor.get_text(' ', strip=True).lower()
        rel = anchor.get('rel') or []
        if 'next' in label or 'next' in rel or '›' in label or '»' in label:
            nxt = _absolute(anchor['href'])
            if nxt and nxt != current_url:
                return nxt
    return None


def fetch_expats_listings():
    results = []
    seen = set()

    for section_url in EXPATS_SECTIONS:
        url = section_url
        for page in range(EXPATS_MAX_PAGES):
            try:
                response = requests.get(url, headers=EXPATS_HEADERS, timeout=15)
            except Exception as e:
                print(f'Expats fetch error {url}: {e}')
                break
            if response.status_code != 200:
                print(f'Expats status {response.status_code} {url}')
                break

            for item in _parse_page(response.text):
                if not item['url'] or not item['hash_id']:
                    continue
                if item['hash_id'] in seen:
                    continue
                seen.add(item['hash_id'])
                results.append(item)

            next_url = _find_next_url(response.text, url)
            if not next_url:
                break
            url = next_url
            time.sleep(EXPATS_DELAY_SECONDS)

    return results


def run_all_expats():
    try:
        seen = set()
        combined = []
        for item in fetch_expats_listings():
            if item['hash_id'] in seen:
                continue
            seen.add(item['hash_id'])
            combined.append(item)
        return combined
    except Exception as e:
        print(f'Expats run error: {e}')
        return []


if __name__ == '__main__':
    resp = requests.get(EXPATS_BASE_URL, headers=EXPATS_HEADERS, timeout=15)
    print('HTTP', resp.status_code, resp.url)
    print(resp.text[:3000])
