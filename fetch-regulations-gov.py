import json
import time
import os
import requests
from datetime import datetime, timezone, timedelta

API_KEY = os.environ.get("REGULATIONS_GOV_API_KEY", "DEMO_KEY")
BASE_URL = "https://api.regulations.gov/v4"
INPUT_FILE = "data/rules_index.json"
OUTPUT_FILE = "data/regulations_gov.json"

MISS_TTL_DAYS = 30

def needs_refresh(cached_record):
    """Re-fetch if it was a miss and the cache is older than 30 days."""
    if cached_record.get("docket_id"):
        return False  # it's a hit — never re-fetch
    fetched_at = cached_record.get("fetched_at")
    if not fetched_at:
        return True
    age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
    return age > timedelta(days=MISS_TTL_DAYS)

def fetch_docket_for_rin(rin, session):
    """Look up regulations.gov docket info for a given RIN."""
    url = f"{BASE_URL}/dockets"
    params = {
        "filter[searchTerm]": rin,
        "api_key": API_KEY,
    }
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("data", [])
    if not results:
        return None

    docket = results[0]
    attrs = docket.get("attributes", {})

    return {
        "rin": rin,
        "docket_id": docket.get("id"),
        "docket_url": f"https://www.regulations.gov/docket/{docket.get('id')}",
        "title": attrs.get("title"),
        "comment_count": attrs.get("numberOfCommentsReceived"),
        "comment_start_date": attrs.get("commentStartDate"),
        "comment_end_date": attrs.get("commentEndDate"),
        "docket_type": attrs.get("docketType"),
        "last_modified": attrs.get("lastModifiedDate"),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }

def main():
    with open(INPUT_FILE) as f:
        rules = json.load(f)

    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)

    rin_list = [
        r["rin"] for r in rules
        if r.get("rin") and (
            r["rin"] not in existing or needs_refresh(existing[r["rin"]])
        )
    ]
    print(f"Already cached: {len(existing)} RINs")
    print(f"To fetch:       {len(rin_list)} RINs")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "unified-agenda-tracker/1.0 (github.com/abulix/unified-agenda-tracker)"
    })

    results = {}
    errors = []

    for i, rin in enumerate(rin_list):
        try:
            record = fetch_docket_for_rin(rin, session)
            if record:
                results[rin] = record
                print(f"  [{i+1}/{len(rin_list)}] {rin} → {record['docket_id']}")
            else:
                results[rin] = {"rin": rin, "docket_id": None, "fetched_at": datetime.utcnow().isoformat() + "Z"}
                print(f"  [{i+1}/{len(rin_list)}] {rin} → not found")
            time.sleep(2)
        except Exception as e:
            print(f"  [{i+1}/{len(rin_list)}] {rin} → ERROR: {e}")
            errors.append(rin)
            time.sleep(10)

    existing.update(results)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    print(f"\nDone. {len(results)} newly fetched, {len(errors)} errors.")
    print(f"Total cached:  {len(existing)} RINs")
    if errors:
        print("Errors:", errors)

if __name__ == "__main__":
    main()