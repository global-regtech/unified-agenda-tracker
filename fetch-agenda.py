"""
Fetch the most recent Unified Agenda publication date from the
Federal Register API.

Why we pivoted: reginfo.gov's eAgendaXmlReport endpoint serves up an
HTML form for humans, not raw XML. The Federal Register publishes
each Unified Agenda edition as a Notice with a clean publication
date, accessible via a documented JSON API with no API key required.
"""

import requests
from datetime import date

URL = "https://www.federalregister.gov/api/v1/documents.json"

PARAMS = {
    "conditions[term]": "Unified Agenda",
    "conditions[type][]": "NOTICE",
    "order": "newest",
    "per_page": 50,
    "fields[]": ["title", "publication_date", "html_url"],
}

HEADERS = {
    "User-Agent": "UnifiedAgendaTracker/0.1 (abulix@gmail.com)"
}

FALL_2025_DEADLINE = date(2025, 12, 31)


def main():
    print("Fetching Unified Agenda publications from Federal Register API...")
    print()

    response = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=30)
    print(f"HTTP status: {response.status_code}")
    print(f"Content type: {response.headers.get('Content-Type', 'unknown')}")
    print()

    data = response.json()
    results = data.get("results", [])

    print(f"Total matching documents in archive: {data.get('count', 'unknown')}")
    print(f"Showing {len(results)} most recent:")
    print()

    for i, doc in enumerate(results, 1):
        print(f"{i}. {doc['publication_date']} — {doc['title']}")
        print(f"   {doc['html_url']}")
        print()

    # Find the most recent "Introduction to the Unified Agenda" — these
    # are the official publication notices for each edition.
    intros = [d for d in results if d["title"].startswith("Introduction to the Unified Agenda")]

    if intros:
        print("=" * 60)
        print(f"Found {len(intros)} Unified Agenda introduction(s):")
        print()
        for intro in intros:
            print(f"  {intro['publication_date']}  —  {intro['title']}")
        print()

        most_recent = intros[0]
        pub_date = date.fromisoformat(most_recent["publication_date"])
        days_since_last = (date.today() - pub_date).days
        print("=" * 60)
        print("Most recent edition:")
        print(f"  Title:              {most_recent['title']}")
        print(f"  Published:          {pub_date.isoformat()}")
        print(f"  Days since:         {days_since_last}")
        print(f"  URL:                {most_recent['html_url']}")
        print()
    else:
        print("No Unified Agenda introductions found in the response.")
        print("This shouldn't happen — investigate the API response.")
        print()

    today = date.today()
    days_overdue = (today - FALL_2025_DEADLINE).days
    print("=" * 60)
    print(f"Today's date:           {today.isoformat()}")
    print(f"Fall 2025 deadline:     {FALL_2025_DEADLINE.isoformat()}")
    print(f"Days overdue:           {days_overdue}")


if __name__ == "__main__":
    main()