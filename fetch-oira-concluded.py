"""
fetch_oira_concluded.py

Pulls the current list of pending OIRA regulatory reviews from reginfo.gov.
Saves the raw HTML response to data/oira_concluded_raw.html for offline parsing.

This is step 1 of a two-step pipeline:
  1. Fetch (this script) — gets the HTML
  2. Parse (separate script, next session) — extracts structured rows into JSON

Why split fetch from parse?
  - Reginfo is old infrastructure; we want to hit it as little as possible.
  - We save the response once, then iterate on parsing logic locally
    without re-fetching from the server every time we tweak a selector.
"""

import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# Politeness header: identify ourselves and provide a contact path.
# If reginfo's admins ever notice this traffic, they can find the project.
HEADERS = {
    "User-Agent": (
        "unified-agenda-tracker/0.5 "
        "(+https://github.com/abulix/unified-agenda-tracker; "
        "personal research project)"
    )
}

# Additional headers for the POST. Reginfo's server checks Referer and Origin
# as anti-bot signals; without them we get a 403. These mirror what a real
# browser sends when submitting the advanced search form. Content-Type is
# set automatically by `requests` when we pass `data=` as a list of tuples.
POST_HEADERS = {
    **HEADERS,
    "Referer": "https://www.reginfo.gov/public/Forward?SearchTarget=RegReview",
    "Origin": "https://www.reginfo.gov",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Two URLs in play:
#   FORM_URL — serves the search form HTML; this is where we capture the CSRF token.
#   SUBMIT_URL — the action handler that processes filter submissions and returns results.
#     The viewall=y query string tells the server "skip pagination, return all results
#     on a single page" — without it, we'd only get 10 of 153 rows.
FORM_URL = "https://www.reginfo.gov/public/do/eoAdvancedSearchMain"
SUBMIT_URL = "https://www.reginfo.gov/public/do/eoAdvancedSearch?viewall=y"

OUTPUT_PATH = Path("data/oira_concluded_raw.html")


def fetch_csrf_token(session: requests.Session) -> str:
    """
    GET the search form page. This does two things at once:
      - The server sets a JSESSIONID cookie, which the session object stores
        automatically. We need this cookie for the POST to succeed.
      - The form HTML contains a hidden <input name="csrf_token" value="..."/>
        that we extract for use in the POST.
    """
    print("Step 1/2: fetching the search form to capture CSRF token + session cookie...")
    resp = session.get(FORM_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()  # crash loudly if reginfo returned an error

    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "csrf_token"})
    if token_input is None:
        raise RuntimeError(
            "CSRF token not found on form page. "
            f"Reginfo's HTML may have changed, or {FORM_URL} is the wrong URL. "
            "Open it in a browser and view-source to investigate."
        )
    token = token_input.get("value")
    print(f"  ok — token starts with {token[:12]}..., session cookie acquired")
    return token


def fetch_concluded_reviews(session: requests.Session, csrf_token: str) -> str:
    """
    POST the filter form with eoStatusCode=CO (Concluded).
    Returns the raw HTML of the results page.
    """
    print("Step 2/2: posting the Concluded filter...")

    # Full payload, including the _fieldname:on hidden checkbox fields.
    # We tried submitting a minimal payload (matching what the browser sent
    # for View All) and got a 500. The reason: the browser was in a session
    # that had already done the initial search, so the server had stored
    # state about "which checkbox groups were in the prior form." We're
    # submitting cold — no prior search — so we need to send those state-
    # establishing fields ourselves.
    form_data = [
        ("autoRefresh", "1"),
        ("rin", ""),
        ("eoStatusCode", "CO"),       # CO = Concluded (the key filter)
        ("agencyCode", "0000"),        # 0000 = all agencies
        ("subAgencyCode", ""),
        ("_econSigs", "on"),
        ("_econSigs", "on"),
        ("terms", ""),
        ("_s3f1Sigs", "on"),
        ("_s3f1Sigs", "on"),
        ("_legalDeadlines", "on"),
        ("_legalDeadlines", "on"),
        ("_legalDeadlines", "on"),
        ("receivedStartDate", ""),
        ("receivedEndDate", ""),
        ("_ruleStages", "on"),
        ("_ruleStages", "on"),
        ("_ruleStages", "on"),
        ("_ruleStages", "on"),
        ("_ruleStages", "on"),
        ("_ruleStages", "on"),
        ("_healthcareFlag", "on"),
        ("_healthcareFlag", "on"),
        ("_healthcareFlag", "on"),
        ("_internationalFlag", "on"),
        ("_internationalFlag", "on"),
        ("_internationalFlag", "on"),
        ("_doddFrankFlag", "on"),
        ("_doddFrankFlag", "on"),
        ("_doddFrankFlag", "on"),
        ("_tcjaFlag", "on"),
        ("_tcjaFlag", "on"),
        ("_tcjaFlag", "on"),
        ("_expeditedFlag", "on"),
        ("_expeditedFlag", "on"),
        ("_covid19Flag", "on"),
        ("_covid19Flag", "on"),
        ("_covid19Flag", "on"),
        ("concludedActionCode", ""),
        ("conclusionStartDate", ""),
        ("conclusionEndDate", ""),
        ("_majors", "on"),
        ("_majors", "on"),
        ("publishedStartDate", ""),
        ("publishedEndDate", ""),
        ("_federalisms", "on"),
        ("_federalisms", "on"),
        ("_federalisms", "on"),
        ("_homelandSecurities", "on"),
        ("_homelandSecurities", "on"),
        ("_homelandSecurities", "on"),
        ("_smallEntities", "on"),
        ("_smallEntities", "on"),
        ("_smallEntities", "on"),
        ("_smallEntities", "on"),
        ("_smallEntities", "on"),
        ("_unfundedMandates", "on"),
        ("_unfundedMandates", "on"),
        ("_unfundedMandates", "on"),
        ("_unfundedMandates", "on"),
        ("_rfaRequires", "on"),
        ("_rfaRequires", "on"),
        ("_rfaRequires", "on"),
        ("_rfaRequires", "on"),
        ("_rfaRequires", "on"),
        ("sortBy", "DESC"),
        ("orderBy", "OIRA_RECEIVED_DT"),
        ("csrf_token", csrf_token),
    ]

    # Polite pause between requests. One second is plenty for our scale.
    time.sleep(1)

    resp = session.post(SUBMIT_URL, data=form_data, headers=POST_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # A Session object persists cookies across requests automatically.
    session = requests.Session()
    csrf = fetch_csrf_token(session)
    html = fetch_concluded_reviews(session, csrf)

    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"\nSaved {len(html):,} bytes to {OUTPUT_PATH}")

    # Sanity check: do we actually see the records-found line?
    # Case-insensitive because reginfo's exact wording is "Number of records Found".
    if "number of records found" in html.lower():
        # Pull out the count line for quick eyeballing.
        soup = BeautifulSoup(html, "html.parser")
        for line in soup.get_text().splitlines():
            if "number of records found" in line.lower():
                print(f"Sanity check: {line.strip()}")
                break
    else:
        print(
            "WARNING: response does not contain 'Number of Records found'. "
            "Open the saved HTML in a browser to inspect — it may be an "
            "error page or the form may not have submitted correctly."
        )


if __name__ == "__main__":
    main()