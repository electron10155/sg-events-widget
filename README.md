# SG Events Widget

A Daily Art-style desktop pet widget that curates free and low-cost public events in Singapore.

## Features

- **Apple Calendar widget aesthetic** — dark theme with gradient category colors
- **Daily Art-style carousel** — auto-rotating curated event cards (6s interval, hover to pause)
- **Personalized recommendations** — scoring engine based on user preferences (music, museums, free-first, solo exploration)
- **Dynamic data loading** — fetches `events.json` at runtime, falls back to built-in data offline
- **Auto-update** — Python scraper + WorkBuddy daily automation at 8am SGT

## Files

| File | Purpose |
|------|---------|
| `index.html` | The widget — single-file HTML/CSS/JS, no dependencies |
| `events.json` | Dynamic event data (auto-generated) |
| `update_events.py` | Python scraper for 10+ Singapore official sources |

## Data Sources

- [Singapore Night Festival](https://www.heritage.sg/sgnightfest)
- [Esplanade](https://www.esplanade.com/whats-on)
- [Gardens by the Bay](https://www.gardensbythebay.org.sg)
- [National Museum of Singapore](https://www.nationalmuseum.nhb.gov.sg)
- [National Gallery Singapore](https://www.nationalgallery.sg)
- [NParks](https://www.nparks.gov.sg/activities/events-and-workshops)
- [Gillman Barracks](https://www.gillmanbarracks.com)
- [Objectifs](https://www.objectifs.com.sg)
- [URA City Gallery](https://www.ura.gov.sg/visit/exhibitions/city-gallery)
- [Heritage Board](https://www.heritage.sg)

## Usage

1. Open `index.html` in any browser, or
2. Visit the [cloud deployment](https://f96971d66189406fa1f1008e2d91d727.app.workbuddy.link)
3. Use arrow keys or swipe to navigate, click event titles for official links

## Update Schedule

The WorkBuddy automation runs daily at 8:00 AM:
1. Python scraper pulls baseline data from official sources
2. WebSearch supplements JS-rendered sites (Esplanade, NParks, etc.)
3. WebFetch extracts event details
4. Writes `events.json` and redeploys to cloud
