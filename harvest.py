"""
Harvester (API-free starter)

- Reads inputs from env (set in your Actions workflow)
- Builds a stable JSON payload: { meta, events, notes }
- NEVER fails your CI: writes events.json and exits 0
- Stubs for future feeds (Meetup/Eventbrite/etc.)

You can safely run this from GitHub Actions.
"""

import os, sys, json, time
from datetime import datetime, timedelta, timezone

# ---------- small helpers ----------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()

def getenv_str(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if v is not None else default

def getenv_int(name: str, default: int) -> int:
    raw = getenv_str(name, "")
    try:
        return int(raw)
    except Exception:
        return default

def parse_keywords(raw: str) -> list[str]:
    if not raw:
        return []
    # Allow comma or newline separated
    parts = [p.strip() for p in raw.replace("\n", ",").split(",")]
    return [p for p in parts if p]

def write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def log(msg: str) -> None:
    print(msg, flush=True)

# ---------- “feeds” (safe stubs) ----------

def fetch_stub_keywords(keywords: list[str], start: datetime, end: datetime) -> list[dict]:
    """
    Offline, API-free placeholder feed.
    If you gave keywords, we create a single “todo” event showing the query.
    Otherwise, returns [].
    """
    if not keywords:
        return []
    title = f"Search placeholder for: {', '.join(keywords[:6])}"
    return [{
        "source": "stub",
        "id": f"stub-{int(time.time())}",
        "title": title,
        "start_utc": iso(start + timedelta(days=7, hours=19)),  # one week out, 7pm UTC
        "end_utc":   iso(start + timedelta(days=7, hours=21)),
        "url": "",
        "city": getenv_str("CITY", "") or None,
        "notes": "Stub event to prove pipeline. Replace with real feed later."
    }]

def fetch_meetup_placeholder(*args, **kwargs) -> list[dict]:
    """
    Placeholder that does NOTHING (no paid API). Kept for future wiring.
    """
    return []

def fetch_eventbrite_placeholder(*args, **kwargs) -> list[dict]:
    """
    Placeholder (Eventbrite v3 search is gone). No network call here.
    """
    return []

# Map feed name -> function (easy to extend later)
FEEDS = {
    "stub": fetch_stub_keywords,
    "meetup": fetch_meetup_placeholder,
    "eventbrite": fetch_eventbrite_placeholder,
}

# ---------- main ----------

def main() -> int:
    # Inputs (match your workflow defaults but tolerate empties)
    city         = getenv_str("CITY") or None
    within_miles = getenv_int("WITHIN_MILES", 0) or None
    window_days  = getenv_int("WINDOW_DAYS", 180)
    keywords_raw = getenv_str("KEYWORDS")
    keywords     = parse_keywords(keywords_raw)

    start = now_utc()
    end   = start + timedelta(days=window_days)

    # Choose which feeds to run (safe, non-paid only)
    feeds_to_run = ["stub"]  # add "meetup" or others later when ready

    all_events: list[dict] = []
    notes: list[str] = []

    log("----- Harvester starting -----")
    log(f"Window: {iso(start)} -> {iso(end)} ({window_days} days)")
    log(f"City: {city or '-'}  Within miles: {within_miles or '-'}")
    log(f"Keywords: {keywords if keywords else '-'}")
    log(f"Feeds: {feeds_to_run}")

    for feed in feeds_to_run:
        fn = FEEDS.get(feed)
        if not fn:
            notes.append(f"Unknown feed '{feed}' – skipped.")
            continue
        try:
            log(f"Running feed: {feed}")
            if feed == "stub":
                events = fn(keywords, start, end)
            else:
                events = fn(keywords, start, end)  # same signature for future
            if events:
                log(f"  -> {len(events)} event(s)")
                all_events.extend(events)
            else:
                log("  -> 0 events")
        except Exception as e:
            notes.append(f"Feed '{feed}' error: {repr(e)} (skipped)")
            # continue safely

    # Build output
    payload = {
        "meta": {
            "ts_utc": iso(start),
            "city": city,
            "within_miles": within_miles,
            "window_days": window_days,
            "keywords": keywords,
        },
        "events": all_events,
        "notes": notes or [
            "API-free placeholder run. Replace stub feed with real connectors when ready."
        ],
    }

    # Always write – even if zero events – so CI stays green and artifact exists
    out_path = "events.json"
    write_json(out_path, payload)
    log(f"Wrote {out_path} ({len(json.dumps(payload))} bytes)")
    log("----- Harvester complete -----")

    # Always succeed
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        raise
    except Exception as e:
        # Last-resort safety: still write a minimal file and exit 0
        fallback = {
            "meta": {"ts_utc": iso(now_utc())},
            "events": [],
            "notes": [f"Unexpected error – wrote fallback file: {repr(e)}"],
        }
        try:
            write_json("events.json", fallback)
            print("Wrote fallback events.json")
        except Exception as inner:
            print(f"Failed to write fallback file: {inner}")
        sys.exit(0)
