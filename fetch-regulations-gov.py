import json
import time
import os
import requests
from datetime import datetime

API_KEY = os.environ.get("REGULATIONS_GOV_API_KEY", "DEMO_KEY")
BASE_URL = "https://api.regulations.gov/v4"
INPUT_FILE = "data/rules_index.json"   # your existing joined index
OUTPUT_FILE = "data/regulations_gov.json"

def fetch_docket_for_rin(rin, session):
    """Look up regulations.gov docket info for a given RIN."""
    url = f"{BASE_URL}/dockets"
    params = {
        "filter[rin]": rin,
        "api_key": API_KEY,
    }
    resp = session.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    
    results = data.get("data", [])
    if not results:
        return None
    
    # Take the first match (usually only one docket per RIN)
    docket = results[0]
    attrs = docket.get("attributes", {})
    
    return {
        "rin": rin,
        "docket_id": docket.get("id"),
        "docket_url": f"https://www.regulations.gov/docket/{docket.get('id')}",
        "title": attrs.get("title"),
        "comment_count": attrs.get("numberOfCommentsReceived"),
        "comment_start_date": attrs.get("commentStartDate"),      # ISO date or null
        "comment_end_date": attrs.get("commentEndDate"),          # ISO date or null
        "docket_type": attrs.get("docketType"),                   # "Rulemaking" etc.
        "last_modified": attrs.get("lastModifiedDate"),
        "fetched_at": datetime.utcnow().isoformat() + "Z",
    }

def main():
    # Load your existing rules index to get the list of RINs to look up
    with open(INPUT_FILE) as f:
        rules = json.load(f)
    
    rin_list = [r["rin"] for r in rules if r.get("rin")]
    print(f"Looking up {len(rin_list)} RINs on regulations.gov...")
    
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
                print(f"  [{i+1}/{len(rin_list)}] {rin} → not found")
            time.sleep(0.1)   # 10 req/sec well under the 1,000/hr limit
        except Exception as e:
            print(f"  [{i+1}/{len(rin_list)}] {rin} → ERROR: {e}")
            errors.append(rin)
            time.sleep(1)
    
    with open(OUTPUT_FILE, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDone. {len(results)} matched, {len(errors)} errors.")
    if errors:
        print("Errors:", errors)

if __name__ == "__main__":
    main()