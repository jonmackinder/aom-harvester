#!/usr/bin/env python3
"""
HTML harvester for steampunk events.

- Runs happily inside GitHub Actions (no JS, no headless browser)
- Scrapes Eventbrite and TicketTailor public HTML with broad selectors
- Never hard-fails: always writes a JSON artifact so the workflow stays green
- Tunable via environment variables (see ENV section below)
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Iterable, Tuple, Optional

import requests
from bs4 import BeautifulSoup

# -----------------------
# ENV (all optional)
# -----------------------
KEYWORDS = [
    k.strip() for k in os.getenv(
        "KEYWORDS",
        "steampunk,victorian,renaissance,faire,aether,tesla,edison"
    ).split(",") if k.strip()
]

CITY = os.getenv("CITY", "").strip() or None         # e.g. "san-francisco"
STATE = os.getenv("STATE", "").strip() or None       # e.g. "ca"
COUNTRY = os.getenv("COUNTRY", "").strip() or "united-states"
WITHIN_MILES = os.getenv("WITHIN_MILES", "").strip() or None
WINDOW_DAYS = int(os.getenv("WINDOW_DAYS", "180"))

SOURCES = [s.strip() for s in os.getenv(
    "SOURCES",
    "eventbrite_html,tickettailor_html"
).split(",") if s.strip()]

OUTFILE = os.getenv("OUTFILE", "aom-events.json")

# Networking
TIMEOUT = float(os.getenv("TIMEOUT", "12"))
RETRIES = int(os.getenv("RETRIES", "2"))
SLEEP_BETWEEN = float(os.getenv("SLEEP_BETWEEN", "0.6"))

HEADERS = {
    "User-Agent": os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 (+AOM Harvester)"
    ),
    "Accept-Language": "en-US,en;q=0.8",
}


# -----------------------
# Helpers
# -----------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def http_get(url: str) -> Optional[str]:
    """GET with tiny retry loop; returns text or None."""
    for i in range(1, RETRIES + 2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.text:
                return r.text
            # Treat 404/403 as final, others retry once or twice.
            if r.status_code in (403, 404):
                return None
        except requests.RequestException:
            pass
        time.sleep(SLEEP_BETWEEN * i)
    return None


DATE_RE = re.compile(
    r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*)?"
    r"(?:\b\d{1,2}\s*(?:AM|PM)\b|\b\d{1,2}:\d{2}\s*(?:AM|PM)\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}(?:,\s*\d{4})?)",
    re.I
)


def extract_nearby_date(elem: Any) -> Optional[str]:
    """
    Heuristic: search up the DOM for a <time> tag or any text that looks like a date/time.
    """
    # 1) Direct time tags
    nearest = elem
    for _ in range(3):  # check elem, parent, grandparent
        if not nearest:
            break
        # <time datetime="...">
        for t in nearest.find_all("time"):
            if t.get("datetime"):
                return t.get("datetime").strip()
            if t.text and DATE_RE.search(t.text):
                return t.text.strip()
        # Any texty node that looks date-ish
        txt = nearest.get_text(" ", strip=True)
        if txt:
            m = DATE_RE.search(txt)
            if m:
                return m.group(0).strip()
        nearest = nearest.parent
    return None


def dedupe(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for ev in events:
        key = hashlib.sha256(ev.get("link", "").encode("utf-8")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


# -----------------------
# Eventbrite (HTML) scrapes
# -----------------------
def eventbrite_search_urls(keyword: str) -> List[str]:
    """
    Build several HTML-only search pages that render without JS.
    We try progressively more general URLs.
    """
    urls = []

    # City-scoped (if provided)
    if CITY and STATE:
        urls.append(f"https://www.eventbrite.com/d/{STATE}--{CITY}/{keyword}/")
    # Country-scoped
    if COUNTRY:
        urls.append(f"https://www.eventbrite.com/d/{COUNTRY}/{keyword}/")
    # Online catch-all
    urls.append(f"https://www.eventbrite.com/d/online/{keyword}/")
    # Very broad catch-all
    urls.append(f"https://www.eventbrite.com/d/{keyword}/")
    return urls


def parse_eventbrite_html(html: str) -> List[Dict[str, Any]]:
    """
    Very broad extraction:
    - any <a> whose href contains '/e/' (Eventbrite event detail pages)
    - title is the link text; date pulled from nearby nodes
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/e/" not in href:
            continue
        # Normalize absolute link
        if href.startswith("/"):
            href = "https://www.eventbrite.com" + href
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        date_text = extract_nearby_date(a)
        out.append({
            "title": title,
            "link": href,
            "date": date_text,
            "source": "eventbrite_html",
        })
    return out


