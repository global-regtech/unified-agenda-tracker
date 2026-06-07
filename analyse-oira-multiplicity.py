"""
analyze-oira-multiplicity.py

Answers: "do rules go to OIRA more than once, and how often?" -- WITHOUT
scraping anything new. Reads data/rules_index.json only.

The key signal: a rule that is AT OIRA right now but ALREADY has a published
proposed rule must have been to OIRA before (the proposed rule's publication
implies a prior, now-concluded NPRM review). So the current pending review is
its 2nd+ review. That gives a lower bound on how common multiplicity is.

Run from the repo root:  python analyze-oira-multiplicity.py
"""

import json
import os
from datetime import datetime

INDEX_PATH = os.path.join("data", "rules_index.json")


def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%b %d, %Y"):
        try:
            return datetime.strptime(s[:len(fmt) + 4], fmt)
        except (ValueError, TypeError):
            continue
    return None


def main():
    if not os.path.exists(INDEX_PATH):
        raise SystemExit(f"Cannot find {INDEX_PATH}. Run from the repo root.")
    with open(INDEX_PATH, encoding="utf-8") as f:
        rules = json.load(f)

    total = len(rules)
    at_oira = [r for r in rules if r.get("at_oira")]

    # --- the lower-bound signal: at OIRA now AND a proposed rule already exists
    second_review = [r for r in at_oira if r.get("fr_proposed_date")]
    also_final = [r for r in second_review if r.get("fr_final_date")]

    # --- cross-check by dates: pending review received AFTER the proposed rule
    after_proposed = []
    for r in at_oira:
        rec = parse_date(r.get("oira_received"))
        prop = parse_date(r.get("fr_proposed_date"))
        if rec and prop and rec > prop:
            after_proposed.append(r)

    print(f"Total rules in index:                         {total}")
    print(f"Currently at OIRA:                            {len(at_oira)}")
    print("-" * 56)
    pct = (100 * len(second_review) / len(at_oira)) if at_oira else 0
    print(f"At OIRA *and* proposed rule already published:{len(second_review):>5}  "
          f"({pct:.0f}% of those at OIRA)")
    print(f"   ^ these are on their 2nd+ OIRA review")
    print(f"   ...of which a final rule also exists:      {len(also_final):>5}")
    print(f"Date cross-check (received > proposed date):  {len(after_proposed):>5}")
    print("-" * 56)

    if at_oira:
        if pct >= 20:
            verdict = ("COMMON. The timeline needs to support OIRA appearing twice "
                       "(proposed-stage review + final-stage review).")
        elif pct >= 5:
            verdict = ("NOT RARE. Worth handling, but a single node with a 'stage' "
                       "label may be an acceptable v1.")
        else:
            verdict = ("RARE. A single OIRA node is fine for v1; revisit later.")
        print("VERDICT:", verdict)

    # a few concrete examples to eyeball
    if second_review:
        print("\nExamples (at OIRA with a proposed rule already out):")
        for r in second_review[:8]:
            print(f"  RIN {r.get('rin'):12}  proposed {r.get('fr_proposed_date')}  "
                  f"oira_received {r.get('oira_received')}  | {str(r.get('title'))[:50]}")


if __name__ == "__main__":
    main()