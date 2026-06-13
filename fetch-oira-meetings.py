"""
fetch-oira-meetings.py — Tier 4 EO 12866 meeting log scraper.

Reads data/oira_reviews.json for currently-pending OIRA RINs, fetches each
one's meeting search results from reginfo.gov, then drills into each meeting's
detail page for requestor + attendee data.

URL patterns (both simple GETs, no JSP form dance):
  Search:   https://www.reginfo.gov/public/do/eom12866SearchResults?rin={RIN}&viewRule=true
  Detail:   https://www.reginfo.gov/public/do/viewEO12866Meeting?meetingId={ID}&rin={RIN}

Caching strategy:
  - Search page is re-fetched daily while a RIN is at OIRA (new meetings can appear).
  - Detail pages are immutable once captured — keyed by meeting_id, never re-fetched.
  - RINs that leave OIRA are dropped on the next run to keep file size bounded.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.reginfo.gov/public/do"
SEARCH_URL = f"{BASE}/eom12866SearchResults"
DETAIL_URL = f"{BASE}/viewEO12866Meeting"

THROTTLE_SECONDS = 1.5
TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "RegulatoryTransparencyTracker/0.7 "
        "(+https://unified-agenda-tracker.abulix.workers.dev/)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.reginfo.gov/public/do/eom12866Search",
}

OIRA_REVIEWS_PATH = Path("data/oira_reviews.json")
OUTPUT_PATH = Path("data/oira_meetings.json")

# Affiliation strings that mark an attendee as a federal-government employee.
# Used to compute is_government on each attendee. The list is intentionally
# permissive — we'd rather mis-flag one DOL employee than miss the outside-vs-
# inside distinction at the aggregate level. Extend as new agencies appear.
GOV_AFFILIATIONS = re.compile(
    r"\b("
    # Executive Office
    r"OMB|OIRA|White House|EOP|"
    # Cabinet departments
    r"USDA|DOC|DOD|DoD|ED|DOE|HHS|DHS|HUD|DOI|DOJ|DOL|DOS|DOT|VA|"
    r"Treasury|IRS|"
    # Major independent agencies
    r"EPA|GSA|NASA|NSF|SBA|SSA|OPM|EEOC|NLRB|NRC|FRB|"
    # Financial regulators
    r"FCC|FTC|FERC|FDIC|SEC|CFPB|CFTC|OCC|"
    # Health
    r"FDA|CMS|CDC|NIH|ACF|HRSA|SAMHSA|"
    # Transportation sub-agencies
    r"NHTSA|FAA|FRA|FTA|FMCSA|MARAD|PHMSA|"
    # Interior sub-agencies
    r"BLM|BIA|FWS|NPS|USGS|BOEM|BSEE|"
    # Labor sub-agencies
    r"OSHA|MSHA|WHD|EBSA|OFCCP|"
    # Commerce sub-agencies
    r"USPTO|NIST|NOAA|BIS|"
    # Law enforcement
    r"FBI|DEA|ATF|USPS|TSA|CBP|ICE|USCIS|"
    # Generic patterns (catches Department of X, Office of Y, etc.)
    r"Department of|Office of|Bureau of|Administration|Commission"
    r")\b",
    re.IGNORECASE,
)


def load_pending_rins() -> list[str]:
    with OIRA_REVIEWS_PATH.open() as f:
        data = json.load(f)
    return [r["rin"] for r in data["reviews"]]


def load_cache() -> dict:
    if not OUTPUT_PATH.exists():
        return {"records": {}, "meetings_by_id": {}, "generated_at": None}
    with OUTPUT_PATH.open() as f:
        cache = json.load(f)
    cache.setdefault("records", {})
    cache.setdefault("meetings_by_id", {})
    return cache


def save_cache(cache: dict) -> None:
    cache["generated_at"] = datetime.now(timezone.utc).isoformat()
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w") as f:
        json.dump(cache, f, indent=2)


# ---------- Search results parsing ----------

def parse_search_page(html: str, rin: str) -> dict:
    """Extract meeting count and the list of meeting IDs (and sparse metadata)
    from the per-RIN search results page."""
    soup = BeautifulSoup(html, "html.parser")

    count_match = re.search(
        r"Number\s*Of\s*Records\s*Found[:\s]*([0-9,]+)", soup.get_text()
    )
    meeting_count = int(count_match.group(1).replace(",", "")) if count_match else 0

    meeting_stubs = []
    for link in soup.find_all("a", href=re.compile(r"viewEO12866Meeting")):
        href = link.get("href", "")
        m = re.search(r"meetingId=(\d+)", href)
        if not m:
            continue
        meeting_id = m.group(1)

        link_text = link.get_text(strip=True)
        date_match = re.match(
            r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}:\d{2})\s*(AM|PM)?",
            link_text,
        )
        if not date_match:
            continue
        mm, dd, yyyy, hhmm, ampm = date_match.groups()
        iso_date = f"{yyyy}-{mm}-{dd}"
        time_24h = _to_24h(hhmm, ampm)

        row = link.find_parent("tr")
        cells = [c.get_text(strip=True) for c in row.find_all("td")] if row else []
        stage = cells[3] if len(cells) > 3 else ""
        mtype = cells[4] if len(cells) > 4 else ""

        meeting_stubs.append(
            {
                "meeting_id": meeting_id,
                "date": iso_date,
                "time": time_24h,
                "stage": stage,
                "type": mtype,
            }
        )

    return {"meeting_count": meeting_count, "stubs": meeting_stubs}


def _to_24h(hhmm: str, ampm: str | None) -> str:
    h, m = hhmm.split(":")
    h = int(h)
    if ampm:
        if ampm.upper() == "PM" and h != 12:
            h += 12
        elif ampm.upper() == "AM" and h == 12:
            h = 0
    return f"{h:02d}:{m}"


# ---------- Meeting detail page parsing ----------

def parse_meeting_detail(html: str, meeting_id: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    requestor_org = _extract_label(text, "Requestor")
    requestor_name = _extract_label(text, r"Requestor's\s+Name")

    attendees = _parse_attendees(soup)
    documents = _parse_documents(soup)  

    return {
        "meeting_id": meeting_id,
        "requestor_org": requestor_org,
        "requestor_name": requestor_name,
        "attendees": attendees,
        "documents": documents,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

def _extract_label(text: str, label_pattern: str) -> str | None:
    """Pull the value following a 'Label:' line. Returns None if absent."""
    m = re.search(rf"{label_pattern}\s*:?\s*\n+\s*([^\n]+)", text)
    if not m:
        return None
    value = m.group(1).strip()
    # Reginfo sometimes inlines the next label on the same line — clean defensively
    value = re.split(r"\s{2,}|(?=Requestor's|Title:|Agency)", value)[0].strip()
    return value or None


def _parse_attendees(soup: BeautifulSoup) -> list[dict]:
    """Find the dedicated attendees table and extract each row.

    Several wrapper tables on the page contain 'Attendees' in their summary
    attribute, so we narrow to the one with a 'Participation' header. We also
    use recursive=False when finding cells to prevent absorbing nested-table
    content, and dedupe on (name, affiliation) since reginfo sometimes renders
    the attendee list twice on the same page.
    """
    tables = soup.find_all(
        "table", attrs={"summary": re.compile(r"Attendees", re.IGNORECASE)}
    )
    table = next(
        (
            t for t in tables
            if t.find("th", string=re.compile(r"Participation", re.IGNORECASE))
        ),
        None,
    )
    if not table:
        return []

    attendees: list[dict] = []
    seen = set()

    for row in table.find_all("tr"):
        # Direct td children only — prevents pulling cells from nested tables
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue

        combined = " ".join(c.get_text(" ", strip=True) for c in cells)
        combined = re.sub(r"\s+", " ", combined.replace("\u00a0", " ")).strip()

        # Safety: a normal attendee row is under ~150 chars. Skip suspicious blobs.
        if len(combined) > 300:
            continue

        combined = re.sub(r"^•\s*", "", combined)

        # Participation markers — order matters: "Did Not Attend" before "In Person"
        # because "In Person" is a substring concern (it isn't, but defensively).
        participation = ""
        for marker in (
            "Did Not Attend",
            "No Show",
            "Teleconference",
            "Video Conference",
            "In-Person",
            "In Person",
            "Hybrid",
        ):
            if combined.endswith(marker):
                participation = marker
                combined = combined[: -len(marker)].strip()
                break

        if " - " not in combined:
            continue
        name, _, affiliation = combined.partition(" - ")
        name, affiliation = name.strip(), affiliation.strip()
        if not name or not affiliation:
            continue

        # Dedupe — reginfo renders the list twice on some pages
        key = (name.lower(), affiliation.lower())
        if key in seen:
            continue
        seen.add(key)

        attendees.append(
            {
                "name": name,
                "affiliation": affiliation,
                "participation": participation,
                "is_government": bool(GOV_AFFILIATIONS.search(affiliation)),
            }
        )

    return attendees

def _parse_documents(soup: BeautifulSoup) -> list[dict]:
    """Documents (if any) live in a sibling table with summary='List of Documents'.
    Each document is an anchor inside that table. 'No documents found.' rows
    are present when the requestor didn't share materials — return [] in that case.
    """
    table = soup.find(
        "table", attrs={"summary": re.compile(r"Documents", re.IGNORECASE)}
    )
    if not table:
        return []

    text = table.get_text(" ", strip=True)
    if "No documents found" in text:
        return []

    documents = []
    for a in table.find_all("a"):
        title = a.get_text(" ", strip=True)
        href = a.get("href", "").strip()
        if title and href:
            documents.append({"title": title, "url": href})
    return documents

# ---------- HTTP wrappers ----------

def fetch_search(session: requests.Session, rin: str) -> dict | None:
    try:
        resp = session.get(
            SEARCH_URL,
            params={"rin": rin, "viewRule": "true"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return parse_search_page(resp.text, rin)
    except Exception as e:
        print(f"  [search-error] {rin}: {e}", file=sys.stderr)
        return None


def fetch_detail(session: requests.Session, rin: str, meeting_id: str) -> dict | None:
    try:
        resp = session.get(
            DETAIL_URL,
            params={"rin": rin, "meetingId": meeting_id, "viewRule": "true"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return parse_meeting_detail(resp.text, meeting_id)
    except Exception as e:
        print(f"  [detail-error] {meeting_id} ({rin}): {e}", file=sys.stderr)
        return None


# ---------- Main orchestration ----------

def main() -> int:
    rins = load_pending_rins()
    cache = load_cache()
    records: dict = cache["records"]
    meetings_by_id: dict = cache["meetings_by_id"]

    print(f"Fetching EO 12866 meetings for {len(rins)} pending OIRA RINs...")
    session = requests.Session()
    session.headers.update(HEADERS)

    new_details = 0
    rules_with_meetings = 0
    fail = 0

    for i, rin in enumerate(rins, 1):
        if i % 25 == 0:
            print(f"  Progress: {i}/{len(rins)} (saving checkpoint, {new_details} new detail fetches)")
            cache["records"] = records
            cache["meetings_by_id"] = meetings_by_id
            save_cache(cache)

        search_result = fetch_search(session, rin)
        if search_result is None:
            fail += 1
            continue

        meeting_count = search_result["meeting_count"]
        stubs = search_result["stubs"]

        if meeting_count == 0:
            records[rin] = {
                "rin": rin,
                "meeting_count": 0,
                "last_meeting_date": None,
                "meetings": [],
                "has_more": False,
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            time.sleep(THROTTLE_SECONDS)
            continue

        # For each meeting stub on the search page, fetch the detail page only
        # if we haven't seen this meeting_id before. Completed meetings are
        # immutable so this is a one-time cost per meeting.
        full_meetings = []
        for stub in stubs:
            mid = stub["meeting_id"]
            if mid not in meetings_by_id:
                time.sleep(THROTTLE_SECONDS)
                detail = fetch_detail(session, rin, mid)
                if detail is None:
                    # Save the stub but no attendee info — better than nothing
                    meetings_by_id[mid] = {**stub, "attendees": [], "incomplete": True}
                else:
                    meetings_by_id[mid] = {**stub, **detail}
                    new_details += 1

            full_meetings.append(meetings_by_id[mid])

        full_meetings.sort(key=lambda m: (m["date"], m["time"]), reverse=True)
        last_meeting_date = full_meetings[0]["date"] if full_meetings else None

        records[rin] = {
            "rin": rin,
            "meeting_count": meeting_count,
            "last_meeting_date": last_meeting_date,
            "meetings": full_meetings,
            "has_more": meeting_count > len(full_meetings),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        rules_with_meetings += 1
        time.sleep(THROTTLE_SECONDS)

    # Trim records for RINs no longer at OIRA, but KEEP meetings_by_id forever —
    # those are immutable historical records and may be referenced by rules that
    # come back to OIRA for a second review.
    pending_set = set(rins)
    records = {r: rec for r, rec in records.items() if r in pending_set}

    cache["records"] = records
    cache["meetings_by_id"] = meetings_by_id
    save_cache(cache)

    total_meetings = sum(r["meeting_count"] for r in records.values())
    print(
        f"\nDone. {rules_with_meetings} of {len(rins)} pending rules have >=1 meeting. "
        f"{total_meetings} meetings total. {new_details} new detail pages fetched this run. "
        f"{fail} search-page errors."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())