"""
ria_detection.py  (importable library -- underscore name, not a runnable script)

The RIA / economic-analysis classifier and cross-tab signal. Imported by both
-titles.py (the CLI/validation tool) and build-rules-index.py (the pipeline).
Keep this file free of CLI / argparse / file-IO concerns -- pure logic only, so
the thing the build depends on stays small and stable.

regulations.gov has no "RIA" document type -- analyses are filed as "Supporting &
Related" (occasionally "Other") and identified ONLY by title. We match titles
with guardrails, then fold the result against significance + publication stage.

SIGNAL STATES (exactly one per rule; only `available` ever pulls a document):
  available           high-confidence RIA found -> pull ria_title + ria_url (one doc)
  review              only an ambiguous/tail match -> hand to LLM, show nothing yet
  expected_missing    econ-significant + published + docket has docs, none an RIA -> gap flag
  expected_elsewhere  econ-significant + published + no docket/docs -> likely in rule preamble
  pending             econ-significant + NOT yet published -> analysis expected later
  none                not econ-significant, nothing found -> routine, show nothing
  unknown             no docket/docs and not econ-significant -> can't say
"""

import re

# --- patterns ---------------------------------------------------------------
STRONG = [
    r"\bregulatory impact analysis\b",
    r"\bregulatory impact assessment\b",
    r"\beconomic impact analysis\b",
    r"\bcost[- ]benefit analysis\b",
    r"\bcost[- ]benefit\b",
    r"\bregulatory flexibility analysis\b",
    r"\bp?ria\b",        # RIA, PRIA
    r"\b[if]rfa\b",      # IRFA, FRFA
    r"\bcba\b",          # cost-benefit analysis (disambiguated below)
]
MEDIUM = [
    r"\beconomic analysis\b",
    r"\bregulatory analysis\b",
    r"\bregulatory assessment\b",
    r"\beconomic impact\b",
]
TAIL = [
    r"\bfee study\b",
    r"\bfee analysis\b",
    r"\beconomic study\b",
]
REFERENCE_GUARDS = [
    r"\breference\b",
    r"available at",
    r"\baccessed\b",
    r"https?://",
    r"guidelines for",
]

CBA_RE = re.compile(r"\bcba\b", re.I)
BARGAINING_RE = re.compile(r"collective bargaining|bargaining agreement", re.I)
OMB_TAB = re.compile(r"(submitted to omb|cleared by omb|track changes|\btab [abc]\b)", re.I)

STRONG_RE = [re.compile(p, re.I) for p in STRONG]
MEDIUM_RE = [re.compile(p, re.I) for p in MEDIUM]
TAIL_RE = [re.compile(p, re.I) for p in TAIL]
REF_RE = [re.compile(p, re.I) for p in REFERENCE_GUARDS]
STRONG_NON_CBA_RE = [re.compile(p, re.I) for p in STRONG if p != r"\bcba\b"]


def _norm(title):
    # underscores act as separators in these titles; collapse to spaces so \b works
    return re.sub(r"_+", " ", (title or "").lower())


def _looks_like_reference(t):
    return any(r.search(t) for r in REF_RE)


def _strong_hit(t):
    """Strong match, but a bare CBA in a collective-bargaining title doesn't count."""
    if not any(r.search(t) for r in STRONG_RE):
        return False
    if CBA_RE.search(t) and BARGAINING_RE.search(t):
        return any(r.search(t) for r in STRONG_NON_CBA_RE)
    return True


def doc_url(document_id):
    return f"https://www.regulations.gov/document/{document_id}" if document_id else None


def classify_documents(docs):
    """docs: [{documentType, title, documentId}]. Pure; no API calls."""
    matches = []
    for d in docs or []:
        if d.get("documentType") in ("Proposed Rule", "Rule"):
            continue  # the rule text, not the analysis
        title = d.get("title") or ""
        t = _norm(title)
        if _looks_like_reference(t):
            continue  # citation, not the document itself
        tier = None
        if _strong_hit(t):
            tier = "strong"
        elif any(r.search(t) for r in MEDIUM_RE):
            tier = "medium"
        elif any(r.search(t) for r in TAIL_RE):
            tier = "tail"
        if tier:
            score = {"strong": 3, "medium": 2, "tail": 1}[tier]
            if OMB_TAB.search(title):
                score += 1
            matches.append({"title": title, "documentId": d.get("documentId"),
                            "tier": tier, "score": score})

    matches.sort(key=lambda m: m["score"], reverse=True)
    high = [m for m in matches if m["tier"] in ("strong", "medium")]
    if high:
        return {"has_ria": True, "confidence": "high", "best": high[0], "matches": matches}
    if matches:
        return {"has_ria": True, "confidence": "tail", "best": matches[0],
                "matches": matches, "needs_llm": True}
    return {"has_ria": False, "confidence": None, "best": None, "matches": []}


# --- significance + stage gating --------------------------------------------
def is_economically_significant(priority):
    """RIA is legally tied to economically-significant (3(f)(1)), NOT 'Other Significant'."""
    p = (priority or "").lower()
    return ("economically significant" in p
            or "3(f)(1)" in p or "section 3(f)(1)" in p or "3f1" in p)


def is_published(rule):
    return bool(rule.get("fr_proposed_url") or rule.get("fr_final_url")
                or rule.get("fr_proposed_date") or rule.get("fr_final_date"))


def economic_analysis_signal(rule):
    """One cross-tab state per rule. Only `available` pulls a document."""
    docs = rule.get("documents")
    v = classify_documents(docs) if docs else {"confidence": None, "best": None}
    econ_sig = is_economically_significant(rule.get("priority"))
    published = is_published(rule)
    has_docs = bool(docs)

    if v.get("confidence") == "high":
        best = v["best"]
        return {"state": "available", "label": "Economic analysis available",
                "ria_title": best["title"], "ria_url": doc_url(best["documentId"]),
                "needs_llm": False}

    if v.get("confidence") == "tail":
        return {"state": "review", "label": None,
                "ria_title": None, "ria_url": None, "needs_llm": True,
                "candidate_title": v["best"]["title"]}

    if econ_sig and published and has_docs:
        return {"state": "expected_missing",
                "label": "Economically significant, published \u2014 no analysis posted",
                "ria_title": None, "ria_url": None, "needs_llm": False}
    if econ_sig and published and not has_docs:
        return {"state": "expected_elsewhere",
                "label": "Analysis not in regulations.gov (check rule preamble)",
                "ria_title": None, "ria_url": None, "needs_llm": False}
    if econ_sig and not published:
        return {"state": "pending", "label": "Analysis expected at publication",
                "ria_title": None, "ria_url": None, "needs_llm": False}
    if not has_docs:
        return {"state": "unknown", "label": None,
                "ria_title": None, "ria_url": None, "needs_llm": False}
    return {"state": "none", "label": None,
            "ria_title": None, "ria_url": None, "needs_llm": False}