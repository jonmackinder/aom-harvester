#!/usr/bin/env python3
"""
AOM Harvester v1 — ICS-first, bulletproof

- Reads ICS calendar feeds and outputs normalized events
- No external paid tokens required
- Always writes events.json / events.csv / events.md and exits 0

ENV (all optional):
  ICS_FEEDS       comma-separated ICS URLs
  FEEDS_FILE      path to a text file with one ICS URL per line (default: feeds.txt)
  KEYWORDS        comma-separated keywords to match (case-insensitive)
  WINDOW_DAYS     days in future to include (default 180)
  USE_DEMO_FEED   "1" to include demo ICS on first run (default 1)

Artifacts:
  events.json  — { meta, events[], errors[] }
  events.csv   — flat export
  events.md    — pretty table for quick viewing
"""

import os, sys, csv, json, re
from datetime import datetime, timedelta, timezone, date
from urllib.parse import urlparse
import requests
from icalendar import Calendar, Event
from dateutil import tz

OUT_JSON = "events.json"
OUT_CSV  = "events.csv"
OUT_MD   = "events.md"

DEMO_FEEDS = [
    # Demo ICS to prove pipeline on first run; replace with your real feeds.
    # You can remove this by setting USE_DEMO_FEED=0 in the workflow env.
    "https://www.calendarlabs.com/ical-calendar/ics/76/US_Holidays.ics"
]

def now_utc():
    return datetime.now(timezone.utc)

def iso_utc(dt):
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    elif isinstance(dt, date):
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    return None

def coerce_dt(value):
    """
    Accepts icalendar property .dt which can be date or datetime (tz-aware or naive).
    Returns timezone-aware UTC datetime.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, 9, 0, 0)  # assume 9am local for all-day
    else:
        return None

    if dt.tzinfo is None:
        # assume local if naive; convert to UTC
        dt = dt.replace(tzinfo=tz.tzlocal())
    return dt.astimezone(timezone.utc)

def read_env_list(name, default=None):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default[:] if default else []
    return [s.strip() for s in raw.split(",") if s.strip()]

def load_feeds():
    feeds = []
    # 1) From env
    feeds += read_env_list("ICS_FEEDS", [])
    # 2) From file (one URL per line)
    feeds_file = os.getenv("FEEDS_FILE", "feeds.txt")
    if os.path.exists(feeds_file):
        with open(feeds_file, "r", encoding="utf-8") as f:
            for line in f:
                u = line.strip()
                if u and not u.startswith("#"):
                    feeds.append(u)
    # 3) Demo feeds (first run convenience)
    use_demo = os.getenv("USE_DEMO_FEED", "1").strip() != "0"
    if use_demo and not feeds:
        feeds += DEMO_FEEDS
    # Unique while preserving order
    seen = set()
    uniq = []
    for u in feeds:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
    return uniq

def fetch_ics(url, timeout=30):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def parse_ics(text):
    cal = Calendar.from_ical(text)
    events = []
    for comp in cal.walk():
        if comp.name != "VEVENT":
            continue
        summary = str(comp.get("summary", "") or "")
        description = str(comp.get("description", "") or "")
        location = str(comp.get("location", "") or "")
        url = str(comp.get("url", "") or "")
        dtstart = comp.get("dtstart")
        dtend   = comp.get("dtend")

        start = coerce_dt(dtstart.dt if hasattr(dtstart, "dt") else dtstart)
        end   = coerce_dt(dtend.dt if hasattr(dtend, "dt") else dtend)

        events.append({
            "title": summary.strip(),
            "description": description.strip(),
            "location": location.strip(),
            "url": url.strip(),
            "start_utc": iso_utc(start) if start else None,
            "end_utc": iso_utc(end) if end else None,
        })
    return events

def filter_window(events, start_utc, end_utc):
    keep = []
    for e in events:
        s = e.get("start_utc")
        if not s:
            continue
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            continue
        if start_utc <= dt <= end_utc:
            keep.append(e)
    return keep

def filter_keywords(events, keywords):
    if not keywords:
        return events
    pat = re.compile("|".join([re.escape(k) for k in keywords]), re.IGNORECASE)
    out = []
    for e in events:
        hay = " ".join([
            e.get("title",""),
            e.get("description",""),
            e.get("location",""),
        ])
        if pat.search(hay):
            out.append(e)
    return out

def normalize(events, feed_url):
    host = urlparse(feed_url).netloc
    out = []
    for e in events:
        out.append({
            "id": f"ics:{host}:{(e.get('title') or '')[:64]}:{e.get('start_utc')}",
            "title": e.get("title"),
            "start_utc": e.get("start_utc"),
            "end_utc": e.get("end_utc"),
            "city": e.get("location") or None,
            "venue": None,
            "url": e.get("url") or feed_url,
            "organizer": host,
            "tags": ["ics"],
        })
    return out

def dedupe(events):
    seen = set()
    out = []
    for e in events:
        key = (e.get("title","").strip().lower(), e.get("start_utc"), e.get("city"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out

def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def write_csv(path, events):
    header = ["id","title","start_utc","end_utc","city","venue","url","organizer","tags"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for e in events:
            w.writerow([
                e.get("id"), e.get("title"), e.get("start_utc"), e.get("end_utc"),
                e.get("city"), e.get("venue"), e.get("url"), e.get("organizer"),
                ",".join(e.get("tags") or []),
            ])

def write_md(path, events):
    cols = ["Title","Start (UTC)","City","URL","Organizer"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("|" + "|".join(["---"]*len(cols)) + "|\n")
        for e in events:
            title = e.get("title") or ""
            start = e.get("start_utc") or ""
            city  = e.get("city") or ""
            url   = e.get("url") or ""
            org   = e.get("organizer") or ""
            # Simple escape for pipes
            title = title.replace("|","/")
            city  = city.replace("|","/")
            org   = org.replace("|","/")
            f.write(f"| {title} | {start} | {city} | {url} | {org} |\n")

def main():
    # config from env (safe defaults)
    raw_days = os.getenv("WINDOW_DAYS", "").strip()
    window_days = int(raw_days) if raw_days.isdigit() else 180

    start = now_utc()
    end = start + timedelta(days=window_days)

    for u in feeds:
        try:
            print(f"[harvest] fetching ICS: {u}")
            text = fetch_ics(u)
            raw  = parse_ics(text)
            raw  = filter_window(raw, start, end)
            raw  = filter_keywords(raw, keywords)
            norm = normalize(raw, u)
            all_events.extend(norm)
            print(f"[harvest] ...ok: +{len(norm)} events")
        except Exception as ex:
            msg = f"{type(ex).__name__}: {ex}"
            print(f"[harvest] ERROR {u}: {msg}")
            errors.append({"source": u, "message": msg})

    all_events = dedupe(all_events)

    payload = {
        "meta": {
            "ts_utc": iso_utc(start),
            "window_days": window_days,
            "keywords": keywords,
            "feeds_count": len(feeds),
            "events_count": len(all_events),
        },
        "events": all_events,
        "errors": errors,
    }

    # Write artifacts
    write_json(OUT_JSON, payload)
    write_csv(OUT_CSV, all_events)
    write_md(OUT_MD, all_events)

    print(f"SUMMARY: feeds={len(feeds)} found={len(all_events)} errors={len(errors)}")
    # Always exit green so CI never blocks
    sys.exit(0)

if __name__ == "__main__":
    main()
