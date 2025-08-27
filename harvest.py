"""
AOM Harvester (HTML + ICS) with strict timeouts and fast-fail behavior.

- Never hangs: all network calls use short timeouts + tiny retry.
- Always writes a JSON artifact: aom-events.json
- Inputs via env: KEYWORDS, CITY, STATE, COUNTRY, WITHIN_MILES, WINDOW_DAYS, ICS_FEEDS
"""

from __future__ import annotations
import os, sys, json, time, re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import List, Dict, Any

# --- Tunables ---------------------------------------------------------------
REQ_TIMEOUT = 12         # seconds per HTTP request (hard limit)
REQ_RETRIES = 1          # minimal retry so we fail fast but not flaky
GLOBAL_SOFT_TIME = 240   # seconds soft budget for the whole run (job has 5m hard timeout)
USER_AGENT = "AOMHarvester/1.0 (+github actions)"

# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def env_str(name: str, default: str = "") -> str:
    val = os.getenv(name, "").strip()
    return val if val else default

def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw)
    except Exception:
        return default

def split_list(s: str) -> List[str]:
    if not s:
        return []
    # split by commas or newlines, trim blanks
    parts = re.split(r"[,\n]+", s)
    return [p.strip() for p in parts if p.strip()]

# --- Safe HTTP fetch with timeout + tiny retry -----------------------------
def http_get(url: str) -> tuple[int, str] | tuple[None, None]:
    import requests
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    last_exc = None
    for attempt in range(REQ_RETRIES + 1):
        try:
            r = requests.get(url, headers=headers, timeout=REQ_TIMEOUT)
            return r.status_code, r.text
        except Exception as e:
            last_exc = e
            time.sleep(0.5)
    # failed
    return None, None

# --- ICS ingestion ----------------------------------------------------------
def parse_ics_feed(url: str, window_days: int) -> List[Dict[str, Any]]:
    """Parse a single ICS feed URL into our normalized event dicts."""
    from ics import Calendar
    events: List[Dict[str, Any]] = []
    code, text = http_get(url)
    if code is None or not text:
        return events

    try:
        cal = Calendar(text)
    except Exception:
        return events

    cutoff_end = now_utc() + timedelta(days=window_days)
    cutoff_start = now_utc() - timedelta(days=1)

    def to_iso(dt):
        if dt is None:
            return None
        if getattr(dt, "tzinfo", None) is None:
            # assume UTC if naive
            return dt.replace(tzinfo=timezone.utc).isoformat()
        return dt.astimezone(timezone.utc).isoformat()

    for ev in cal.events:
        # Some ICS have no times; guard it
        try:
            start = ev.begin.datetime if hasattr(ev, "begin") else None
            end   = ev.end.datetime   if hasattr(ev, "end")   else None
        except Exception:
            start = end = None

        # Window filter (if dates exist)
        if start and (start < cutoff_start or start > cutoff_end):
            continue

        events.append({
            "source": "ics",
            "source_url": url,
            "title": getattr(ev, "name", None),
            "description": getattr(ev, "description", None),
            "start": to_iso(start),
            "end": to_iso(end),
            "location": getattr(ev, "location", None),
            "all_day": bool(getattr(ev, "all_day", False)),
            "uid": getattr(ev, "uid", None),
        })
    return events

# --- Extremely conservative HTML “searchers” (non-blocking) ----------------
# These are placeholders that return quickly with timeouts;
# enable/extend later when we have stable selectors.
def html_search_eventbrite(keyword: str, city: str, state: str, country: str) -> List[Dict[str, Any]]:
    # Disabled by default to avoid rate-limits / fragile scraping.
    return []

def html_search_tickettailor(keyword: str, city: str, state: str, country: str) -> List[Dict[str, Any]]:
    return []

# --- Main -------------------------------------------------------------------
def main():
    soft_deadline = time.time() + GLOBAL_SOFT_TIME

    keywords = split_list(env_str("KEYWORDS", "steampunk,victorian,renaissance,faire,aether,tesla,edison"))
    city     = env_str("CITY")
    state    = env_str("STATE")
    country  = env_str("COUNTRY")
    within   = env_str("WITHIN_MILES")  # not used yet, reserved
    window_days = env_int("WINDOW_DAYS", 180)

    ics_feeds = split_list(env_str("ICS_FEEDS"))

    meta: Dict[str, Any] = {
        "ts_utc": now_utc().isoformat(),
        "keywords": keywords,
        "city": city or None,
        "state": state or None,
        "country": country or None,
        "within_miles": int(within) if within.isdigit() else None,
        "window_days": window_days,
        "sources": ["ics" if ics_feeds else None, "eventbrite_html", "tickettailor_html"],
    }
    # remove None entries from sources
    meta["sources"] = [s for s in meta["sources"] if s]

    out: Dict[str, Any] = {"meta": meta, "events": [], "notes": []}

    # 1) ICS feeds (fast, reliable)
    for url in ics_feeds:
        if time.time() > soft_deadline:
            out["notes"].append("Soft time budget exhausted during ICS fetch.")
            break
        try:
            out["events"].extend(parse_ics_feed(url, window_days))
        except Exception as e:
            out["notes"].append(f"ICS error: {url} :: {type(e).__name__}")

    # 2) Lightweight HTML attempts (kept super conservative; return quickly)
    def guard_time():
        if time.time() > soft_deadline:
            out["notes"].append("Soft time budget exhausted during HTML search.")
            return False
        return True

    for kw in (keywords or []):
        if not guard_time(): break
        try:
            out["events"].extend(html_search_eventbrite(kw, city, state, country))
        except Exception as e:
            out["notes"].append(f"eventbrite_html '{kw}' :: {type(e).__name__}")

        if not guard_time(): break
        try:
            out["events"].extend(html_search_tickettailor(kw, city, state, country))
        except Exception as e:
            out["notes"].append(f"tickettailor_html '{kw}' :: {type(e).__name__}")

    # Deduplicate simple (by title+start)
    seen = set()
    unique = []
    for ev in out["events"]:
        key = (ev.get("title"), ev.get("start"))
        if key in seen: 
            continue
        seen.add(key)
        unique.append(ev)
    out["events"] = unique
    out["meta"]["count"] = len(unique)

    # Always write the artifact
    with open("aom-events.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Exit 0 so the workflow stays green but still uploads notes/errors
    return 0

if __name__ == "__main__":
    sys.exit(main())
