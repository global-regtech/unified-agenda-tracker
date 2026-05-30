"""
Parses concluded OIRA reviews HTML into structured JSON.

Reads data/oira_concluded_{withdrawn,returned}_raw.html, finds the datatable,
extracts rows, writes combined data/oira_concluded.json sorted by concluded
date descending.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

DATA_DIR = Path("data")

ACTIONS = {
    "withdrawn": "Withdrawn",
    "returned": "Returned for Reconsideration",
}


def parse_date(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date().isoformat()
    except ValueError:
        return text  # leave raw for inspection


def parse_concluded(html: str, action_label: str, print_headers: bool = False) -> list:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "datatable"})
    if not table:
        raise RuntimeError("No datatable found in HTML")

    rows = table.find_all("tr")
    if print_headers and rows:
        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True) for c in header_cells]
        print(f"  Column headers ({len(headers)}): {headers}")

    records = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 6:
            print(f"  Skipping row with {len(cells)} cells")
            continue

        # Best-guess column layout (verify against printed headers):
        #   0: agency (CODE-NAME)
        #   1: RIN
        #   2: title (with link)
        #   3: stage of rulemaking
        #   4: received date
        #   5: concluded date
        #   6: conclusion action
        # If your headers print differently, adjust the indices here.
        agency_text = cells[0].get_text(strip=True)
        if "-" in agency_text:
            agency_code, agency_name = agency_text.split("-", 1)
        else:
            agency_code, agency_name = "", agency_text

        rin = cells[1].get_text(strip=True)
        title = cells[2].get_text(strip=True)
        stage = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        received_date = parse_date(cells[4].get_text(strip=True)) if len(cells) > 4 else None
        concluded_date = parse_date(cells[5].get_text(strip=True)) if len(cells) > 5 else None

        # Find RRID in any link in the row
        rrid = None
        detail_url = None
        for link in row.find_all("a"):
            href = link.get("href", "")
            match = re.search(r"rrid=(\d+)", href)
            if match:
                rrid = match.group(1)
                detail_url = f"https://www.reginfo.gov/public/do/eoDetails?rrid={rrid}"
                break

        records.append({
            "rin": rin,
            "agency_code": agency_code.strip(),
            "agency": agency_name.strip(),
            "title": title,
            "stage": stage,
            "received_date": received_date,
            "concluded_date": concluded_date,
            "concluded_action": action_label,
            "rrid": rrid,
            "detail_url": detail_url,
        })

    return records


def main():
    all_records = []
    for i, (slug, label) in enumerate(ACTIONS.items()):
        raw_path = DATA_DIR / f"oira_concluded_{slug}_raw.html"
        if not raw_path.exists():
            print(f"SKIP: {raw_path} not found (run fetch_oira_concluded.py first)")
            continue

        print(f"Parsing {raw_path} as {label}")
        html = raw_path.read_text(encoding="utf-8")
        # Print headers from the first file only (they're the same structure)
        records = parse_concluded(html, label, print_headers=(i == 0))
        print(f"  Extracted {len(records)} records")
        all_records.extend(records)

    # Most recently concluded first
    all_records.sort(key=lambda r: r.get("concluded_date") or "", reverse=True)

    output_path = DATA_DIR / "oira_concluded.json"
    output_path.write_text(json.dumps(all_records, indent=2), encoding="utf-8")
    print(f"\nWrote {len(all_records)} records to {output_path}")


if __name__ == "__main__":
    main()