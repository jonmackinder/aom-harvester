#!/usr/bin/env python3
"""
Minimal Eventbrite harvester (v0.1)
- Reads EVENTBRITE_TOKEN from environment (GitHub secret)
- Queries /v3/events/search/ for "steampunk" from now forward
- Writes events.json with {meta, events, error}
- ALWAYS exits 0 so CI doesn't fail while we're iterating
"""

import os
import sys
import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUT_PATH = "events.json"


def utc_now_iso():
    # ISO8601 in UTC with trailing Z
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def fetch_events(token: str):
    base = "https://www.eventbriteapi.com/v3/events/search/"
    params = {
        "q": "steampunk",
        "sort_by": "date",
        "page": 1,
        "start_date.range_start": utc_now_iso(),
    }
    url = f"{base}?{urlencode(params)}"
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    token = os.environ.get("EVENTBRITE_TOKEN", "").strip()

    result = {
        "meta": {
            "ts_utc": utc_now_iso(),
            "keywords": ["steampunk"],
        },
        "events": [],
        "error": None,
    }

    if not token:
        result["error"] = "Missing EVENTBRITE_TOKEN"
        write_json(OUT_PATH, result)
        print("No token found; wrote empty events.json")
        return 0

    try:
        data = fetch_events(token)
        result["events"] = data.get("events", [])
    except Exception as e:
        # Capture the message but still produce an artifact
        result["error"] = f"{type(e).__name__}: {e}"

    write_json(OUT_PATH, result)
    print(f"Wrote {OUT_PATH} with {len(result['events'])} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
