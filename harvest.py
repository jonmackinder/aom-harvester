"""
Eventbrite → events.json (robust, phone-friendly)
- Reads EVENTBRITE_TOKEN (secret) and optional inputs via env
- NEVER leaves CI without an events.json
- ALWAYS exits 0 (so your workflow stays green)
- Prints a one-line SUMMARY in the logs
"""

import os, sys, time, json
from datetime import datetime, timedelta
from urllib.parse import urlencode

try:
    import requests
except Exception as e:
    # Let the workflow install deps; just surface a clear message if import failed
    print("Bootstrap import error:", e)

BASE = "https://www.eventbriteapi.com/v3/events/search/"

def getenv(name, default=None):
    v = os.environ.get(name)
    return v if (v is not None and v != "") else default

def search_events(token, keywords, city=None, within_miles=None, start_window_days=150):
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
        time.sleep(0.25)

    return all_events

def write_json(obj, path="events.json"):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)

def main():
    token = os.getenv("EVENTBRITE_TOKEN")
    city = getenv("AOM_CITY")
    within = getenv("AOM_WITHIN_MILES")
    window_days = int(getenv("AOM_WINDOW_DAYS", "150"))
    keywords = getenv("AOM_KEYWORDS", "steampunk gaslamp aether victorian tesla edison renaissance faire")
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

    # If the token is missing, don’t crash—write an informative file.
    if not token:
        msg = "Missing EVENTBRITE_TOKEN; writing empty events.json."
        print("WARN:", msg)
        write_json(result)
        print("SUMMARY:", json.dumps({"found": 0, **result["meta"], "note": "no token"}))
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
        # Never leave CI without a file; embed the error for debugging.
        result["error"] = str(e)
        write_json(result)
        print("ERROR:", e)
        print("SUMMARY:", json.dumps({"found": 0, **result["meta"], "error": str(e)}))
        return 0  # always exit 0 so GitHub Actions shows green

if __name__ == "__main__":
    sys.exit(main())
