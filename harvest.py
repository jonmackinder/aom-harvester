#!/usr/bin/env python3
"""
Harvester: builds a JSON file of upcoming events.

✅ Works in GitHub Actions (no third-party packages).
✅ Reads public ICS calendar feeds (URLs in ICS_FEEDS env, comma-separated).
✅ Keyword filtering (KEYWORDS env, comma-separated; case-insensitive).
✅ Time window filtering (WINDOW_DAYS env; defaults safely to 180 even if blank).
✅ Never fails the workflow on “no data” – still writes a valid JSON file.
"""

from __future__ import annotations

import os
import sys
import json
import re
import io
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

# ---------- small helpers ----------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def clean_int_env(name: str, default: int) -> int:
    """
    Read an int env var safely. Treats unset, empty, or invalid as default.
    (Fix for the "" -> ValueError crash you hit earlier.)
    """
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

def list_from_env(name: str) -> List[str]:
    """
    Split a comma/semicolon/newline separated env var into a list of strings.
    Trims whitespace and drops empties.
    """
    raw = os.getenv(name) or ""
    parts = re.split(r"[,\n;]+", raw)
    return [p.strip() for p in parts if p.strip()]

def safe_getenv(name: str) -> Optional[str]:
    val = os.getenv(name)
    if val is None:
        return None
    val = val.strip()
    return val or None

def log(msg: str) -> None:
    print(f"[harvest] {msg}", flush=True)

# ---------- ICS parsing (no third-party deps) ----------

_ICS_EVENT_SPLIT = re.compile(r"(?m)^BEGIN:VEVENT\r?$")
_ICS_KV = re.compile(r"(?m)^([A-Z]+)(;[^:]+)?:\s*(.+?)\s*$")
_ICS_FOLDED = re.compile(r"(?m)\r?\n[ \t]")  # unfold folded lines

def _unfold(text: str) -> str:
    return _ICS_FOLDED.sub("", text)

def _parse_ics_datetime(val: str) -> Optional[datetime]:
    """
    Supports common forms:
      - 20250130T170000Z
      - 20250130T170000 (floating; assume UTC)
      - 20250130 (all-day; treat as start of day UTC)
    """
    val = val.strip()
    try:
        if val.endswith("Z"):
            return datetime.strptime(val, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if "T" in val:
            # floating time – assume UTC for CI consistency
            return datetime.strptime(val, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        # date only
        return datetime.strptime(val, "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_ics_events(text: str) -> List[Dict[str, Any]]:
    text = _unfold(text)
    # Split into event blocks (skip preamble)
    blocks = _ICS_EVENT_SPLIT.split(text)
    if not blocks:
        return []
    events: List[Dict[str, Any]] = []
    for block in blocks[1:]:
        # Extract key fields
        fields: Dict[str, str] = {}
        for m in _ICS_KV.finditer(block):
            k = m.group(1).upper()
            v = m.group(3).strip()
            # Keep the last occurrence of a key
            fields[k] = v
        start = _parse_ics_datetime(fields.get("DTSTART", ""))
        end = _parse_ics_datetime(fields.get("DTEND", "")) or start
        title = fields.get("SUMMARY", "").strip()
        url = fields.get("URL", "").strip()
        loc = fields.get("LOCATION", "").strip()
        desc = fields.get("DESCRIPTION", "").strip()

        # Skip if we don't at least have a start or a title
        if not (start or title):
            continue

        events.append({
            "title": title or "(untitled)",
            "start_utc": start.isoformat() if start else None,
            "end_utc": end.isoformat() if end else None,
            "location": loc or None,
            "url": url or None,
            "description": desc or None,
            "source": "ics"
        })
    return events

def fetch_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "aom-harvester/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    # try utf-8 first, fall back to latin-1
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore")

# ---------- main harvesting ----------

def within_window(dt_iso: Optional[str], start: datetime, end: datetime) -> bool:
    if not dt_iso:
        return False
    try:
        dt = datetime.fromisoformat(dt_iso)
    except ValueError:
        return False
    return start <= dt <= end

def keyword_ok(title: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    text = (title or "").lower()
    return any(k.lower() in text for k in keywords)

def harvest_from_ics(feeds: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for url in feeds:
        try:
            log(f"Fetching ICS: {url}")
            txt = fetch_text(url)
            evs = parse_ics_events(txt)
            for e in evs:
                e = dict(e)
                e["source"] = f"ics:{url}"
                events.append(e)
        except Exception as exc:
            log(f"WARNING: failed ICS fetch/parse: {url} ({exc})")
    return events

def main() -> int:
    # ----- configuration from environment -----
    KEYWORDS = list_from_env("KEYWORDS")
    WINDOW_DAYS = clean_int_env("WINDOW_DAYS", 180)   # <— safe defaulting
    ICS_FEEDS = list_from_env("ICS_FEEDS")

    # Optional location filters (not applied to ICS unless present in text)
    CITY = safe_getenv("CITY")
    STATE = safe_getenv("STATE")
    COUNTRY = safe_getenv("COUNTRY")
    WITHIN_MILES = clean_int_env("WITHIN_MILES", 0) if safe_getenv("WITHIN_MILES") else None

    out_name = safe_getenv("OUTFILE") or "aom-events.json"

    log(f"Start — window_days={WINDOW_DAYS}, keywords={KEYWORDS or '—'}, ics_feeds={len(ICS_FEEDS)}")

    start = now_utc()
    end = start + timedelta(days=WINDOW_DAYS)

    # ----- collect -----
    all_events: List[Dict[str, Any]] = []

    # ICS feeds (if any)
    if ICS_FEEDS:
        all_events.extend(harvest_from_ics(ICS_FEEDS))
    else:
        log("No ICS_FEEDS provided; skipping ICS harvest.")

    # ----- filter: keywords + time window -----
    filtered: List[Dict[str, Any]] = []
    for e in all_events:
        if not within_window(e.get("start_utc"), start, end):
            continue
        if not keyword_ok(e.get("title", ""), KEYWORDS):
            continue
        filtered.append(e)

    # ----- build output -----
    payload: Dict[str, Any] = {
        "meta": {
            "ts_utc": now_utc().isoformat(),
            "keywords": KEYWORDS,
            "city": CITY,
            "state": STATE,
            "country": COUNTRY,
            "within_miles": WITHIN_MILES,
            "window_days": WINDOW_DAYS,
            "sources": ["ics"] if ICS_FEEDS else [],
            "count": len(filtered),
        },
        "events": filtered,
        "notes": []
    }

    if not ICS_FEEDS:
        payload["notes"].append("No ICS_FEEDS provided.")
    if not filtered and all_events:
        payload["notes"].append("No events matched filters (time window and/or keywords).")
    if not all_events and ICS_FEEDS:
        payload["notes"].append("ICS feeds fetched but no events were parsed.")

    # ----- write file -----
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f"Wrote {out_name} with {len(filtered)} events (from {len(all_events)} raw).")
    # Keep the job green even if zero events
    return 0

if __name__ == "__main__":
    sys.exit(main())
