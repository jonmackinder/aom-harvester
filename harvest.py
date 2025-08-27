"""
Eventbrite → events.json (JSON-only)
- Reads EVENTBRITE_TOKEN from env
- Accepts optional env overrides for keywords/city/radius/window days
- Writes all matching events to events.json
"""

import os, sys, time, json
from datetime import datetime, timedelta
from urllib.parse import urlencode
import requests

BASE = "https://www.eventbriteapi.com/v3/events/search/"

def getenv(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and v != "") else default

def search_events(token, keywords, city=None, within_miles=None, start_window_days=120, page_size=50):
    headers = {"Authorization": f"Bearer {token}"}
    start_date = datetime.utcnow()
    end_date   = start_date + timedelta(days=int(start_window_days))

    q = {
        "q": " ".join(keywords),
        "start_date.range_start": start_date.isoformat() + "Z",
        "start_date.range_end":   end_date.isoformat() + "Z",
        "expand": "venue,organizer",
        "sort_by": "date",
        "page": 1,
    }
    if city:
        q["location.address"] = city
    if within_miles:
        q["location.within"] = f"{within_miles}mi"

    all_events = []
    while True:
        url = BASE + "?" + urlencode(q)
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            raise SystemExit("ERROR: Unauthorized. Check EVENTBRITE_TOKEN.")
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
        all_events.extend(events)

        pagination = data.get("pagination", {})
        if not pagination.get("has_more_items"):
            break
        q["page"] += 1
        time.sleep(0.3)  # politeness

    return all_events

def main():
    token = os.environ.get("EVENTBRITE_TOKEN")
    if not token:
        print("ERROR: EVENTBRITE_TOKEN is not set.")
        sys.exit(2)

    # Defaults can be overridden by workflow inputs (env)
    keywords = getenv("AOM_KEYWORDS", "steampunk gaslamp aether victorian tesla edison renaissance faire time travel")
    keywords_list = [w for w in keywords.split() if w.strip()]

    city = getenv("AOM_CITY")
    within = getenv("AOM_WITHIN_MILES")
    window_days = getenv("AOM_WINDOW_DAYS", "150")

    events = search_events(
        token=token,
        keywords=keywords_list,
        city=city,
        within_miles=int(within) if within else None,
        start_window_days=int(window_days),
    )

    with open("events.json", "w") as f:
        json.dump(events, f, indent=2)

    print("SUMMARY:", json.dumps({
        "found": len(events),
        "city": city,
        "within_miles": within,
        "window_days": window_days,
        "keywords": keywords_list[:8]  # preview
    }))

if __name__ == "__main__":
    main()
