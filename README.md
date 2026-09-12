# FlatRadar

A personal apartment search tool for the Czech Republic. Aggregates listings
from Sreality, Bezrealitky, and Expats.cz into one place, scores them against
your criteria, and emails you when new matches appear.

Built for English-speaking expats searching for apartments in Czech Republic.

---

## Requirements

- Python 3.10 or higher
- Internet connection (for scraping and Overpass API)
- A Yahoo or Gmail account for email notifications

---

## Installation

```bash
git clone https://github.com/teokitten/flatradar.git
cd flatradar
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py
```

Open http://localhost:5001 in your browser.

---

## Setup

**1. Create a search profile**
Go to Search setup. Set your city, price range, size, room type, and any
other criteria. Save the profile.

**2. Configure email notifications**
Go to App Settings (⚙). Select your email provider, enter your address,
and generate an app password – not your regular account password. Instructions
are shown in the settings form for Yahoo, Gmail, Outlook, and iCloud.

**3. Run a fetch**
Click Fetch now in the feed, or wait for the scheduler to run automatically.
The default interval is 15 minutes.

---

## Features

- Listings from three sources: Sreality, Bezrealitky, Expats.cz
- Deduplication across sources – the same apartment only appears once
- Scoring 0–100 based on how well each listing matches your profile
- Filters: city, district, neighborhood, metro stop, price, size, room type,
  furnished status, building condition, must-have features (balcony, parking,
  cellar, bathtub, dishwasher)
- Supermarket and park proximity – shows what's nearby when you select an area
- Commute calculator – enter your workplace and see estimated walking time
  on each card
- Email notifications when new matching listings appear, at a frequency
  you choose (daily, every 3 days, or weekly)
- Price change tracking – the Logs tab shows which listings changed price
- Activity log – every scraper run is recorded with source counts and
  profile match summaries
- Insights – price per m² by district, listing volume by day of week,
  price distribution, profile match rate

---

## Limitations

**Sreality images do not load.** Sreality's CDN blocks image requests that
don't come from a browser with an active sreality.cz session. Listing data
and links work correctly – only photos are missing. Bezrealitky and
Expats.cz images load fine.

**The app must be running to check for new listings.** FlatRadar runs locally
on your machine. If the app is stopped, no fetches happen and no
notifications are sent.

**GPS data is partial.** Bezrealitky provides coordinates for its listings.
Sreality and Expats.cz do not. Commute time and proximity features only
work for listings that have GPS data.

**Feature extraction (furnished, balcony, etc.) is best-effort.** This
information is parsed from listing labels and descriptions. Not all listings
include it, and accuracy depends on how thoroughly the landlord filled in
their listing.

**Supermarket and park data comes from OpenStreetMap** via the Overpass API.
The public Overpass instance has rate limits. If you select many areas in
quick succession, some requests may fail silently and retry on the next load.

---

## Data sources

- [Sreality.cz](https://www.sreality.cz) – listing data only, no images
- [Bezrealitky.cz](https://www.bezrealitky.cz) – listing data and images
- [Expats.cz](https://www.expats.cz) – listing data and images
- [OpenStreetMap](https://www.openstreetmap.org) via Overpass API –
  supermarket and park locations
- [Nominatim](https://nominatim.org) – workplace address geocoding
- [OSRM](https://project-osrm.org) – walking route times

---

## Stack

Flask · SQLite · APScheduler · vanilla JavaScript · Chart.js
