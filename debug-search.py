"""
debug_search.py — Figure out why our main search missed Spring 2024.

Two probes:
  1. Fetch the Spring 2024 Unified Agenda intro doc directly by its
     document number, and dump its key fields.
  2. Run a phrase-search for "Introduction to the Unified Agenda"
     and see how many results we get vs. our original search.
"""

import requests

HEADERS = {
    "User-Agent": "unified-agenda-tracker (https://github.com/abulix/unified-agenda-tracker)",
}

# ---- Probe 1: direct fetch by document number ----
print("=" * 70)
print("PROBE 1: Fetch Spring 2024 intro (doc 2024-16445) directly")
print("=" * 70)
url = "https://www.federalregister.gov/api/v1/documents/2024-16445.json"
resp = requests.get(url, headers=HEADERS, timeout=30)
resp.raise_for_status()
doc = resp.json()

# Print the fields most likely to explain why our search missed it
for key in ["document_number", "title", "type", "publication_date",
            "presidential_document_type", "subtype", "agency_names",
            "raw_text_url"]:
    value = doc.get(key)
    if value is not None:
        # Truncate very long values
        if isinstance(value, str) and len(value) > 100:
            value = value[:100] + "..."
        print(f"  {key}: {value}")

print()

# ---- Probe 2: search by exact phrase ----
print("=" * 70)
print('PROBE 2: Search for phrase "Introduction to the Unified Agenda"')
print("=" * 70)
params = {
    "conditions[term]": '"Introduction to the Unified Agenda"',
    "per_page": 100,
    "order": "newest",
}
resp = requests.get(
    "https://www.federalregister.gov/api/v1/documents.json",
    params=params, headers=HEADERS, timeout=30,
)
resp.raise_for_status()
data = resp.json()

print(f"  API reports total count: {data.get('count')}")
print(f"  Results in this page: {len(data.get('results', []))}")
print()
print("  First 30 results (newest first):")
for d in data.get("results", [])[:30]:
    print(f"    {d['publication_date']}  type={d.get('type', '?'):8s}  {d['title'][:65]}")