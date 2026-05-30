"""
parse-agenda-content.py
Parses data/agenda_content_raw.xml into data/agenda_rules.json.

Each record is one <RIN_INFO> entry — one rule in the Unified Agenda.
The ABSTRACT field contains HTML wrapped in CDATA; BeautifulSoup strips it to plain text.

Run:  python parse-agenda-content.py
"""
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup

SRC = Path("data/agenda_content_raw.xml")
OUT = Path("data/agenda_rules.json")


def strip_html(html_text):
    """Strip HTML tags from a CDATA abstract, returning clean plain text."""
    if not html_text or not html_text.strip():
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def parse_rules(xml_path):
    print(f"Parsing {xml_path} ...")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rules = []
    skipped = 0

    for rin_info in root.findall("RIN_INFO"):
        rin = rin_info.findtext("RIN", "").strip()
        if not rin:
            skipped += 1
            continue

        pub_id = rin_info.findtext("PUBLICATION/PUBLICATION_ID", "").strip()

        rule = {
            # --- Core identifiers ---
            "rin":                  rin,
            "pub_id":               pub_id,

            # --- Rule content ---
            "title":                rin_info.findtext("RULE_TITLE", "").strip(),
            "abstract":             strip_html(rin_info.findtext("ABSTRACT", "")),

            # --- Classification ---
            "priority":             rin_info.findtext("PRIORITY_CATEGORY", "").strip(),
            "stage":                rin_info.findtext("RULE_STAGE", "").strip(),
            "rin_status":           rin_info.findtext("RIN_STATUS", "").strip(),
            "major":                rin_info.findtext("MAJOR", "No").strip() == "Yes",
            "in_reg_plan":          rin_info.findtext("RPLAN_ENTRY", "No").strip() == "Yes",

            # --- Agency (sub-agency level) ---
            "agency_code":          rin_info.findtext("AGENCY/CODE", "").strip(),
            "agency_name":          rin_info.findtext("AGENCY/NAME", "").strip(),
            "agency_acronym":       rin_info.findtext("AGENCY/ACRONYM", "").strip(),

            # --- Parent agency (top-level department) ---
            "parent_agency_code":   rin_info.findtext("PARENT_AGENCY/CODE", "").strip(),
            "parent_agency_name":   rin_info.findtext("PARENT_AGENCY/NAME", "").strip(),
            "parent_agency_acronym":rin_info.findtext("PARENT_AGENCY/ACRONYM", "").strip(),

            # --- Source link ---
            "reginfo_url": (
                f"https://www.reginfo.gov/public/do/eAgendaViewRule"
                f"?pubId={pub_id}&RIN={rin}"
            ),
        }

        rules.append(rule)

    if skipped:
        print(f"  Skipped {skipped} entries with no RIN")

    return rules


rules = parse_rules(SRC)

OUT.write_text(json.dumps(rules, indent=2))
print(f"  Wrote {len(rules)} rules → {OUT}")

# --- Quick breakdown ---
def tally(rules, field):
    counts = {}
    for r in rules:
        val = r.get(field, "")
        counts[val] = counts.get(val, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])

print("\nBy stage:")
for stage, n in tally(rules, "stage"):
    print(f"  {n:>5}  {stage}")

print("\nBy priority:")
for priority, n in tally(rules, "priority"):
    print(f"  {n:>5}  {priority}")

print(f"\nMajor rules: {sum(1 for r in rules if r['major'])}")
print(f"In regulatory plan: {sum(1 for r in rules if r['in_reg_plan'])}")