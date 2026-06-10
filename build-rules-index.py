"""
build-rules-index.py
Builds data/rules_index.json which is the file the frontend Fuse.js search and the
per-rule timeline page (rule.html) load.

UNION ON RIN: the universe of rules is every RIN seen across all four sources,
not just the agenda. Rules that are at OIRA but absent from the current agenda
(e.g. submitted after publication, or only in an earlier edition) now get a
record instead of being dropped. Each record carries `in_agenda` so the
frontend can tell "in the current agenda" from "found via OIRA only."

Run:  python build-rules-index.py
"""
import json
from datetime import date, datetime
from pathlib import Path

# Economic-analysis (RIA) signal. The shared classifier lives in ria_detection.py
# (an importable module -- underscores, not the hyphen used for runnable scripts).
from ria_detection import economic_analysis_signal

AGENDA   = Path("data/agenda_rules.json")
OIRA     = Path("data/oira_reviews.json")
REGS_GOV = Path("data/regulations_gov.json")
FED_REG  = Path("data/federal_register.json")
OUT      = Path("data/rules_index.json")


def days_since(date_str):
    """Return days between today and an ISO date string, or None."""
    if not date_str:
        return None
    try:
        received = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (date.today() - received).days
    except ValueError:
        return None


def first(d, *keys, default=None):
    """First non-empty value among keys in dict d, else default."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


# --- Load sources ---
agenda_rules = json.loads(AGENDA.read_text())
agenda_by_rin = {r["rin"]: r for r in agenda_rules}
print(f"Agenda rules:     {len(agenda_rules)}")

# code -> (parent, sub) full names, from the agenda. The RIN's 4-digit prefix
# is the agency code, so OIRA-only rules can borrow the agenda's full names.
agency_lookup = {}
for r in agenda_rules:
    code = r["rin"].split("-")[0]
    if code and code not in agency_lookup:
        agency_lookup[code] = (r.get("parent_agency_name", ""), r.get("agency_name", ""))

oira_reviews = json.loads(OIRA.read_text())["reviews"]
oira_by_rin  = {r["rin"]: r for r in oira_reviews}
print(f"OIRA reviews:     {len(oira_reviews)}")

regs_gov = json.loads(REGS_GOV.read_text()) if REGS_GOV.exists() else {}
print(f"Regs.gov:         {len(regs_gov)} dockets")

fed_reg = json.loads(FED_REG.read_text()) if FED_REG.exists() else {}
print(f"Federal Register: {len(fed_reg)} RINs with documents")


def resolve_agency(rin, oira):
    """Full parent/sub agency names. Prefer the agenda's names (matched on the
    RIN's agency-code prefix); else split the OIRA 'agency' string ('HHS/ACF').
    Returns (parent, sub) where sub == parent when there is no sub-agency, so
    the UI shows the name once."""
    code = rin.split("-")[0] if rin else ""
    if code in agency_lookup:
        return agency_lookup[code]
    raw = (oira.get("agency") or "").strip()
    if "/" in raw:
        parent, sub = (s.strip() for s in raw.split("/", 1))
        return parent, sub
    return raw, raw


def make_oira_only_record(rin, oira):
    """Synthesize the agenda-style fields for a rule that is at OIRA but not in
    the current agenda. Title comes from the OIRA review; agency names are
    resolved to the agenda's full names where possible."""
    parent, sub = resolve_agency(rin, oira)
    return {
        "rin": rin,
        "title":              first(oira, "title", "rule_title", default=f"Rule {rin} (at OIRA, not in current agenda)"),
        "abstract":           first(oira, "abstract"),
        "parent_agency_name": parent,
        "agency_name":        sub,
        "stage":              first(oira, "stage", "rule_stage", default="Pending OIRA Review"),
        # rules at OIRA are significant by definition; default reflects that
        "priority":           first(oira, "priority", "significance", default="Significant"),
        "reginfo_url":        None,   # no agenda page; OIRA detail is linked via oira_url
    }


