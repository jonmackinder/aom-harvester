"""
Eventbrite → events.json (robust)
- Reads EVENTBRITE_TOKEN from env
- Optional env: AOM_CITY, AOM_WITHIN_MILES, AOM_KEYWORDS, AOM_WINDOW_DAYS
- Never crashes CI: always writes events.json and exits 0
"""

import os, sys, time, json
from datetime import datetime, timedelta
from urllib.parse import urlencode

try:
    import requests
except Exception as e:
    print(f"Bootstrap import error: {e}")
    # minimal fallback; let workflow handle install
    raise

BASE = "https://www.eventbriteapi.com/v3/events/search/"

def getenv(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and v != "") else default

def search_events(token, keywords, city=None, within_miles=None, start_window_days=120):
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
        # Helpful diagnostics
        print(f"GET {resp.status_code} page={q['page']} url={url[:120]}...")
        if resp.status_code == 401:
            raise RuntimeError("Unauthorized (401). Check EVENTBRITE_TOKEN.")
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
        all_events.extend(events)

        pagination = data.get("pagination", {})
        if not pagination.get("has_more_items"):
            break
        q["page"] += 1
        time.sleep(0.3)

    return all_events

def write_json(obj, path="events.json"):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def main():
    token = os.getenv("EVENTBRITE_TOKEN")
    city = getenv("AOM_CITY")
    within = getenv("AOM_WITHIN_MILES")
    window_days = int(getenv("AOM_WINDOW_DAYS", "150"))
    keywords = getenv("AOM_KEYWORDS", "steampunk gaslamp aether victorian tesla edison renaissance faire time travel")
    keywords_list = [w for w in keywords.split() if w.strip()]

    result = {
        "meta": {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "city": city,
            "within_miles": within,
            "window_days": window_days,
            "keywords": keywords_list,
        },
        "events": []
    }

    if not token:
        msg = "Missing EVENTBRITE_TOKEN; writing empty events.json."
        print("WARN:", msg)
        write_json(result)  # empty
        print("SUMMARY:", json.dumps({"found": 0, **result["meta"]}))
        return 0

    try:
        events = search_events(
            token=token,
            keywords=keywords_list,
            city=city,
            within_miles=int(within) if within else None,
            start_window_days=window_days,
        )
        result["events"] = events
        write_json(result)
        print("SUMMARY:", json.dumps({"found": len(events), **result["meta"]}))
        return 0
    except Exception as e:
        # Never hard-fail CI; capture the error and write diagnostics
        result["error"] = str(e)
        write_json(result)
        print("ERROR:", e)
        print("SUMMARY:", json.dumps({"found": 0, **result["meta"], "error": str(e)}))
        return 0  # <-- exit 0 on purpose
# --- Save results and print summary ---
import json

# Save all events into a JSON file (artifact for GitHub Actions)
with open("events.json", "w") as f:
    json.dump({"events": events}, f, indent=2)

# Print a one-line summary so you see it in the Actions log
print(f"SUMMARY: found={len(events)} city={city} within={within} window_days={window_days}")

if __name__ == "__main__":
    sys.exit(main())
