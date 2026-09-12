#!/usr/bin/env python3
"""
Build a self-contained static demo of FlatRadar for GitHub Pages.
Reads templates/index.html, injects mock data and a fetch interceptor,
outputs docs/index.html.
"""
import os, re, json

BASE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(BASE, 'templates', 'index.html')
DST  = os.path.join(BASE, 'docs', 'index.html')

os.makedirs(os.path.join(BASE, 'docs'), exist_ok=True)

# ── Mock data ────────────────────────────────────────────────────────────────

PROFILES = [
    {
        "id": 1, "name": "Prague – Line A", "active": 1,
        "listing_type": "rent", "property_type": "flat",
        "price_min": 0, "price_max": 30000,
        "size_min": 35, "size_max": 0,
        "districts": json.dumps(["Vinohrady","Žižkov","Dejvice","Malá Strana",
                                  "Staré Město","Nové Město","Strašnice","Hostivař",
                                  "Motol","Petřiny","Veleslavín"]),
        "selected_cities": '["Praha"]',
        "selected_neighborhoods": '["Vinohrady","Žižkov","Dejvice","Malá Strana","Staré Město","Nové Město"]',
        "metro_stops": json.dumps(["Náměstí Míru","Jiřího z Poděbrad","Flora",
                                    "Želivského","Dejvická","Hradčanská",
                                    "Malostranská","Staroměstská","Můstek A",
                                    "Muzeum A","Strašnická","Skalka","Depo Hostivař",
                                    "Nemocnice Motol","Petřiny","Nádraží Veleslavín",
                                    "Bořislavka"]),
        "score_threshold": 65, "notify_email": 1,
        "room_types": '["2+kk","2+1","3+kk"]',
        "feature_balcony": 0, "feature_terrace": 0, "feature_parking": 0,
        "feature_cellar": 0, "feature_bathtub": 0, "feature_dishwasher": 0,
        "feature_furnished": "any", "feature_furnished_v2": "[]",
        "feature_building_age": "any", "feature_building_age_v2": "[]",
        "supermarket_chains": "[]", "supermarket_max_km": 0,
        "park_max_km": 0,
        "workplace_address": "Václavské náměstí 1, Praha 1",
        "workplace_lat": 50.0815, "workplace_lng": 14.4279,
    },
    {
        "id": 2, "name": "Brno flats", "active": 1,
        "listing_type": "rent", "property_type": "flat",
        "price_min": 0, "price_max": 18000,
        "size_min": 40, "size_max": 0,
        "districts": '["Brno"]',
        "selected_cities": '["Brno"]',
        "selected_neighborhoods": "[]", "metro_stops": "[]",
        "score_threshold": 60, "notify_email": 1,
        "room_types": '["2+kk","2+1","3+kk","3+1"]',
        "feature_balcony": 0, "feature_terrace": 0, "feature_parking": 0,
        "feature_cellar": 0, "feature_bathtub": 0, "feature_dishwasher": 0,
        "feature_furnished": "any", "feature_furnished_v2": "[]",
        "feature_building_age": "any", "feature_building_age_v2": "[]",
        "supermarket_chains": "[]", "supermarket_max_km": 0,
        "park_max_km": 0,
        "workplace_address": "Náměstí Svobody 1, Brno",
        "workplace_lat": 49.1948, "workplace_lng": 16.6095,
    },
]

def mk(hash_id, source, title, locality, price, size, listing_type,
       property_type, room_type, score, floor=0, image_url="",
       url="", is_new=False, is_saved=False,
       commute_km=None, commute_walk_est=None):
    return {
        "hash_id": hash_id, "source": source, "title": title,
        "locality": locality, "price": price, "price_currency": "CZK",
        "listing_type": listing_type, "property_type": property_type,
        "size_m2": size, "floor_number": floor, "room_type": room_type,
        "image_url": image_url, "url": url or "https://www.sreality.cz",
        "features_parsed": "{}",
        "first_seen_at": "2026-09-12T08:00:00",
        "last_seen_at":  "2026-09-12T09:00:00",
        "active": 1, "score": score, "is_new": is_new,
        "is_saved": is_saved, "is_hidden": False,
        "saved_status": None, "price_drop": False,
        "commute_km": commute_km, "commute_walk_est": commute_walk_est,
        # NOTE: real /api/feed pre-parses score_breakdown into an object
        # (app.py: d['score_breakdown'] = json.loads(...)) before sending,
        # so this must be a plain dict here, not a JSON string.
        "score_breakdown": {
            "price": int(score*0.3), "size": int(score*0.25),
            "location": int(score*0.25), "type": 10, "recency": 8,
        },
    }