def attach_sources(record, rin):
    """Attach OIRA / regulations.gov / Federal Register fields to a record."""
    oira = oira_by_rin.get(rin)
    if oira:
        record["at_oira"]       = True
        record["oira_received"] = oira.get("received_date")
        record["oira_days"]     = days_since(oira.get("received_date"))
        record["oira_rrid"]     = oira.get("rrid")
        record["oira_url"]      = oira.get("detail_url")
    else:
        record.update(at_oira=False, oira_received=None, oira_days=None,
                      oira_rrid=None, oira_url=None)

    regs = regs_gov.get(rin)
    if regs:
        record["docket_id"]          = regs.get("docket_id")
        record["docket_url"]         = regs.get("docket_url")
        record["documents"]          = regs.get("documents", [])
        record["comment_count"]      = regs.get("comment_count")
        record["comment_start_date"] = regs.get("comment_start_date")
        record["comment_end_date"]   = regs.get("comment_end_date")
    else:
        record.update(docket_id=None, docket_url=None, documents=None, comment_count=None,
                      comment_start_date=None, comment_end_date=None)

    fr = fed_reg.get(rin)
    if fr:
        proposed = fr.get("proposed") or {}
        final    = fr.get("final")    or {}
        record["fr_proposed_url"]  = proposed.get("url")
        record["fr_proposed_date"] = proposed.get("publication_date")
        record["fr_final_url"]     = final.get("url")
        record["fr_final_date"]    = final.get("publication_date")
    else:
        record.update(fr_proposed_url=None, fr_proposed_date=None,
                      fr_final_url=None, fr_final_date=None)


# --- Join: agenda rules first (preserves order), then OIRA-only rules ---
rules_index = []
seen = set()

for rule in agenda_rules:
    rin = rule["rin"]
    record = {**rule, "in_agenda": True}
    attach_sources(record, rin)
    rules_index.append(record)
    seen.add(rin)

# Any RIN present in another source but not the agenda (chiefly OIRA-only rules)
extra_rins = (set(oira_by_rin) | set(regs_gov) | set(fed_reg)) - seen
for rin in sorted(extra_rins):
    record = make_oira_only_record(rin, oira_by_rin.get(rin, {}))
    record["in_agenda"] = False
    attach_sources(record, rin)
    rules_index.append(record)

# --- Economic-analysis (RIA) signal: computed here so it's a native part of the
# build and survives every regeneration. Runs last, when documents / priority /
# FR dates are all present on each record. ---
for record in rules_index:
    record["economic_analysis"] = economic_analysis_signal(record)

OUT.write_text(json.dumps(rules_index, indent=2))

# --- Summary (counters count real matches, not cached misses) ---
oira_only   = sum(1 for r in rules_index if not r["in_agenda"])
at_oira     = sum(1 for r in rules_index if r.get("at_oira"))
regs_real   = sum(1 for r in rules_index if r.get("docket_url"))
fr_real     = sum(1 for r in rules_index if r.get("fr_proposed_url") or r.get("fr_final_url"))
ea_available = sum(1 for r in rules_index if (r.get("economic_analysis") or {}).get("state") == "available")
ea_missing   = sum(1 for r in rules_index if (r.get("economic_analysis") or {}).get("state") == "expected_missing")

print(f"\nWrote {len(rules_index)} records → {OUT}")
print(f"  in the current agenda:        {len(agenda_rules)}")
print(f"  added (at OIRA, not in agenda):{oira_only:>4}")
print(f"  currently at OIRA (total):    {at_oira}")
print(f"  with a regulations.gov docket:{regs_real:>4}")
print(f"  with a Federal Register doc:  {fr_real:>4}")
print(f"  economic analysis available:  {ea_available:>4}")
print(f"  econ-significant, none found: {ea_missing:>4}")