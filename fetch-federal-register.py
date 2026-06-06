"""
fetch-federal-register.py
For each RIN in data/rules_index.json, queries the Federal Register API
and finds the most recent Proposed Rule and Final Rule documents.
Writes data/federal_register.json — keyed by RIN.

Run:  python fetch-federal-register.py
"""
import json
import time
import requests
from datetime import datetime
from pathlib import Path

INPUT_FILE  = Path("data/rules_index.json")
OUTPUT_FILE = Path("data/federal_register.json")
BASE_URL    = "https://www.federalregister.gov/api/v1/documents.json"

FIELDS = [
    "document_number",
    "title",
    "type",
    "publication_date",
    "html_url",
    "abstract",
]


def fetch_fr_documents(rin, session):
    """
    Return the most recent Proposed Rule and Final Rule for a RIN.
    Both may be None if no matching documents exist.
    """
    params = {
        "conditions[regulation_id_number]": rin,
        "fields[]": FIELDS,
        "per_page": 20,
        "order": "newest",
    }
    resp = session.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    results = resp.json().get("results", [])

    proposed = None
    final    = None

    for doc in results:
        doc_type = doc.get("type", "")

        if doc_type == "Proposed Rule" and proposed is None:
            proposed = {
                "document_number":  doc.get("document_number"),
                "title":            doc.get("title"),
                "publication_date": doc.get("publication_date"),
                "url":              doc.get("html_url"),
                "abstract":         doc.get("abstract"),
            }

        if doc_type == "Rule" and final is None:
            final = {
                "document_number":  doc.get("document_number"),
                "title":            doc.get("title"),
                "publication_date": doc.get("publication_date"),
                "url":              doc.get("html_url"),
                "abstract":         doc.get("abstract"),
            }

        if proposed and final:
            break   # got both, no need to read further

    return proposed, final


def main():
    rules = json.loads(INPUT_FILE.read_text())
    rin_list = [r["rin"] for r in rules if r.get("rin")]
    print(f"Fetching Federal Register docs for {len(rin_list)} RINs...")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "unified-agenda-tracker/1.0 (github.com/abulix/unified-agenda-tracker)"
    })

    results       = {}
    proposed_hits = 0
    final_hits    = 0
    errors        = []

    for i, rin in enumerate(rin_list):
        try:
            proposed, final = fetch_fr_documents(rin, session)

            results[rin] = {
                "rin":      rin,
                "proposed": proposed,
                "final":    final,
                "fetched_at": datetime.utcnow().isoformat() + "Z",
            }

            if proposed: proposed_hits += 1
            if final:    final_hits    += 1

            label = []
            if proposed: label.append("NPRM")
            if final:    label.append("Final")
            status = ", ".join(label) if label else "—"
            print(f"  [{i+1}/{len(rin_list)}] {rin}  {status}")

            time.sleep(0.2)   # polite; FR API has no published rate limit

        except Exception as e:
            print(f"  [{i+1}/{len(rin_list)}] {rin}  ERROR: {e}")
            errors.append(rin)
            time.sleep(1)

    OUTPUT_FILE.write_text(json.dumps(results, indent=2))

    print(f"\nWrote {len(results)} records → {OUTPUT_FILE}")
    print(f"Proposed rules found:  {proposed_hits} ({proposed_hits/len(rin_list)*100:.1f}%)")
    print(f"Final rules found:     {final_hits}    ({final_hits/len(rin_list)*100:.1f}%)")
    if errors:
        print(f"Errors ({len(errors)}): {errors}")


if __name__ == "__main__":
    main()