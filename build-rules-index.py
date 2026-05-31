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
REGS_GOV = Path("data/regulations_gov.json")
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

regs_gov = json.loads(REGS_GOV.read_text()) if REGS_GOV.exists() else {}
print(f"Regs.gov:      {len(regs_gov)} dockets")                          

# --- Join on RIN ---
rules_index  = []
oira_matched = 0
regs_matched = 0

for rule in agenda_rules:
    rin  = rule["rin"]
    oira = oira_by_rin.get(rin)
    regs = regs_gov.get(rin)

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

    if regs:
        regs_matched += 1
        record["docket_id"]          = regs.get("docket_id")
        record["docket_url"]         = regs.get("docket_url")
        record["comment_count"]      = regs.get("comment_count")
        record["comment_start_date"] = regs.get("comment_start_date")
        record["comment_end_date"]   = regs.get("comment_end_date")
    else:
        record["docket_id"]          = None
        record["docket_url"]         = None
        record["comment_count"]      = None
        record["comment_start_date"] = None
        record["comment_end_date"]   = None

    rules_index.append(record)

OUT.write_text(json.dumps(rules_index, indent=2))

print(f"\nWrote {len(rules_index)} records → {OUT}")
print(f"OIRA matches:  {oira_matched} of {len(agenda_rules)} rules")
print(f"               ({oira_matched / len(agenda_rules) * 100:.1f}% of agenda is currently at OIRA)")
print(f"Regs.gov:      {regs_matched} of {len(agenda_rules)} rules matched a docket")