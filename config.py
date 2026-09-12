import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'flatradar.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

IMAGE_CACHE_DIR = os.path.join(BASE_DIR, 'static', 'listing_images')
IMAGE_CACHE_URL = '/static/listing_images/'

CHECK_INTERVAL_MINUTES = 20

SREALITY_API_BASE = 'https://www.sreality.cz/api/v1/estates/search'
SREALITY_LANG = 'cs'
SREALITY_PER_PAGE = 60
SREALITY_MAX_PAGES = 5
SREALITY_DELAY_SECONDS = 2

SREALITY_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.sreality.cz/',
    'Origin': 'https://www.sreality.cz',
}

SREALITY_CATEGORY_MAIN = {'flat': 1, 'house': 2}
SREALITY_CATEGORY_TYPE = {'rent': 2, 'buy': 1}
SREALITY_TYPE_SLUG = {1: 'prodej', 2: 'pronajem'}
SREALITY_MAIN_SLUG = {1: 'byt', 2: 'dum'}

SUPERMARKET_CHAINS = {
    'Globus':        {'brand': 'Globus',        'osm_shop': ['supermarket', 'hypermarket']},
    'Kaufland':      {'brand': 'Kaufland',       'osm_shop': ['supermarket', 'hypermarket']},
    'Albert':        {'brand': 'Albert',         'osm_shop': ['supermarket', 'hypermarket']},
    'Billa':         {'brand': 'Billa',          'osm_shop': ['supermarket']},
    'Lidl':          {'brand': 'Lidl',           'osm_shop': ['supermarket', 'discount']},
    'Penny Market':  {'brand': 'Penny Market',   'osm_shop': ['supermarket', 'discount']},
    'Tesco':         {'brand': 'Tesco',          'osm_shop': ['supermarket', 'hypermarket']},
    'Rohlik':        {'brand': 'Rohlik.cz',      'osm_shop': ['supermarket']},
}

OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
OVERPASS_TIMEOUT = 30
SUPERMARKET_CACHE_DAYS = 7
