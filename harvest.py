# --- Eventbrite search (minimal, known-good) -------------------------------
BASE_URL = "https://www.eventbriteapi.com/v3/events/search/"
headers = {"Authorization": f"Bearer {EVENTBRITE_TOKEN}"}

# Build the simplest valid query first (no continuation/paging yet)
params = {
    # IMPORTANT: let requests/urlencode turn spaces into %20 (NOT +)
    "q": " ".join(KEYWORDS),                 # e.g. "steampunk gaslamp aether ..."
    "start_date.range_start": start_iso,    # ISO8601, e.g. 2025-08-27T03:29:12Z
    "start_date.range_end": end_iso,
    "expand": "venue,organizer",
    "sort_by": "date",
    "page": 1,
}

# Optional locality (only include if you actually have values)
if CITY:
    params["location.address"] = CITY
if WITHIN_MILES:
    # Eventbrite expects a unit; use miles here (mi). Example: "50mi"
    params["location.within"] = f"{WITHIN_MILES}mi"

resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
try:
    resp.raise_for_status()
    data = resp.json()
except requests.HTTPError as e:
    # Preserve the raw API error body to help debug from the artifact
    data = {"meta": meta, "events": [], "error": f"HTTPError {resp.status_code}: {e}; body={resp.text}"}
# --------------------------------------------------------------------------
