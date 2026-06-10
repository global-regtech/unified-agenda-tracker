"""
detect-ria.py  (CLI / validation tool)

Thin command-line wrapper around ria_detection.py. The classifier and signal
logic live in that module; this file only handles the two run modes:

  python detect-ria.py --validate   -- score the classifier against ria_assessment.json
  python detect-ria.py --apply       -- attach signals to an index and report coverage
                                        (the daily pipeline computes this in
                                        build-rules-index.py now; --apply is for
                                        ad-hoc testing against a separate --out file)
"""

import argparse
import json
import os

from ria_detection import classify_documents, economic_analysis_signal


# --- mode 1: validate against the 50-docket sample --------------------------
def validate(path="ria_assessment.json"):
    if not os.path.exists(path):
        raise SystemExit(f"{path} not found -- run assess-ria-titles.py first.")
    with open(path, encoding="utf-8") as f:
        sample = json.load(f)

    sig_hit = sig_tail = sig_none = ctrl_hit = no_doc_significant = 0
    llm_candidates = []
    for rec in sample:
        v = classify_documents(rec.get("supporting", []))
        is_sig = rec.get("significant")
        docket = rec.get("docket_id") or ""
        has_supporting = bool(rec.get("supporting"))
        if v["has_ria"]:
            tag = "RIA " if v["confidence"] == "high" else "tail"
            print(f"[{tag}] {'SIG ' if is_sig else 'ctrl'} {docket:<22} -> {v['best']['title']}")
            if is_sig and v["confidence"] == "high":
                sig_hit += 1
            elif is_sig:
                sig_tail += 1
            if not is_sig:
                ctrl_hit += 1
        elif is_sig:
            sig_none += 1
            if not has_supporting:
                no_doc_significant += 1
            else:
                llm_candidates.append((docket, [d["title"] for d in rec["supporting"]]))

    n_sig = sum(1 for r in sample if r.get("significant"))
    print("\n--- summary -------------------------------------------------")
    print(f"Significant dockets: {n_sig}")
    print(f"  flagged RIA (high confidence): {sig_hit}")
    print(f"  flagged via tail (LLM-confirm): {sig_tail}")
    print(f"  not flagged: {sig_none}  (of which {no_doc_significant} had NO supporting docs)")
    print(f"Control dockets: {len(sample) - n_sig}  -> false positives: {ctrl_hit}")
    if llm_candidates:
        print("\nLLM-pass candidates (significant, has docs, no keyword match):")
        for docket, titles in llm_candidates:
            print(f"  {docket}: {titles}")


# --- mode 2: apply to an index (ad-hoc; pipeline does this in build-rules-index) --
def apply_to_index(index_path="data/rules_index.json", out_path=None):
    if not os.path.exists(index_path):
        raise SystemExit(f"{index_path} not found.")
    with open(index_path, encoding="utf-8") as f:
        rules = json.load(f)

    counts = {}
    with_docs = linkable = 0
    for rule in rules:
        sig = economic_analysis_signal(rule)
        rule["economic_analysis"] = sig
        counts[sig["state"]] = counts.get(sig["state"], 0) + 1
        if rule.get("documents"):
            with_docs += 1
        if sig["state"] == "available":
            linkable += 1

    print("--- apply summary -------------------------------------------")
    print(f"Total rules: {len(rules)}   (with stored documents: {with_docs})")
    for state in ("available", "review", "expected_missing", "expected_elsewhere",
                  "pending", "none", "unknown"):
        print(f"  {state:<19} {counts.get(state, 0)}")
    print(f"Linkable analyses pulled: {linkable}")
    if with_docs == 0:
        print("\nNote: no rule carries a `documents` list. Run fetch-regulations-gov.py "
              "and rebuild the index first; until then states collapse to "
              "pending/expected_elsewhere/unknown.")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2)
        print(f"\nWrote enriched index -> {out_path}")


def main():
    ap = argparse.ArgumentParser(description="RIA detector CLI (logic in ria_detection.py).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true", help="score against ria_assessment.json (default)")
    mode.add_argument("--apply", action="store_true", help="attach signals to an index")
    ap.add_argument("--sample", default="ria_assessment.json")
    ap.add_argument("--index", default="data/rules_index.json")
    ap.add_argument("--out", default=None, help="with --apply, write enriched index here (non-destructive)")
    args = ap.parse_args()
    if args.apply:
        apply_to_index(args.index, args.out)
    else:
        validate(args.sample)


if __name__ == "__main__":
    main()