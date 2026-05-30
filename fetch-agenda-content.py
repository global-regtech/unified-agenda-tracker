"""
fetch_agenda_content.py
Downloads the Spring 2025 Unified Agenda XML from reginfo.gov.
Saves raw XML to data/agenda_content_raw.xml (gitignored).

Run:  python fetch_agenda_content.py
"""
import requests
import sys
from pathlib import Path

# Spring 2025 = pubId 202504 (year + 2-digit month of publication)
# Update this when a new edition is published.
PUB_ID = "202504"
URL = f"https://www.reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_{PUB_ID}.xml"
OUT = Path("data/agenda_content_raw.xml")

HEADERS = {
    "User-Agent": "regulatory-transparency-tracker/0.1 (github.com/abulix/unified-agenda-tracker)",
    "Accept": "application/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

print(f"Fetching Unified Agenda XML (pubId={PUB_ID})...")
print(f"  URL: {URL}")

try:
    resp = requests.get(URL, headers=HEADERS, timeout=60)
    resp.raise_for_status()
except requests.RequestException as e:
    print(f"ERROR: {e}")
    sys.exit(1)

OUT.parent.mkdir(exist_ok=True)
OUT.write_bytes(resp.content)

size_kb = len(resp.content) / 1024
print(f"  Saved {size_kb:,.0f} KB to {OUT}")