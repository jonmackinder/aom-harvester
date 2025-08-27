# harvest.py
"""
AOM Event Harvester (API-agnostic tonight)
- Never fabricates events by default.
- If sources aren't configured, succeed with an empty list and a clear note.
- Can include real items from data/manual_events.json (optional).
- Optional STUB_EVENTS=true env will add obviously fake, time-warped records (disabled by default).
"""

import os, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ISO = "%Y-%m-%dT%H:%M:%S%z"

def now_utc():
    return datetime.now(timezone.utc)

def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "y", "on")

def env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw.strip() != "" else default
    except Exception:
        return default

def load_manual_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and "events" in payload and isinstance(payload["events"], list):
            return payload["events"]
        return []
    except Exception as e:
        return [{
            "id": "manual-parse-error",
            "name": "Manual events file parse error",
            "source": "manual",
            "error": str(e)
        }]

def very_obvious_stubs() -> list[dict]:
    # Only used if STUB_EVENTS=true. These are deliberately impossible.
    return [
        {
            "id": "stub-venus-1875",
            "name": "Victorian Ball — City of Brass (TEST ONLY)",
            "starts_utc": "1875-05-17T20:00:00+00:00",
            "ends_utc": "1875-05-18T02:00:00+00:00",
            "city": "Ishtar Terra",
            "venue": "Airship Pavilion, Venus",
            "url": "https://example.invalid/stub",
            "source": "stub"
        }
    ]

def main():
    # Inputs (safe defaults)
    window_days = env_int("WINDOW_DAYS", 180)
    keywords_raw = os.getenv("KEYWORDS", "").strip()
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    start = now_utc()
    end = start + timedelta(days=window_days)

    # Collect events from available sources
    events: list[dict] = []
    notes: list[str] = []

    # Manual (real) items you maintain in-repo
    manual_path = Path("data/manual_events.json")
    manual = load_manual_events(manual_path)
    if manual:
        notes.append(f"Loaded {len(manual)} manual event(s).")
        events.extend(manual)

    # (Future) live connectors go here (Meetup, Eventbrite, etc.)
    # For any connector errors, append to notes; do not fail the run.

    # Optional, explicitly opt-in fake records for formatting tests
    if env_bool("STUB_EVENTS", False):
        events.extend(very_obvious_stubs())
        notes.append("STUB_EVENTS=true: included impossible, clearly fake test items.")

    # Filter by date window if items have starts_utc
    def in_window(evt: dict) -> bool:
        s = evt.get("starts_utc")
        if not s:
            return True
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return start <= dt <= end
        except Exception:
            return True

    events = [e for e in events if in_window(e)]

    # Package
    out = {
        "meta": {
            "ts_utc": start.strftime(ISO),
            "within_miles": None,
            "city": None,
            "window_days": window_days,
            "keywords": keywords
        },
        "events": events
    }
    if notes:
        out["notes"] = notes
    if not events and not notes:
        out["notes"] = ["No sources configured; produced an empty list."]

    # Write artifact-friendly filename
    out_path = Path("aom-events.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} with {len(events)} event(s).")

if __name__ == "__main__":
    main()