def harvest_eventbrite(keyword: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    notes = []
    events = []
    for url in eventbrite_search_urls(keyword):
        html = http_get(url)
        if not html:
            notes.append(f"eventbrite: no HTML for {url}")
            continue
        found = parse_eventbrite_html(html)
        if found:
            notes.append(f"eventbrite: {len(found)} links from {url}")
            events.extend(found)
        else:
            notes.append(f"eventbrite: 0 links from {url}")
    return events, notes


# -----------------------
# TicketTailor (HTML) scrapes
# -----------------------
def tickettailor_search_urls(keyword: str) -> List[str]:
    """
    TicketTailor doesn't have a single canonical public search URL that always SSRs,
    so we try a few discover pages that commonly list events by text.
    """
    return [
        f"https://www.tickettailor.com/events/search/?q={keyword}",
        f"https://www.tickettailor.com/browse/?q={keyword}",
    ]


def parse_tickettailor_html(html: str) -> List[Dict[str, Any]]:
    """
    Broad extraction for TicketTailor:
    - any <a> whose href contains '/events/' or '/event/'
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/events/" not in href and "/event/" not in href:
            continue
        if href.startswith("/"):
            href = "https://www.tickettailor.com" + href
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        date_text = extract_nearby_date(a)
        out.append({
            "title": title,
            "link": href,
            "date": date_text,
            "source": "tickettailor_html",
        })
    return out


def harvest_tickettailor(keyword: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    notes = []
    events = []
    for url in tickettailor_search_urls(keyword):
        html = http_get(url)
        if not html:
            notes.append(f"tickettailor: no HTML for {url}")
            continue
        found = parse_tickettailor_html(html)
        if found:
            notes.append(f"tickettailor: {len(found)} links from {url}")
            events.extend(found)
        else:
            notes.append(f"tickettailor: 0 links from {url}")
    return events, notes


# -----------------------
# Pipeline
# -----------------------
def within_window(date_text: Optional[str]) -> bool:
    """
    Very forgiving window filter: if we can parse a month/day from the string and
    infer a reasonable year, keep it when inside WINDOW_DAYS. If parsing fails,
    we keep the event (you can filter later).
    """
    if not date_text:
        return True  # keep unknown dates for manual review

    # Try a couple of simple parses.
    txt = date_text.strip()
    # 1) ISO-ish
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        return (dt - now_utc()).days <= WINDOW_DAYS
    except Exception:
        pass

    # 2) Month Day[, Year] patterns
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2}(?:,\s*(\d{4}))?", txt, re.I)
    if m:
        month = m.group(1)
        day = int(re.search(r"\d{1,2}", m.group(0)).group(0))
        year = int(m.group(2)) if m.group(2) else now_utc().year
        try:
            dt = datetime.strptime(f"{month} {day} {year}", "%b %d %Y").replace(tzinfo=timezone.utc)
            return (dt - now_utc()).days <= WINDOW_DAYS
        except Exception:
            return True  # if in doubt, keep
    return True


def run() -> Dict[str, Any]:
    notes: List[str] = []
    all_events: List[Dict[str, Any]] = []

    if not KEYWORDS:
        notes.append("No KEYWORDS provided; using default list.")

    for kw in KEYWORDS:
        kwq = kw.replace(" ", "-").lower()

        if "eventbrite_html" in SOURCES:
            evs, n = harvest_eventbrite(kwq)
            all_events.extend(evs)
            notes.extend(n)

        if "tickettailor_html" in SOURCES:
            evs, n = harvest_tickettailor(kwq)
            all_events.extend(evs)
            notes.extend(n)

        time.sleep(SLEEP_BETWEEN)

    # Deduplicate and filter by date window (lightly)
    all_events = dedupe(all_events)
    all_events = [e for e in all_events if within_window(e.get("date"))]

    payload: Dict[str, Any] = {
        "meta": {
            "ts_utc": now_utc().isoformat(),
            "keywords": KEYWORDS,
            "city": CITY,
            "state": STATE,
            "country": COUNTRY,
            "within_miles": WITHIN_MILES,
            "window_days": WINDOW_DAYS,
            "sources": SOURCES,
            "count": len(all_events),
        },
        "events": all_events,
        "notes": notes or ["ok"],
    }
    return payload


def main() -> None:
    data = {}
    try:
        data = run()
    except Exception as ex:
        # Never crash the workflow: emit a tiny diagnostic JSON instead.
        data = {
            "meta": {
                "ts_utc": now_utc().isoformat(),
                "keywords": KEYWORDS,
                "window_days": WINDOW_DAYS,
                "sources": SOURCES,
            },
            "events": [],
            "notes": [f"harvester error: {type(ex).__name__}: {ex}"],
        }
    with open(OUTFILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
