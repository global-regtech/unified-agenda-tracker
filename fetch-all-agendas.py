"""
fetch_all_agendas.py

Pulls every "Introduction to the Unified Agenda" document published in
the Federal Register, going back as far as the API allows (~2011).

Important quirk: these documents have inconsistent type classification
in the Federal Register — most are "Proposed Rule", but the 2025 edition
is "Notice". So we DON'T filter by type; we use a strict phrase search on
"Introduction to the Unified Agenda" and then filter by title prefix.

Saves results to data/agenda_history.json for use by the website.
"""

import json
import time
from pathlib import Path

import requests

BASE_URL = "https://www.federalregister.gov/api/v1/documents.json"

PARAMS = {
    # Quotes force the API to do an exact-phrase match rather than loose OR.
    "conditions[term]": '"Introduction to the Unified Agenda"',
    "per_page": 1000,
    "order": "oldest",
}

HEADERS = {
    "User-Agent": "unified-agenda-tracker (https://github.com/abulix/unified-agenda-tracker)",
}
SLEEP_SECONDS = 1.0


def fetch_all_pages():
    all_docs = []
    url = BASE_URL
    params = PARAMS
    page_num = 1

    while url:
        print(f"Fetching page {page_num}...")
        response = requests.get(url, params=params, headers=HEADERS, timeout=30)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        all_docs.extend(results)
        print(f"  Got {len(results)} documents (running total: {len(all_docs)})")

        url = data.get("next_page_url")
        params = None
        page_num += 1

        if url:
            time.sleep(SLEEP_SECONDS)

    return all_docs


def filter_introductions(docs):
    """Keep only docs whose title starts with the canonical prefix."""
    return [
        d for d in docs
        if d.get("title", "").startswith("Introduction to the Unified Agenda")
    ]


def slim_down(docs):
    return [
        {
            "publication_date": d.get("publication_date"),
            "title": d.get("title"),
            "type": d.get("type"),
            "document_number": d.get("document_number"),
            "html_url": d.get("html_url"),
        }
        for d in docs
    ]


def main():
    print("Querying Federal Register API for Unified Agenda introductions...\n")

    all_docs = fetch_all_pages()
    print(f"\nFetched {len(all_docs)} total documents matching the phrase search.")

    introductions = filter_introductions(all_docs)
    print(f"Of those, {len(introductions)} are 'Introduction to the Unified Agenda' docs.\n")

    introductions.sort(key=lambda d: d["publication_date"])
    slimmed = slim_down(introductions)

    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "agenda_history.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(slimmed, f, indent=2)

    print(f"Wrote {len(slimmed)} editions to {output_path}\n")

    print("All editions found:")
    for d in slimmed:
        type_str = (d.get("type") or "?")[:14]
        print(f"  {d['publication_date']}  ({type_str:14s}) {d['title'][:70]}")


if __name__ == "__main__":
    main()