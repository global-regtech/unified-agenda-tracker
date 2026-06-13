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
from datetime import date, datetime, timedelta
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

oira_meetings_path = Path("data/oira_meetings.json")
if oira_meetings_path.exists():
    oira_meetings = json.loads(oira_meetings_path.read_text()).get("records", {})
    print(f"OIRA meetings:    {len(oira_meetings)} RINs")
else:
    oira_meetings = {}
    print("OIRA meetings:    no data file (will skip meeting join)")

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

# Industry vs advocacy classification — narrow v1 heuristics. False positives
# fall to "Other" rather than getting force-classified. Refine after seeing
# real-world distribution.
INDUSTRY_PATTERNS = __import__("re").compile(
    # Whole-word industry markers
    r"\b(?:"
    r"Association|Associations|Chamber|Council|Institute|Federation|"
    r"Manufacturers|Industry|Industries|Trade|"
    r"Inc|LLC|LLP|Corp|Corporation|Company|Holdings|"
    r"Strategies|Associates|"
    r"Therapeutics|Pharmaceuticals|Biotech|Energy|Aviation|"
    r"Manatt|McDermott|FGS"
    r")\b"
    # Multi-word industry phrases
    r"|\b(?:"
    r"Strategy Group|Policy Group|Policy Strategies|"
    r"Government Affairs|Government Relations|"
    r"Innovation Alliance|Industry Alliance|"
    r"Builders and Contractors|Advisory Group|"
    r"Powers Law|Tiber Creek"
    r")\b"
    # Alliance for [Capitalized Word]
    r"|\bAlliance for [A-Z]\w+\b"
    # Law firm partner patterns
    r"|& (?:Phelps|Knight|Levy|Schulte|Bird|Bond|Goldstein|Phillips|Watkins)\b"
    r"|\bHolland & ",
    __import__("re").IGNORECASE,
)

ADVOCACY_PATTERNS = __import__("re").compile(
    # Whole-word advocacy markers
    r"\b(?:"
    r"Coalition|ACLU|League|Justice|Rights|Action|"
    r"Citizens|Earthjustice|Mothers|"
    r"NAACP|NRDC|"
    r"Wildlife|Wilderness|Defenders|Guardians|FUSEE|"
    r"Union|Advocates|Network|Project"
    r")\b"
    # Multi-word advocacy phrases
    r"|\b(?:"
    r"Center for|Sierra Club|Defense Fund|Public Interest|"
    r"Watchdog|Moms Clean|Environmental|Conservation|"
    r"Civil Liberties|Law Center|Legal Defense|Legal Aid|"
    r"Lawyers Committee|Lawyers' Committee|Due Process|"
    r"Southern Poverty|National Women|National Fair Housing|"
    r"Food & Water Watch|Water Watch|"
    r"Workers of America|Laborers'|Mine Workers|"
    r"Campaign for|Tobacco-Free|Cancer Prevention|"
    r"Taxpayers for|Fair Housing|"
    r"Resource Councils|Federation of Teachers|Federation of Labor"
    r")\b"
    # Initiative as a noun (avoid "Initiative for [X]" being industry)
    r"|\bInitiative\b",
    __import__("re").IGNORECASE,
)


def aggregate_meetings(rin):
    """Compute per-rule meeting aggregates from oira_meetings.

    Returns None if no record (preserves the distinction between 'we know
    there are 0 meetings' and 'we haven't fetched meetings for this rule').
    """
    record = oira_meetings.get(rin)
    if not record:
        return None

    meeting_count = record.get("meeting_count", 0)
    meetings = record.get("meetings", [])

    if meeting_count == 0:
        return {
            "count": 0, "recent_count": 0, "last_date": None,
            "outside_orgs": [], "outside_org_count": 0,
            "industry_orgs": [], "advocacy_orgs": [], "other_orgs": [],
            "has_more_unscraped": False,
        }

    # Recent = meetings within last 14 days (matches the imminence-weight window)
    cutoff = date.today() - timedelta(days=14)
    recent_count = sum(
        1 for m in meetings
        if (d := _parse_iso_date(m.get("date"))) and d >= cutoff
    )

    # Dedupe requestor orgs (case-insensitive), preserve display case
    seen_keys = set()
    outside_orgs = []
    for m in meetings:
        org = (m.get("requestor_org") or "").strip()
        if not org:
            continue
        key = org.lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        outside_orgs.append(org)

    industry, advocacy, other = [], [], []
    for org in outside_orgs:
        if ADVOCACY_PATTERNS.search(org):
            advocacy.append(org)
        elif INDUSTRY_PATTERNS.search(org):
            industry.append(org)
        else:
            other.append(org)

    return {
        "count":               meeting_count,
        "recent_count":        recent_count,
        "last_date":           record.get("last_meeting_date"),
        "outside_orgs":        outside_orgs,
        "outside_org_count":   len(outside_orgs),
        "industry_orgs":       industry,
        "advocacy_orgs":       advocacy,
        "other_orgs":          other,
        "has_more_unscraped":  record.get("has_more", False),
    }


def _parse_iso_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date() if s else None
    except ValueError:
        return None

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
    record["meetings"] = aggregate_meetings(record["rin"])

OUT.write_text(json.dumps(rules_index, indent=2))

# --- Summary (counters count real matches, not cached misses) ---
oira_only   = sum(1 for r in rules_index if not r["in_agenda"])
at_oira     = sum(1 for r in rules_index if r.get("at_oira"))
regs_real   = sum(1 for r in rules_index if r.get("docket_url"))
fr_real     = sum(1 for r in rules_index if r.get("fr_proposed_url") or r.get("fr_final_url"))
ea_available = sum(1 for r in rules_index if (r.get("economic_analysis") or {}).get("state") == "available")
ea_missing   = sum(1 for r in rules_index if (r.get("economic_analysis") or {}).get("state") == "expected_missing")
with_meetings = sum(1 for r in rules_index if (r.get("meetings") or {}).get("count", 0) > 0)
heavy_lobbying = sum(1 for r in rules_index if (r.get("meetings") or {}).get("outside_org_count", 0) >= 5)

print(f"\nWrote {len(rules_index)} records → {OUT}")
print(f"  in the current agenda:        {len(agenda_rules)}")
print(f"  added (at OIRA, not in agenda):{oira_only:>4}")
print(f"  currently at OIRA (total):    {at_oira}")
print(f"  with a regulations.gov docket:{regs_real:>4}")
print(f"  with a Federal Register doc:  {fr_real:>4}")
print(f"  economic analysis available:  {ea_available:>4}")
print(f"  econ-significant, none found: {ea_missing:>4}")
print(f"  with logged EO 12866 meetings:{with_meetings:>4}")
print(f"  heavy lobbying (5+ orgs):     {heavy_lobbying:>4}")