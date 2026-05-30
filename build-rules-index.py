"""
build-rules-index.py
Joins data/agenda_rules.json with data/oira_reviews.json on RIN.
Writes data/rules_index.json — the file the frontend Fuse.js search loads.

Run:  python build-rules-index.py
"""
import json
from datetime import date, datetime
from pathlib import Path

AGENDA = Path("data/agenda_rules.json")
OIRA   = Path("data/oira_reviews.json")
OUT    = Path("data/rules_index.json")


def days_since(date_str):
    """Return days between today and an ISO date string, or None."""
    if not date_str:
        return None
    try:
        received = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (date.today() - received).days
    except ValueError:
        return None


# --- Load sources ---
agenda_rules = json.loads(AGENDA.read_text())
print(f"Agenda rules:  {len(agenda_rules)}")

oira_reviews = json.loads(OIRA.read_text())["reviews"]
oira_by_rin  = {r["rin"]: r for r in oira_reviews}
print(f"OIRA reviews:  {len(oira_reviews)}")

# --- Join on RIN ---
rules_index  = []
oira_matched = 0

for rule in agenda_rules:
    rin  = rule["rin"]
    oira = oira_by_rin.get(rin)

    record = {**rule}   # copy all agenda fields

    if oira:
        oira_matched += 1
        record["at_oira"]      = True
        record["oira_received"]= oira.get("received_date")
        record["oira_days"]    = days_since(oira.get("received_date"))
        record["oira_rrid"]    = oira.get("rrid")
        record["oira_url"]     = oira.get("detail_url")
    else:
        record["at_oira"]      = False
        record["oira_received"]= None
        record["oira_days"]    = None
        record["oira_rrid"]    = None
        record["oira_url"]     = None

    rules_index.append(record)

OUT.write_text(json.dumps(rules_index, indent=2))

print(f"\nWrote {len(rules_index)} records → {OUT}")
print(f"OIRA matches:  {oira_matched} of {len(agenda_rules)} rules")
print(f"               ({oira_matched / len(agenda_rules) * 100:.1f}% of agenda is currently at OIRA)")