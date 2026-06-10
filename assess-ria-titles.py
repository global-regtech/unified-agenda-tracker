"""
assess-ria-titles.py  (throwaway / NOT part of the daily pipeline)

Purpose
-------
Before committing to an RIA-detection heuristic, look at the REAL document titles
regulations.gov returns for dockets we *expect* to contain an economic analysis.
regulations.gov has only four documentType values
(Proposed Rule | Rule | Supporting & Related | Other), so an RIA has no type of
its own -- it lives under "Supporting & Related" and is identifiable only by its
TITLE. This dumps every non-rule-text document's (type, title) so we can design
the keyword/regex from real data.

This version is resumable and rate-limit tolerant:
  - Samples ACROSS agencies (round-robin by RIN prefix), not the first N, so we
    see varied title conventions (USDA "CBA" vs EPA/HHS "RIA", etc.).
  - On HTTP 429 (OVER_RATE_LIMIT) it saves progress and stops cleanly.
  - On rerun it resumes: dockets already in ria_assessment.json are skipped, so
    you never re-spend quota. Run it across a few hourly windows if needed.

Run locally (Windows):  python assess-ria-titles.py
Reads:  data/rules_index.json
Writes: ria_assessment.json   <- eyeball it, or paste it back into the chat.
"""

import json
import os
import sys
import time
from collections import defaultdict, deque

import requests

# --- config -----------------------------------------------------------------
API_KEY = "zNCdpP1RAkLiaiFDDEwDbT99hvaqgDEagRsB53PG"  # or hardcode for a local run, then revert
DOCS_URL = "https://api.regulations.gov/v4/documents"
OUT_PATH = "ria_assessment.json"
THROTTLE_SECONDS = 3.6        # ~1,000 req/hr ceiling
SIGNIFICANT_TARGET = 40       # dockets we expect to HAVE an RIA
CONTROL_TARGET = 10           # non-significant dockets -> false-positive control
PAGE_SIZE = 250               # max; assessment fetches page 1 only

HEADERS = {
    "User-Agent": "regulatory-transparency-tooling (assess-ria-titles.py)",
    "Accept": "application/vnd.api+json",
}


def is_significant(priority):
    """Weekend-4 rule: contains 'signif' but not 'nonsignif'."""
    p = (priority or "").lower()
    return "signif" in p and "nonsignif" not in p


def get_docket_id(rule):
    return rule.get("docket_id") or rule.get("docketId")


def agency_code(rule):
    """RIN prefix is the agency code (e.g. '0560-AI41' -> '0560')."""
    rin = rule.get("rin") or ""
    return rin.split("-")[0] if "-" in rin else (rin[:4] or "????")


def stratified(rules, n):
    """Round-robin one rule per agency per pass -> maximize agency diversity."""
    buckets = defaultdict(list)
    for r in rules:
        buckets[agency_code(r)].append(r)
    queues = [deque(v) for v in buckets.values()]
    out = []
    while len(out) < n and any(queues):
        for q in queues:
            if q:
                out.append(q.popleft())
                if len(out) >= n:
                    break
    return out


def fetch_documents(docket_id):
    params = {
        "filter[docketId]": docket_id,
        "page[size]": PAGE_SIZE,
        "api_key": API_KEY,  # query-param auth is what the data.gov gateway reliably accepts
    }
    r = requests.get(DOCS_URL, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out = []
    for d in r.json().get("data", []):
        a = d.get("attributes", {})
        out.append({
            "documentType": a.get("documentType"),
            "title": a.get("title"),
            "documentId": d.get("id"),
        })
    return out


def save(results):
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def main():
    if not API_KEY:
        sys.exit("Set REGULATIONS_GOV_API_KEY (env var) or hardcode it for this local run.")

    with open("data/rules_index.json", encoding="utf-8") as f:
        rules = json.load(f)

    sig = [r for r in rules if is_significant(r.get("priority")) and get_docket_id(r)]
    ctrl = [r for r in rules if not is_significant(r.get("priority")) and get_docket_id(r)]
    sample = stratified(sig, SIGNIFICANT_TARGET) + stratified(ctrl, CONTROL_TARGET)

    # Resume: skip dockets we've already fetched in a prior (rate-limited) run.
    results = []
    done = set()
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            results = json.load(f)
        done = {r["docket_id"] for r in results}

    todo = [r for r in sample if get_docket_id(r) not in done]
    print(f"Index: {len(rules)} rules. Significant w/ docket: {len(sig)}, "
          f"control: {len(ctrl)}.")
    print(f"Sample: {len(sample)} dockets across "
          f"{len({agency_code(r) for r in sample})} agencies. "
          f"Already done: {len(done)}. To fetch this run: {len(todo)}.\n")

    for i, rule in enumerate(todo, 1):
        docket_id = get_docket_id(rule)
        rin = rule.get("rin")
        sig_flag = is_significant(rule.get("priority"))
        label = "SIG " if sig_flag else "ctrl"

        try:
            docs = fetch_documents(docket_id)
        except requests.HTTPError as e:
            resp = e.response
            code = resp.status_code if resp is not None else "?"
            if code == 429:
                save(results)
                print(f"\nRate limited (429) after {len(results)} dockets total. Progress saved.")
                print("Wait for the hourly window to reset (and ideally run when no "
                      "comment-backfill / daily Action is consuming quota), then rerun "
                      "-- it resumes automatically.")
                return
            body = resp.text[:400] if resp is not None else "(no body)"
            print(f"\n[{i}/{len(todo)}] {label} {docket_id} HTTP {code}\n  BODY: {body}")
            save(results)
            return
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(todo)}] {label} {docket_id} ERROR: {e}")
            time.sleep(THROTTLE_SECONDS)
            continue

        support = [d for d in docs if d["documentType"] not in ("Proposed Rule", "Rule")]
        print(f"[{i}/{len(todo)}] {label} {agency_code(rule):>5}  {docket_id}  "
              f"RIN={rin}  {len(docs)} docs, {len(support)} supporting/other")
        for d in support:
            print(f"      - [{d['documentType']}] {d['title']}")

        results.append({
            "rin": rin,
            "docket_id": docket_id,
            "agency_code": agency_code(rule),
            "significant": sig_flag,
            "doc_count": len(docs),
            "supporting": support,
        })
        save(results)  # checkpoint after every docket so a 429 never loses work
        time.sleep(THROTTLE_SECONDS)

    print(f"\nDone. {len(results)} dockets in {OUT_PATH}.")


if __name__ == "__main__":
    main()