LISTINGS_PRAGUE = [
    mk("pr001","bezrealitky","Pronájem bytu 2+kk 52 m²",
       "Mánesova, Vinohrady, Praha, Praha 2",22500,52,"rent","flat","2+kk",92,3,
       "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       is_saved=True, commute_km=1.8, commute_walk_est=22),
    mk("pr002","bezrealitky","Pronájem bytu 2+1 58 m²",
       "Blanická, Vinohrady, Praha, Praha 2",24000,58,"rent","flat","2+1",89,2,
       "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=2.1, commute_walk_est=26),
    mk("pr003","expats","Apartment for rent 2+kk 48 m²",
       "Korunní, Vinohrady, Praha 2",21000,48,"rent","flat","2+kk",87,1,
       "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=400&h=225&fit=crop","https://www.expats.cz",True,
       commute_km=1.6, commute_walk_est=20),
    mk("pr004","bezrealitky","Pronájem bytu 3+kk 75 m²",
       "Žitná, Nové Město, Praha, Praha 2",28500,75,"rent","flat","3+kk",86,4,
       "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       is_saved=True, commute_km=0.9, commute_walk_est=11),
    mk("pr005","bezrealitky","Pronájem bytu 2+kk 44 m²",
       "Slavíkova, Žižkov, Praha, Praha 3",19500,44,"rent","flat","2+kk",84,2,
       "https://images.unsplash.com/photo-1493809842364-78817add7ffb?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=2.8, commute_walk_est=34),
    mk("pr006","expats","Modern 2BR apartment, Žižkov",
       "Seifertova, Žižkov, Praha 3",20000,50,"rent","flat","2+kk",83,3,
       "https://images.unsplash.com/photo-1524758631624-e2822e304c36?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=2.5, commute_walk_est=31),
    mk("pr007","bezrealitky","Pronájem bytu 2+1 62 m²",
       "Budečská, Vinohrady, Praha, Praha 2",25000,62,"rent","flat","2+1",82,2,
       "https://images.unsplash.com/photo-1585128792020-803d29415281?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=2.0, commute_walk_est=25),
    mk("pr008","bezrealitky","Pronájem bytu 3+kk 80 m²",
       "Mánesova, Vinohrady, Praha, Praha 2",29000,80,"rent","flat","3+kk",81,5,
       "https://images.unsplash.com/photo-1586023492125-27b2c045efd7?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=1.9, commute_walk_est=23),
    mk("pr009","expats","Charming 2+kk in Malá Strana",
       "Nerudova, Malá Strana, Praha 1",26000,47,"rent","flat","2+kk",79,2,
       "https://images.unsplash.com/photo-1507089947368-19c1da9775ae?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=1.4, commute_walk_est=17),
    mk("pr010","bezrealitky","Pronájem bytu 2+kk 50 m²",
       "Máchova, Vinohrady, Praha, Praha 2",23000,50,"rent","flat","2+kk",78,1,
       "https://images.unsplash.com/photo-1554995207-c18c203602cb?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=1.7, commute_walk_est=21),
    mk("pr011","bezrealitky","Pronájem bytu 2+1 55 m²",
       "Jagellonská, Žižkov, Praha, Praha 3",20500,55,"rent","flat","2+1",77,3,
       "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=2.6, commute_walk_est=32),
    mk("pr012","expats","Bright 3+kk apartment, Dejvice",
       "Dejvická, Dejvice, Praha 6",27500,72,"rent","flat","3+kk",76,2,
       "https://images.unsplash.com/photo-1536376072261-38c75010e6c9?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=3.8, commute_walk_est=47),
    mk("pr013","bezrealitky","Pronájem bytu 2+kk 42 m²",
       "Vršovická, Strašnice, Praha, Praha 10",17500,42,"rent","flat","2+kk",74,0,
       "https://images.unsplash.com/photo-1538688525198-9b88f6f53126?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=4.2, commute_walk_est=52),
    mk("pr014","bezrealitky","Pronájem bytu 3+1 85 m²",
       "Slavíkova, Žižkov, Praha, Praha 3",29500,85,"rent","flat","3+1",73,4,
       "https://images.unsplash.com/photo-1574362848149-11496d93a7c7?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=2.7, commute_walk_est=33),
    mk("pr015","expats","Cozy studio near Náměstí Míru",
       "Mánesova, Vinohrady, Praha 2",16000,32,"rent","flat","1+kk",68,1,
       "https://images.unsplash.com/photo-1598928636135-d146006ff4be?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=1.5, commute_walk_est=19),
]

LISTINGS_BRNO = [
    mk("br001","bezrealitky","Pronájem bytu 2+kk 55 m²",
       "Masarykova, Brno-střed, Brno, Jihomoravský kraj",15000,55,"rent","flat","2+kk",91,2,
       "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=0.4, commute_walk_est=5),
    mk("br002","bezrealitky","Pronájem bytu 3+kk 68 m²",
       "Veveří, Brno-střed, Brno, Jihomoravský kraj",16500,68,"rent","flat","3+kk",88,3,
       "https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       is_saved=True, commute_km=1.2, commute_walk_est=15),
    mk("br003","expats","2BR apartment, city center Brno",
       "Žabovřesky, Brno, Jihomoravský kraj",14000,52,"rent","flat","2+kk",85,1,
       "https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=2.1, commute_walk_est=26),
    mk("br004","bezrealitky","Pronájem bytu 2+1 60 m²",
       "Královo Pole, Brno, Jihomoravský kraj",14500,60,"rent","flat","2+1",83,2,
       "https://images.unsplash.com/photo-1617806118233-18e1de247200?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=2.8, commute_walk_est=34),
    mk("br005","bezrealitky","Pronájem bytu 3+1 75 m²",
       "Řečkovice, Brno, Jihomoravský kraj",16000,75,"rent","flat","3+1",80,0,
       "https://images.unsplash.com/photo-1630699144867-37acec97df5a?w=400&h=225&fit=crop","https://www.bezrealitky.cz",True,
       commute_km=4.5, commute_walk_est=56),
    mk("br006","expats","Modern flat near Brno university",
       "Veveří, Brno-střed, Brno",13500,48,"rent","flat","2+kk",77,3,
       "https://images.unsplash.com/photo-1583608205776-bfd35f0d9f83?w=400&h=225&fit=crop","https://www.expats.cz",False,
       commute_km=1.1, commute_walk_est=14),
    mk("br007","bezrealitky","Pronájem bytu 2+kk 50 m²",
       "Lesná, Brno, Jihomoravský kraj",13000,50,"rent","flat","2+kk",75,4,
       "https://images.unsplash.com/photo-1600121848594-d8644e57abab?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=3.2, commute_walk_est=40),
    mk("br008","bezrealitky","Pronájem bytu 3+kk 72 m²",
       "Bystrc, Brno, Jihomoravský kraj",15500,72,"rent","flat","3+kk",72,1,
       "https://images.unsplash.com/photo-1618221118493-9cfa1a1c00da?w=400&h=225&fit=crop","https://www.bezrealitky.cz",False,
       commute_km=5.8, commute_walk_est=72),
]

ALL_LISTINGS = LISTINGS_PRAGUE + LISTINGS_BRNO

FEED_RESPONSE = {
    "listings": ALL_LISTINGS,
    "total": len(ALL_LISTINGS),
    "page": 1,
    "per_page": 24,
}

STATUS = {
    "db": {
        "active_profiles": 2,
        "new_today": len(ALL_LISTINGS),
        "sources": {"bezrealitky": 16, "expats": 7, "sreality": 0},
        "total_listings": len(ALL_LISTINGS),
    },
    "scheduler": {
        "interval_minutes": 15, "last_run": "2026-09-12T09:00:00",
        "last_run_count": 23, "manual_only": False,
        "next_run": "2026-09-12T09:15:00", "running": True,
    },
}

INSIGHTS_PRICE = {
    "labels": ["Vinohrady","Žižkov","Malá Strana","Dejvice","Nové Město",
               "Staré Město","Strašnice","Brno-střed","Královo Pole"],
    "values": [478,412,523,445,502,567,389,278,255],
    "counts": [42,38,19,24,31,15,22,35,28],
    "listing_type": "rent",
}

INSIGHTS_DAY = {
    "labels": [
        "2026-08-30","2026-08-31","2026-09-01","2026-09-02","2026-09-03",
        "2026-09-04","2026-09-05","2026-09-06","2026-09-07","2026-09-08",
        "2026-09-09","2026-09-10","2026-09-11","2026-09-12"
    ],
    "datasets": {
        "sreality":    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "bezrealitky": [18, 24, 31, 27, 29, 12, 8, 22, 35, 28, 31, 24, 19, 16],
        "expats":      [4, 6, 8, 5, 7, 3, 2, 6, 9, 7, 8, 5, 6, 4],
    }
}

# NOTE: the real /api/insights/day-of-week route returns a different shape
# ({labels: [Sun..Sat], values: [...]}) than /api/insights/listings-by-day
# ({labels: [14 dates], datasets: {...}}) — the frontend's loadDowChart()
# does Math.max(...data.values), which would throw if given INSIGHTS_DAY's
# new datasets shape. Kept as a separate constant so both mocks stay correct.
INSIGHTS_DOW = {
    "labels": ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],
    "values": [12,89,94,76,68,103,34],
}

INSIGHTS_SOURCE = [
    {"source": "bezrealitky", "total_active": 16, "last_active": "2026-09-12T09:00:00"},
    {"source": "expats",      "total_active": 7,  "last_active": "2026-09-12T09:00:00"},
]

INSIGHTS_PULSE = {
    "this_week":{"new_listings":23,"avg_price":21800},
    "last_week":{"new_listings":18,"avg_price":22400},
    "listing_delta":5,"listing_delta_pct":27.8,
    "price_delta":-600,"price_delta_pct":-2.7,
}

INSIGHTS_TOM = {
    "labels": ["Vinohrady", "Žižkov", "Dejvice", "Malá Strana", "Nové Město",
               "Brno-střed", "Královo Pole", "Žabovřesky"],
    "values": [3.2, 4.8, 2.9, 5.1, 3.7, 6.2, 7.4, 8.1],
    "counts": [12, 9, 7, 5, 11, 8, 6, 4],
}

INSIGHTS_DIST = {
    "labels":["Under 10k","10–15k","15–20k","20–25k","25–30k","30–40k","Over 40k"],
    "values":[0,3,6,8,4,1,1],
    "listing_type":"rent",
}

INSIGHTS_MATCH = [
    {"profile":"Prague – Line A","matching":15,"total":23,"pct":65.2},
    {"profile":"Brno flats","matching":8,"total":23,"pct":34.8},
]

# NOTE: the real /api/saved route returns a bare array (jsonify(_saved_rows()))
# and _saved_rows() pre-parses `notes` into a list before sending — so this
# must be a bare list with `notes` as an actual list, not a wrapped
# {"listings": [...]} object with a JSON-stringified notes field (the
# frontend calls notes.forEach(...) directly on it).
SAVED = [
    {**ALL_LISTINGS[0],
     "status": "interested",
     "notes": [
         {"text": "Great location, 2 min from Náměstí Míru metro",
          "timestamp": "2026-09-12T09:30:00"}
     ],
     "saved_at": "2026-09-12T09:05:00"},
    {**ALL_LISTINGS[3],
     "status": "visited",
     "notes": [
         {"text": "Viewed on Sep 11 – very spacious, quiet street",
          "timestamp": "2026-09-11T14:00:00"},
         {"text": "Landlord responsive, asking if pets allowed",
          "timestamp": "2026-09-11T16:30:00"},
     ],
     "saved_at": "2026-09-11T10:00:00"},
    {**next(l for l in ALL_LISTINGS if l["hash_id"] == "br002"),
     "status": "contacted",
     "notes": [
         {"text": "Emailed landlord, waiting for response",
          "timestamp": "2026-09-12T08:00:00"}
     ],
     "saved_at": "2026-09-12T08:00:00"},
]

LOGS_RUNS = {
    "items":[
        {"id":1,"started_at":"2026-09-12T09:00:00","completed_at":"2026-09-12T09:01:42",
         "sreality_fetched":0,"bezrealitky_fetched":640,"expats_fetched":231,
         "new_listings":23,"deduplicated":4,
         "profile_matches":json.dumps({"Prague – Line A":15,"Brno flats":8}),
         "errors":"[]","status":"ok"},
        {"id":2,"started_at":"2026-09-12T08:45:00","completed_at":"2026-09-12T08:46:38",
         "sreality_fetched":0,"bezrealitky_fetched":638,"expats_fetched":230,
         "new_listings":5,"deduplicated":2,
         "profile_matches":json.dumps({"Prague – Line A":15,"Brno flats":8}),
         "errors":"[]","status":"ok"},
    ],
    "total":2,
}

LOGS_PRICE = [
    {"hash_id":"pr003","title":"Apartment for rent 2+kk 48 m²",
     "locality":"Korunní, Vinohrady, Praha 2",
     "url":"https://www.expats.cz","source":"expats",
     "current_price":21000,"previous_price":22500,
     "changed_at":"2026-09-12T07:30:00"},
    {"hash_id":"br002","title":"Pronájem bytu 3+kk 68 m²",
     "locality":"Veveří, Brno-střed, Brno",
     "url":"https://www.bezrealitky.cz","source":"bezrealitky",
     "current_price":16500,"previous_price":17000,
     "changed_at":"2026-09-11T14:20:00"},
]

NOTIF_LOG = {
    "items":[
        {"id":1,"notification_type":"new_match","sent_at":"2026-09-12T09:02:00",
         "success":1,"error_message":None,
         "title":"Pronájem bytu 2+kk 52 m²",
         "locality":"Mánesova, Vinohrady, Praha, Praha 2",
         "price":22500,"url":"https://www.bezrealitky.cz",
         "source":"bezrealitky","profile_name":"Prague – Line A"},
        {"id":2,"notification_type":"new_match","sent_at":"2026-09-12T09:02:00",
         "success":1,"error_message":None,
         "title":"Pronájem bytu 2+kk 55 m²",
         "locality":"Masarykova, Brno-střed, Brno",
         "price":15000,"url":"https://www.bezrealitky.cz",
         "source":"bezrealitky","profile_name":"Brno flats"},
    ],
    "total":2,"offset":0,"limit":50,
}

SETTINGS = {
    "smtp_host":"smtp.mail.yahoo.com","smtp_port":"587",
    "smtp_user":"","email_from":"","email_to":"",
    "notifications_enabled":"0","notification_frequency":"daily",
    "scheduler_interval_minutes":"15",
    "scheduler_restrict_hours":"0",
    "scheduler_time_start":"08:00","scheduler_time_end":"22:00",
    "smtp_password":"",
    "last_notification_sent":"2026-09-12T09:02:00",
}

MOCK_SUPERMARKETS = [
    {"chain": "Albert", "name": "Albert", "distance_km": 0.39},
    {"chain": "Billa", "name": "Billa", "distance_km": 0.72},
    {"chain": "Lidl", "name": "Lidl", "distance_km": 1.15},
    {"chain": "Penny Market", "name": "Penny Market", "distance_km": 1.43},
    {"chain": "Kaufland", "name": "Kaufland", "distance_km": 2.18},
]

MOCK_PARKS = [
    {"name": "Riegrovy sady", "distance_km": 0.31},
    {"name": "Čelakovského sady", "distance_km": 0.44},
    {"name": "Havlíčkovy sady", "distance_km": 0.87},
    {"name": "Green space", "distance_km": 1.12},
    {"name": "Fidlovačka", "distance_km": 1.38},
]

# ── Fetch interceptor JS ─────────────────────────────────────────────────────

MOCK_JS = f"""
<script>
// ── FlatRadar demo mode ──────────────────────────────────────────────────────
const DEMO_DATA = {{
  profiles:     {json.dumps(PROFILES)},
  feed:         {json.dumps(FEED_RESPONSE)},
  status:       {json.dumps(STATUS)},
  settings:     {json.dumps(SETTINGS)},
  saved:        {json.dumps(SAVED)},
  notif_log:    {json.dumps(NOTIF_LOG)},
  logs_runs:    {json.dumps(LOGS_RUNS)},
  logs_price:   {json.dumps(LOGS_PRICE)},
  insights: {{
    price_by_district: {json.dumps(INSIGHTS_PRICE)},
    listings_by_day:   {json.dumps(INSIGHTS_DAY)},
    source_health:     {json.dumps(INSIGHTS_SOURCE)},
    market_pulse:      {json.dumps(INSIGHTS_PULSE)},
    time_on_market:    {json.dumps(INSIGHTS_TOM)},
    day_of_week:       {json.dumps(INSIGHTS_DOW)},
    price_distribution:{json.dumps(INSIGHTS_DIST)},
    profile_match_rate:{json.dumps(INSIGHTS_MATCH)},
  }},
}};

function _mockResp(data) {{
  return Promise.resolve({{
    ok: true, status: 200,
    json:  () => Promise.resolve(typeof data === 'string' ? JSON.parse(data) : data),
    text:  () => Promise.resolve(JSON.stringify(data)),
    headers: {{ get: () => 'application/json' }},
    content: data,
  }});
}}

// Demo saved state – starts with pre-loaded saved listings.
// DEMO_DATA.saved is a bare array (matching the real /api/saved response
// shape), so it's mapped directly rather than via a .listings wrapper.
const _demoSaved = new Map(
  DEMO_DATA.saved.map(l => [l.hash_id, l])
);

const _realFetch = window.fetch;
window.fetch = function(url, opts) {{
  const path   = (typeof url === 'string' ? url : url.url || '').split('?')[0];
  const method = (opts && opts.method || 'GET').toUpperCase();

  // Dynamic saved state
  if (path === '/api/saved' && method === 'GET') {{
    return _mockResp([..._demoSaved.values()]);
  }}
  const saveMatch = path.match(/^\/api\/listings\/([^/]+)\/save$/);
  if (saveMatch) {{
    const hashId = saveMatch[1];
    if (method === 'POST') {{
      const listing = DEMO_DATA.feed.listings.find(l => l.hash_id === hashId);
      if (listing) {{
        _demoSaved.set(hashId, {{
          ...listing,
          status: 'interested',
          notes: [],
          saved_at: new Date().toISOString(),
        }});
      }}
      return _mockResp({{saved: true}});
    }}
    if (method === 'DELETE') {{
      _demoSaved.delete(hashId);
      return _mockResp({{saved: false}});
    }}
  }}

  // Read-only routes
  if (path === '/api/profiles')                        return _mockResp(DEMO_DATA.profiles);
  if (path === '/api/feed') {{
    const fullUrl = url.startsWith('/') ? 'http://localhost' + url : url;
    const params = new URL(fullUrl).searchParams;
    const profileId = parseInt(params.get('profile_id'));
    if (!profileId) return _mockResp(DEMO_DATA.feed);
    const profile = DEMO_DATA.profiles.find(p => p.id === profileId);
    if (!profile) return _mockResp(DEMO_DATA.feed);
    const districts = JSON.parse(profile.districts || '[]');
    const threshold = profile.score_threshold || 60;
    const filtered = DEMO_DATA.feed.listings.filter(l => {{
      if (l.score < threshold) return false;
      if (!districts.length) return true;
      return districts.some(d => l.locality.toLowerCase().includes(d.toLowerCase()));
    }});
    return _mockResp({{...DEMO_DATA.feed, listings: filtered, total: filtered.length}});
  }}
  if (path === '/api/status')                          return _mockResp(DEMO_DATA.status);
  if (path === '/api/settings')                        return _mockResp(DEMO_DATA.settings);
  if (path === '/api/notifications/log')               return _mockResp(DEMO_DATA.notif_log);
  if (path === '/api/logs/runs')                       return _mockResp(DEMO_DATA.logs_runs);
  if (path === '/api/logs/price-changes')              return _mockResp(DEMO_DATA.logs_price);
  if (path === '/api/insights/price-by-district')      return _mockResp(DEMO_DATA.insights.price_by_district);
  if (path === '/api/insights/listings-by-day')        return _mockResp(DEMO_DATA.insights.listings_by_day);
  if (path === '/api/insights/source-health')          return _mockResp(DEMO_DATA.insights.source_health);
  if (path === '/api/insights/market-pulse')           return _mockResp(DEMO_DATA.insights.market_pulse);
  if (path === '/api/insights/time-on-market')         return _mockResp(DEMO_DATA.insights.time_on_market);
  if (path === '/api/insights/day-of-week')            return _mockResp(DEMO_DATA.insights.day_of_week);
  if (path === '/api/insights/price-distribution')     return _mockResp(DEMO_DATA.insights.price_distribution);
  if (path === '/api/insights/profile-match-rate')     return _mockResp(DEMO_DATA.insights.profile_match_rate);

  // Supermarkets / parks / commute – return empty (no Overpass in demo)
  if (path === '/api/supermarkets/fetch-area')         return _mockResp({json.dumps(MOCK_SUPERMARKETS)});
  if (path === '/api/parks/fetch-area')                return _mockResp({json.dumps(MOCK_PARKS)});
  if (path.startsWith('/api/supermarkets'))            return _mockResp([]);
  if (path.startsWith('/api/parks'))                   return _mockResp([]);
  if (path === '/api/geocode')                         return _mockResp({{found:true,lat:50.0815,lng:14.4279}});
  if (path.startsWith('/api/geocode'))                 return _mockResp({{found:false}});
  if (path.includes('/commute'))                       return _mockResp({{available:false}});

  // Write routes – acknowledge silently
  if (method === 'POST' || method === 'PUT' ||
      method === 'PATCH' || method === 'DELETE') {{
    return _mockResp({{ok:true,triggered:true,saved:true,seen:0,started:true,recalculated:true}});
  }}

  // Fallback
  return _mockResp({{}});
}};
// ────────────────────────────────────────────────────────────────────────────
</script>
"""

# ── Build ────────────────────────────────────────────────────────────────────

with open(SRC, 'r', encoding='utf-8') as f:
    html = f.read()

# Inject mock fetch interceptor right before </head>
html = html.replace('</head>', MOCK_JS + '\n</head>', 1)

# Patch proxyImg to serve images directly in demo (no Flask proxy)
html = html.replace(
    "return '/api/image-proxy?url=' + encodeURIComponent(url);",
    "return url; // demo mode – serve directly",
    1
)

# Add demo banner below nav
BANNER = '''<div style="background:#1a1040;border-bottom:1px solid #3b2080;
  padding:8px 24px;font-size:12px;color:#a78bfa;text-align:center">
  ✦ Demo mode – data is pre-loaded. No live scraping.
  &nbsp;·&nbsp;
  <a href="https://github.com/teokitten/flatradar"
     target="_blank" style="color:#818cf8;text-decoration:none">
    View on GitHub →
  </a>
</div>'''
html = html.replace('<div id="nav">', BANNER + '\n<div id="nav">', 1)

with open(DST, 'w', encoding='utf-8') as f:
    f.write(html)

print(f'Demo built → {DST}')
print(f'  Profiles: {len(PROFILES)}')
print(f'  Listings: {len(ALL_LISTINGS)} ({len(LISTINGS_PRAGUE)} Prague, {len(LISTINGS_BRNO)} Brno)')
