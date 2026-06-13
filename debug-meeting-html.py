"""Dump the raw HTML of one EO 12866 meeting detail page for parser debugging."""

import sys
import requests
from bs4 import BeautifulSoup

URL = "https://www.reginfo.gov/public/do/viewEO12866Meeting"
HEADERS = {
    "User-Agent": "RegulatoryTransparencyTracker-debug/0.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.reginfo.gov/public/do/eom12866Search",
}

# A Completed meeting with attendees should exist for this one
RIN = "3046-AB37"
MEETING_ID = "1422023"

resp = requests.get(
    URL,
    params={"rin": RIN, "meetingId": MEETING_ID, "viewRule": "true"},
    headers=HEADERS,
    timeout=30,
)
resp.raise_for_status()

# Save full page for inspection
with open("debug-meeting.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print(f"Full HTML saved to debug-meeting.html ({len(resp.text)} chars)")

# Find and print the section containing "Attendees" or "Stromer"-type names
soup = BeautifulSoup(resp.text, "html.parser")

# Print all tables and their first few rows for structure analysis
print("\n=== TABLES FOUND ===")
for i, table in enumerate(soup.find_all("table")):
    text_preview = table.get_text(" ", strip=True)[:200]
    print(f"\n--- Table #{i} ({len(table.find_all('tr'))} rows) ---")
    print(text_preview)

# Print the raw HTML of any element containing "Attendees" or "Linda Morris"
# (the requestor name for the meeting we know exists)
print("\n=== HTML AROUND 'Attendees' / 'Linda Morris' ===")
for term in ["Attendees", "Linda Morris", "Stromer", "Participation"]:
    matches = soup.find_all(string=lambda s: s and term in s)
    if matches:
        print(f"\n>>> Found '{term}' in {len(matches)} text node(s)")
        for match in matches[:2]:
            parent = match.parent
            # Walk up to find a meaningful container
            for _ in range(3):
                if parent and parent.name in ("table", "div", "td"):
                    break
                parent = parent.parent if parent else None
            if parent:
                snippet = str(parent)[:800]
                print(f"  Parent <{parent.name}>: {snippet}")