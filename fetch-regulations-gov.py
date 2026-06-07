import json
import time
import os
import requests
from datetime import datetime, date, timezone, timedelta

API_KEY = os.environ.get("REGULATIONS_GOV_API_KEY", "DEMO_KEY")
BASE_URL = "https://api.regulations.gov/v4"
INPUT_FILE = "data/rules_index.json"
OUTPUT_FILE = "data/regulations_gov.json"

MISS_TTL_DAYS = 30                 # re-search a "no docket" RIN after this long
COMMENT_REFRESH_GRACE_DAYS = 30    # re-pull count/window while a period is open or recently closed
FETCH_COMMENT_COUNT = True         # set False to skip the per-docket comment-count call (halves extra calls)
THROTTLE_SECONDS = 2               # sleep after EVERY API call (raise toward 3.6 to stay under 1,000/hr)
COMMENT_FETCH_BUDGET = 300         # max comment-data fetches per run (0 = unlimited). Spreads the one-time
                                   # backfill over several daily runs instead of one multi-hour run.


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def as_date(s):
    """regulations.gov returns ISO datetimes; the frontend wants YYYY-MM-DD."""
    return s[:10] if isinstance(s, str) and len(s) >= 10 else s


def api_get(session, path, params):
    params = {**params, "api_key": API_KEY}
    resp = session.get(f"{BASE_URL}{path}", params=params, timeout=20)
    resp.raise_for_status()
    time.sleep(THROTTLE_SECONDS)
    return resp.json()


def needs_docket_refresh(rec):
    """Re-search only for misses older than the TTL. Hits keep their docket_id forever
    (docket IDs don't change)."""
    if rec.get("docket_id"):
        return False
    fetched_at = rec.get("fetched_at")
    if not fetched_at:
        return True
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    return age > timedelta(days=MISS_TTL_DAYS)


def needs_comment_refresh(rec):
    """Comment count/window are time-varying, so unlike docket_id they can't be cached
    forever. Refresh while the window is open or recently closed (count still moving);
    leave long-closed dockets alone."""
    if not rec.get("docket_id"):
        return False
    if not rec.get("comment_fetched_at"):
        return True                       # never pulled comment data (incl. old cache format)
    end = rec.get("comment_end_date")
    if not end:
        return True
    try:
        end_d = datetime.strptime(end[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return (date.today() - end_d).days <= COMMENT_REFRESH_GRACE_DAYS


def fetch_docket(rin, session):
    data = api_get(session, "/dockets", {"filter[searchTerm]": rin})
    results = data.get("data", [])
    if not results:
        return None
    d = results[0]
    attrs = d.get("attributes", {})
    return {
        "rin": rin,
        "docket_id": d.get("id"),
        "docket_url": f"https://www.regulations.gov/docket/{d.get('id')}",
        "title": attrs.get("title"),
        "docket_type": attrs.get("docketType"),
        "last_modified": attrs.get("lastModifiedDate"),
        "fetched_at": _now_iso(),
    }


def fetch_comment_info(docket_id, session):
    """Comment window (from the docket's documents) + comment count (from /comments meta).
    The docket object itself carries neither reliably — that's why the original script
    saw null comment dates even when comments existed."""
    info = {
        "comment_start_date": None,
        "comment_end_date": None,
        "open_for_comment": None,
        "comment_count": None,
        "comment_fetched_at": _now_iso(),
    }

    # window: scan documents for the comment-bearing one; prefer an open window,
    # else the latest-ending one
    docs = api_get(session, "/documents",
                   {"filter[docketId]": docket_id, "page[size]": 250, "sort": "-postedDate"})
    windows = [d.get("attributes", {}) for d in docs.get("data", [])
               if d.get("attributes", {}).get("commentEndDate")]
    if windows:
        open_windows = [w for w in windows if w.get("openForComment")]
        chosen = (open_windows or
                  sorted(windows, key=lambda w: w.get("commentEndDate") or "", reverse=True))[0]
        info["comment_start_date"] = as_date(chosen.get("commentStartDate"))
        info["comment_end_date"] = as_date(chosen.get("commentEndDate"))
        info["open_for_comment"] = chosen.get("openForComment")

    # count: totalElements from the comments listing (we don't need the comments themselves)
    if FETCH_COMMENT_COUNT:
        comments = api_get(session, "/comments",
                           {"filter[docketId]": docket_id, "page[size]": 5})
        info["comment_count"] = comments.get("meta", {}).get("totalElements")

    return info


def main():
    with open(INPUT_FILE) as f:
        rules = json.load(f)

    existing = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            existing = json.load(f)

    seen = set()
    rins = [r["rin"] for r in rules if r.get("rin")]
    rins = [r for r in rins if not (r in seen or seen.add(r))]   # de-dupe, keep order
    print(f"RINs in index:  {len(rins)} (now includes OIRA-only rules via the union build)")
    print(f"Already cached: {len(existing)}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "unified-agenda-tracker/1.0 (github.com/abulix/unified-agenda-tracker)"
    })

    searched = comment_refreshed = skipped = errors = deferred = 0
    err_rins = []
    budget = COMMENT_FETCH_BUDGET if COMMENT_FETCH_BUDGET else float("inf")
    comment_fetched = 0

    for i, rin in enumerate(rins):
        cached = existing.get(rin)
        try:
            if cached and cached.get("docket_id"):
                # known docket: id is stable, but refresh comment data if the window is live
                if needs_comment_refresh(cached):
                    if comment_fetched < budget:
                        cached.update(fetch_comment_info(cached["docket_id"], session))
                        comment_fetched += 1
                        comment_refreshed += 1
                        print(f"  [{i+1}/{len(rins)}] {rin} → comments refreshed ({cached.get('comment_count')})")
                    else:
                        deferred += 1            # over budget this run; eligible again next run
                else:
                    skipped += 1
            elif cached and not needs_docket_refresh(cached):
                skipped += 1                                     # recent miss, leave it
            else:
                rec = fetch_docket(rin, session)
                searched += 1
                if rec:
                    if comment_fetched < budget:
                        rec.update(fetch_comment_info(rec["docket_id"], session))
                        comment_fetched += 1
                        print(f"  [{i+1}/{len(rins)}] {rin} → {rec['docket_id']} ({rec.get('comment_count')})")
                    else:
                        # store the docket now (its id is stable); comment data backfills next run
                        deferred += 1
                        print(f"  [{i+1}/{len(rins)}] {rin} → {rec['docket_id']} (comments deferred)")
                    existing[rin] = rec
                else:
                    existing[rin] = {"rin": rin, "docket_id": None, "fetched_at": _now_iso()}
                    print(f"  [{i+1}/{len(rins)}] {rin} → not found")
        except Exception as e:
            errors += 1
            err_rins.append(rin)
            print(f"  [{i+1}/{len(rins)}] {rin} → ERROR: {e}")
            time.sleep(10)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(existing, f, indent=2)

    with_dockets = sum(1 for v in existing.values() if v.get("docket_id"))
    print(f"\nDone. searched={searched}, comment_refreshed={comment_refreshed}, "
          f"deferred={deferred}, skipped={skipped}, errors={errors}")
    print(f"Total cached: {len(existing)}  |  with a docket: {with_dockets}")
    if deferred:
        print(f"{deferred} docket(s) hit the per-run budget "
              f"(COMMENT_FETCH_BUDGET={COMMENT_FETCH_BUDGET}) — re-run to continue the backfill.")
    if err_rins:
        print("Errors:", err_rins)


if __name__ == "__main__":
    main()