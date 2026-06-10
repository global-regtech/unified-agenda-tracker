"""
inspect-ria-states.py  (QA helper)

Dump the rules in a given economic-analysis state, with each rule's docket
documents, so you can judge precision/recall by hand.

  python inspect-ria-states.py expected_missing   # gap flags -- genuine gap vs missed RIA?
  python inspect-ria-states.py available            # spot-check the pulled RIA links
  python inspect-ria-states.py review               # LLM-tail candidates

For each supporting document it tags:
  << possible RIA?     title has economic-analysis wording our matcher doesn't catch
  (non-econ: NEPA/PRA?) title sounds analytical but is environmental / paperwork

At the end it tallies rules that have >=1 "possible RIA?" doc (likely MISSES,
worth fixing) vs rules with none (likely GENUINE GAPS, flag is correct).

Reads data/rules_index.json.
"""

import json
import re
import sys

STATE = sys.argv[1] if len(sys.argv) > 1 else "expected_missing"
MAX_DOCS = 20

# economic-analysis wording the main matcher does NOT already catch -> a likely miss
NEAR_MISS = re.compile(
    r"benefit[- ]cost|costs?\s+and\s+benefits?|\bbca\b|\bris\b|"
    r"technical support document|\btsd\b|"
    r"\beconomic\b|\bfiscal\b|monetiz|valuation|quantif|"
    r"impact (analysis|assessment|statement)", re.I)
# sounds analytical but is a DIFFERENT document type -> not a miss
FALSE_FRIEND = re.compile(
    r"environmental|\bnepa\b|\beis\b|\bea\b|paperwork|information collection|"
    r"\bburden\b|species|habitat|biological|scientific", re.I)


def tag(title):
    t = title or ""
    if NEAR_MISS.search(t) and not FALSE_FRIEND.search(t):
        return "   << possible RIA?"
    if FALSE_FRIEND.search(t):
        return "   (non-econ: NEPA/PRA?)"
    return ""


with open("data/rules_index.json", encoding="utf-8") as f:
    rules = json.load(f)

hits = [r for r in rules if (r.get("economic_analysis") or {}).get("state") == STATE]
print(f"{len(hits)} rules in state '{STATE}'\n" + "=" * 64)

likely_miss = likely_gap = 0
for r in hits:
    ea = r.get("economic_analysis") or {}
    agency = r.get("parent_agency_name") or r.get("agency_name") or ""
    docs = r.get("documents") or []
    any_candidate = any(tag(d.get("title")).strip().startswith("<<") for d in docs)
    flag = "  [has possible-RIA doc]" if any_candidate else ""
    print(f"\n{r.get('rin')}  {agency}  [{r.get('priority')}]{flag}")
    print(f"  {(r.get('title') or '')[:100]}")
    if ea.get("ria_title"):
        print(f"  PULLED -> {ea['ria_title']}  {ea.get('ria_url')}")
    if docs:
        print(f"  {len(docs)} supporting/other doc(s):")
        for d in docs[:MAX_DOCS]:
            print(f"    - [{d.get('documentType')}] {d.get('title')}{tag(d.get('title'))}")
        if len(docs) > MAX_DOCS:
            print(f"    ... (+{len(docs) - MAX_DOCS} more)")
    if any_candidate:
        likely_miss += 1
    else:
        likely_gap += 1

if STATE == "expected_missing":
    print("\n" + "=" * 64)
    print(f"Likely MISSES (>=1 possible-RIA doc): {likely_miss}")
    print(f"Likely GENUINE GAPS (none):           {likely_gap}")
    print("Skim the 'possible RIA?' lines to confirm; that ratio decides "
          "keyword-extend vs LLM-pass vs ship-as-is.")