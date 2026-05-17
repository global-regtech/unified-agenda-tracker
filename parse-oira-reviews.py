"""
parse_oira_reviews.py

Reads data/oira_reviews_raw.html (saved by fetch-oira-reviews.py) and extracts
structured records into data/oira_reviews.json.

This is step 2 of the two-step pipeline. It is pure local processing — it does
not hit reginfo at all. We can iterate on selectors and field cleanup as much
as we want without generating any external traffic.

Schema (one record per pending review):
{
    "rin": "0560-AI88",
    "agency_code": "0560",
    "agency": "USDA/FSA",
    "title": "Assistance for Specialty Crop Farmers",
    "received_date": "2026-05-15",
    "rrid": "1384763",
    "detail_url": "https://www.reginfo.gov/public/do/eoDetails?rrid=1384763"
}

Note: "days at OIRA" is computed at render time in the front-end as
(today - received_date), not stored here. We keep raw fields, derive metrics.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

INPUT_PATH = Path("data/oira_reviews_raw.html")
OUTPUT_PATH = Path("data/oira_reviews.json")

REGINFO_BASE = "https://www.reginfo.gov"


def parse_received_date(raw: str) -> str:
    """Reginfo gives us MM/DD/YYYY; convert to ISO YYYY-MM-DD."""
    return datetime.strptime(raw.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")


def parse_agency_field(raw: str) -> tuple[str, str]:
    """
    Agency cell is formatted "CODE-NAME", e.g. "0560-USDA/FSA" or "2060-EPA/OAR".
    Split into (code, name). The first hyphen is the separator; subsequent
    hyphens stay inside the name.
    """
    raw = raw.strip()
    if "-" in raw:
        code, _, name = raw.partition("-")
        return code.strip(), name.strip()
    return "", raw


def parse_rrid_from_href(href: str) -> str:
    """Extract the rrid query param from a URL like '/public/do/eoDetails?rrid=1384763'."""
    if "rrid=" not in href:
        return ""
    return href.split("rrid=", 1)[1].split("&", 1)[0]


def parse_row(tr) -> dict | None:
    """
    Turn one <tr> into a record dict, or return None if it's not a data row
    (header row, spacer row, etc.). Data rows have exactly 7 <td> cells.
    """
    cells = tr.find_all("td", recursive=False)
    if len(cells) != 7:
        return None

    # Cell 0: Received date
    received_date = parse_received_date(cells[0].get_text())

    # Cell 1: RIN wrapped in an anchor to the agenda view; we just want the text
    rin_link = cells[1].find("a")
    rin = rin_link.get_text(strip=True) if rin_link else cells[1].get_text(strip=True)

    # Cell 2: Agency in CODE-NAME format
    agency_code, agency = parse_agency_field(cells[2].get_text())

    # Cell 3: Title is wrapped in <span class="TCJATitle">; get_text handles that
    title = cells[3].get_text(strip=True)

    # Cell 4: Status with a link to the eoDetails page — RRID lives in that link
    status_link = cells[4].find("a")
    if status_link is not None:
        href = status_link.get("href", "")
        rrid = parse_rrid_from_href(href)
        detail_url = REGINFO_BASE + href if href else ""
    else:
        rrid = ""
        detail_url = ""

    return {
        "rin": rin,
        "agency_code": agency_code,
        "agency": agency,
        "title": title,
        "received_date": received_date,
        "rrid": rrid,
        "detail_url": detail_url,
    }


def main():
    html = INPUT_PATH.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # The data table is uniquely identified by class="datatable".
    table = soup.find("table", class_="datatable")
    if table is None:
        raise RuntimeError(
            "Couldn't find <table class='datatable'> in the saved HTML. "
            "Reginfo may have changed its markup — open the raw file and inspect."
        )

    records = []
    skipped_non_data_rows = 0
    for tr in table.find_all("tr"):
        record = parse_row(tr)
        if record is None:
            skipped_non_data_rows += 1
            continue
        records.append(record)

    print(f"Parsed {len(records)} records (skipped {skipped_non_data_rows} non-data rows)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(records),
        "reviews": records,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")

    # Eyeball the first record to sanity-check field extraction.
    if records:
        print("\nFirst record:")
        print(json.dumps(records[0], indent=2))


if __name__ == "__main__":
    main()