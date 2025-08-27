#!/usr/bin/env python3
"""
AOM Harvester — HTML + ICS (no paid APIs)

Sources (tonight):
  - Eventbrite search HTML (public pages)
  - TicketTailor search HTML (public pages)
  - Optional ICS feeds (if you add any URLs)

Inputs (env):
  KEYWORDS       comma list, e.g. "steampunk,victorian,renaissance,faire"
  CITY           optional city name (e.g., "Los Angeles")
  STATE          optional state/region code (e.g., "CA", "TX")
  COUNTRY        optional country (e.g., "US", "UK")
  WITHIN_MILES   optional radius miles (used in query text only)
  WINDOW_DAYS    days ahead window for ICS filtering (default 180)
  ICS_FEEDS      optional comma list of .ics URLs
  USER_AGENT     optional UA string to use for polite scraping

Behavior:
  - Scrapes public result pages with requests + BeautifulSoup (no headless browser).
  - Extracts: title, url, date text (best-effort), location text (best-effort).
  - Never invents events. If a source yields 0, it returns 0.
  - Writes aom-events.json and exits 0.

Note:
  - HTML structure may change; we log and keep going.
  - Dates from HTML are strings (we include raw text). ICS gives real timestamps.
"""

import os, sys, time, json, re
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# Optional ICS support
try:
    from icalendar import Calendar
    HAVE_ICS = True
except Exception:
    HAVE_ICS = False


# ------------------ helpers ------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")

def env_list(name: str) -> List[str]:
    raw = os.getenv(name, "") or ""
    if not raw.strip():
        return []
    # commas or whitespace
    parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
    # dedupe preserving order
    seen, out = set(), []
    for p in parts:
        pl = p.lower()
        if pl not in seen:
            seen.add(pl)
            out.append(p)
    return out

