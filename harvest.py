"""
Eventbrite → events.json (robust, phone-friendly)

- Reads EVENTBRITE_TOKEN (secret) and optional inputs via env
- Supports keywords, city/radius (optional), and a rolling time window
- Handles pagination (continuation token first, page fallback)
- Writes events.json even on errors (with {"error": "..."} included)
- ALWAYS exits 0 so the workflow never blocks your pipeline
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# ---------- Config helpers ----------

def env_list(*names, sep=",", default=None):
    """Return the first non-empty env value parsed as a list"""
    for n in names:
        v = os.getenv(n)
        if v:
            return [s.strip() for s in v.split(sep) if s.strip()]
    return default[:] if default else []

def env_int(*names, default=None):
    for n in names:
        v = os.getenv(n)
        if v and v.isdigit():
            return int(v)
    return default

def iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

# ---------- Inputs (with sensible defaults) ----------

DEFAULT_KEYWORDS = [
    "steampunk", "gaslamp", "aether", "victorian",
    "tesla", "edison", "renaissance", "faire"
]

KEYWORDS = env_list("KEYWORDS", "INPUT_KEYWORDS", "EVENTBRITE_KEYWORDS", default=DEFAULT_KEYWORDS)
CITY      = os.getenv("CITY") or os.getenv("INPUT_CITY") or None
RADIUS_MI = env_int("WITHIN_MILES", "INPUT_WITHIN_MILES", default=None)
WINDOW_DAYS = env_int("WINDOW_DAYS", "INPUT_WINDOW_DAYS", default=150)

TOKEN = os.getenv("EVENTBRITE_TOKEN")  # <-- set this as a repo secret

# ---------- Query construction ----------

BASE = "https://www.eventbriteapi.com/v3/events/search/"

def build_params(start_iso, end_iso, continuation=None, page=None):
    # Only include params when they have values (prevents duplicates / 404s)
    params = {
        "q": " ".join(KEYWORDS),
        "start_date.range_start": start_iso,
        "start_date.range_end": end_iso,
        "expand": "venue,organizer",
        "sort_by": "date",
    }
    if CITY:
        params["location.address"] = CITY
    if RADIUS_MI:
        params["location.within"] = f"{RADIUS_MI}mi"
    if continuation:
        params["continuation"] = continuation
    elif page:
        params["page"] = page
    return params

def api_get(url, headers):
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ---------- Harvest ----------

def harvest_now():
    meta = {
        "ts_utc": iso_utc(datetime.now(timezone.utc)),
        "city": CITY,
        "within_miles": RADIUS_MI,
        "window_days": WINDOW_DAYS,
        "keywords": KEYWORDS,
    }
    out = {"meta": meta, "events": []}

    if not TOKEN:
        out["error"] = "Missing EVENTBRITE_TOKEN secret."
        return out

    end   = datetime.now(timezone.utc) + timedelta(days=WINDOW_DAYS)
    start = datetime.now(timezone.utc)
    start_iso = iso_utc(start)
    end_iso   = iso_utc(end)

    headers = {"Authorization": f"Bearer {TOKEN}"}
    continuation = None
    page = 1
    page_count = 0

    try:
        while True:
            params = build_params(start_iso, end_iso, continuation=continuation, page=None if continuation else page)
            url = BASE + "?" + urlencode(params)
            print(f"[harvest] GET {url}")  # visible in Actions logs

            data = api_get(url, headers=headers)

            # Collect events (guard if key missing)
            events = data.get("events", [])
            out["events"].extend(events)

            # Pagination handling (prefer continuation token)
            pg = data.get("pagination", {}) or {}
            has_more = pg.get("has_more_items") or False
            continuation = pg.get("continuation")

            page_count += 1
            print(f"[harvest] page #{page_count}, received {len(events)} events, has_more={has_more}, continuation={bool(continuation)}")

            if continuation:
                # next loop with continuation
                continue
            if has_more:
                # fallback to numeric page if API still indicates more
                page += 1
                continue
            break

        # Light summary to logs
        print(f"[harvest] total events: {len(out['events'])}")

    except HTTPError as e:
        # Read response body for debugging when possible
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        out["error"] = f"HTTPError {e.code}: {e.reason}; body={body[:300]}"
        print(f"[harvest][HTTPError] {out['error']}")
    except URLError as e:
        out["error"] = f"URLError: {e.reason}"
        print(f"[harvest][URLError] {out['error']}")
    except Exception as e:
        out["error"] = f"Exception: {e.__class__.__name__}: {e}"
        print(f"[harvest][Exception] {out['error']}")

    return out

# ---------- Write & exit ----------

def main():
    result = harvest_now()
    # Always write events.json so the artifact step can grab it
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    # Keep workflow green (we already embed any errors in the file/logs)
    sys.exit(0)

if __name__ == "__main__":
    main()