def getenv(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return (v.strip() if isinstance(v, str) else v) or default

def getenv_int(name: str, default: int) -> int:
    raw = getenv(name, "")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default

def pick_user_agent() -> str:
    return getenv("USER_AGENT", "AOM-Harvester/1.0 (+github-actions; polite; non-commercial)")

def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": pick_user_agent()})
    s.timeout = 20
    return s


# ------------------ model ------------------

@dataclass
class Event:
    id: str
    name: str
    url: str
    source: str
    date_text: Optional[str] = None
    city_text: Optional[str] = None
    starts_utc: Optional[str] = None
    ends_utc: Optional[str] = None
    venue: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ------------------ Eventbrite HTML ------------------

def eb_search_url(keywords: List[str], city: Optional[str], state: Optional[str], country: Optional[str]) -> str:
    """
    Eventbrite search URL pattern. Examples:
      https://www.eventbrite.com/d/ca--los-angeles/steampunk/
      https://www.eventbrite.com/d/united-states--california/steampunk/
      https://www.eventbrite.com/d/online/steampunk/   (fallback)
    """
    q = "-".join(k.lower() for k in keywords if k)
    if city and state:
        return f"https://www.eventbrite.com/d/{quote_plus(state.lower())}--{quote_plus(city.lower())}/{quote_plus(q)}/"
    if country and state:
        return f"https://www.eventbrite.com/d/{quote_plus(country.lower())}--{quote_plus(state.lower())}/{quote_plus(q)}/"
    if country:
        return f"https://www.eventbrite.com/d/{quote_plus(country.lower())}/{quote_plus(q)}/"
    return f"https://www.eventbrite.com/d/online/{quote_plus(q)}/"

def harvest_eventbrite_html(keywords: List[str], city: Optional[str], state: Optional[str], country: Optional[str]) -> List[Event]:
    url = eb_search_url(keywords, city, state, country)
    s = session()
    out: List[Event] = []
    try:
        resp = s.get(url, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Event cards commonly have data-spec="event-card__formatted"
        # We’ll be permissive: look for anchor cards with role/article-ish wrappers.
        cards = soup.select("a[href*='/e/'], article a[href*='/e/']")
        seen = set()
        for a in cards:
            href = a.get("href") or ""
            title = (a.get_text(" ", strip=True) or "").strip()
            if not href or not title:
                continue
            # crude de-dupe
            key = (href.split("?")[0], title.lower())
            if key in seen:
                continue
            seen.add(key)

            # Try to fetch adjacent date/location text in ancestor nodes
            date_text = None
            city_text = None
            parent = a.find_parent(["article", "div", "section"])
            if parent:
                # common date containers
                date_candidate = parent.select_one("[data-spec*='date'], time, .eds-text-bs--fixed")
                if date_candidate:
                    date_text = date_candidate.get_text(" ", strip=True) or None
                # location text
                loc_candidate = parent.find(string=re.compile(r"(?i)(location|venue|city)"))
                # fallback: look for small text below title
                if not loc_candidate:
                    small = parent.select_one("div, span")
                    if small:
                        txt = small.get_text(" ", strip=True)
                        if txt and len(txt) < 120 and re.search(r"[A-Za-z]", txt):
                            city_text = txt

            out.append(Event(
                id=f"eb:{len(out)+1}",
                name=title,
                url=href,
                source="eventbrite",
                date_text=date_text,
                city_text=city_text
            ))
        return out
    except Exception as e:
        print(f"[eventbrite] ERROR: {e}")
        return out  # empty
    finally:
        time.sleep(1.0)  # politeness


# ------------------ TicketTailor HTML ------------------

def tt_search_url(keywords: List[str], city: Optional[str]) -> str:
    q = "+".join(k for k in keywords if k)
    base = "https://www.tickettailor.com/events/search/"
    if city:
        return f"{base}?q={quote_plus(q)}+{quote_plus(city)}"
    return f"{base}?q={quote_plus(q)}"

def harvest_tickettailor_html(keywords: List[str], city: Optional[str]) -> List[Event]:
    url = tt_search_url(keywords, city)
    s = session()
    out: List[Event] = []
    try:
        resp = s.get(url, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Cards often under .event-card or links under a[href*='/events/']
        cards = soup.select("a[href*='/events/']")
        seen = set()
        for a in cards:
            href = a.get("href") or ""
            title = (a.get_text(" ", strip=True) or "").strip()
            if not href or not title:
                continue
            if not href.startswith("http"):
                href = "https://www.tickettailor.com" + href
            key = (href.split("?")[0], title.lower())
            if key in seen:
                continue
            seen.add(key)

            # Best-effort date/location from nearby text
            date_text = None
            city_text = None
            parent = a.find_parent(["article", "div", "section", "li"])
            if parent:
                # look for small/date spans
                small = parent.select_one("time, .tt-date, .small, .meta, .text-muted")
                if small:
                    date_text = small.get_text(" ", strip=True) or None
                loc = parent.find(string=re.compile(r"(?i)(venue|city|location)"))
                if not loc:
                    # alternative: next sibling text
                    sib = parent.find_next_sibling(["div","p","span"])
                    if sib:
                        stxt = sib.get_text(" ", strip=True)
                        if stxt and len(stxt) < 140:
                            city_text = stxt

            out.append(Event(
                id=f"tt:{len(out)+1}",
                name=title,
                url=href,
                source="tickettailor",
                date_text=date_text,
                city_text=city_text
            ))
        return out
    except Exception as e:
        print(f"[tickettailor] ERROR: {e}")
        return out
    finally:
        time.sleep(1.0)


# ------------------ ICS (optional) ------------------

def env_ics_urls() -> List[str]:
    raw = os.getenv("ICS_FEEDS", "") or ""
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    # de-dupe
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def harvest_ics(url: str, window_days: int) -> List[Event]:
    if not HAVE_ICS:
        return []
    out: List[Event] = []
    try:
        r = session().get(url, timeout=25)
        r.raise_for_status()
        cal = Calendar.from_ical(r.text)
        start = now_utc()
        end = start + timedelta(days=window_days)
        for comp in cal.walk():
            if comp.name != "VEVENT":
                continue
            title = str(comp.get("summary") or "").strip()
            href = (comp.get("url") or "").to_ical().decode("utf-8") if comp.get("url") else url
            loc  = str(comp.get("location") or "").strip() or None

            # start/end
            dtstart = comp.get("dtstart")
            dtend   = comp.get("dtend")
            def to_dt(x):
                if not x: return None
                val = getattr(x, "dt", x)
                if isinstance(val, datetime):
                    if val.tzinfo is None:  # naive → assume UTC
                        val = val.replace(tzinfo=timezone.utc)
                    return val.astimezone(timezone.utc)
                return None
            sdt = to_dt(dtstart)
            edt = to_dt(dtend)

            if sdt and not (start <= sdt <= end):
                continue

            out.append(Event(
                id=f"ics:{len(out)+1}",
                name=title or "(untitled)",
                url=href,
                source="ics",
                date_text=None,
                city_text=loc,
                starts_utc=iso_z(sdt) if sdt else None,
                ends_utc=iso_z(edt) if edt else None,
                venue=None
            ))
        return out
    except Exception as e:
        print(f"[ics] ERROR {url}: {e}")
        return out
    finally:
        time.sleep(0.5)


# ------------------ orchestrator ------------------

def main() -> int:
    keywords = env_list("KEYWORDS") or ["steampunk","victorian","renaissance","faire","aether","tesla","edison"]
    city     = getenv("CITY")
    state    = getenv("STATE")
    country  = getenv("COUNTRY")
    within   = getenv("WITHIN_MILES")  # only used for query text / later filters
    window_days = getenv_int("WINDOW_DAYS", 180)
    ics_urls = env_ics_urls()

    all_events: List[Event] = []
    notes: List[str] = []

    # HTML sources
    print("[harvest] Eventbrite HTML…")
    eb = harvest_eventbrite_html(keywords, city, state, country)
    print(f"[harvest]  -> {len(eb)} items")
    all_events.extend(eb)

    print("[harvest] TicketTailor HTML…")
    tt = harvest_tickettailor_html(keywords, city)
    print(f"[harvest]  -> {len(tt)} items")
    all_events.extend(tt)

    # ICS sources (optional)
    if ics_urls:
        print("[harvest] ICS feeds…")
        total_ics = 0
        for u in ics_urls:
            items = harvest_ics(u, window_days)
            print(f"[harvest]  {u} -> {len(items)}")
            all_events.extend(items); total_ics += len(items)
        notes.append(f"ICS feeds added: {len(ics_urls)} url(s), {total_ics} item(s).")
    else:
        notes.append("No ICS_FEEDS provided.")

    # De-dupe by (name,url)
    seen = set(); unique: List[Event] = []
    for e in all_events:
        k = (e.name.strip().lower(), e.url.split("?")[0])
        if k in seen: continue
        seen.add(k); unique.append(e)

    payload = {
        "meta": {
            "ts_utc": iso_z(now_utc()),
            "keywords": keywords,
            "city": city,
            "state": state,
            "country": country,
            "within_miles": within,
            "window_days": window_days,
            "sources": ["eventbrite_html","tickettailor_html"] + (["ics"] if ics_urls else []),
            "count": len(unique)
        },
        "events": [e.to_dict() for e in unique]
    }
    if notes:
        payload["notes"] = notes

    out = "aom-events.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"SUMMARY: found={len(unique)} sources={payload['meta']['sources']}")
    sys.stdout.flush()
    # Always succeed so CI stays green
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Last-ditch: write an empty but valid file
        fallback = {
            "meta": {"ts_utc": iso_z(now_utc()), "count": 0, "error": str(e)},
            "events": []
        }
        with open("aom-events.json", "w", encoding="utf-8") as f:
            json.dump(fallback, f, indent=2)
        print(f"[harvest] FATAL: {e}")
        sys.exit(0)
