"""Read-only independent raw-evidence review. Prints JSON; never treats absent evidence as pass."""
import collections
import json
import math
import sys
from pathlib import Path


def percentile(values, p=.95):
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)] if values else None


def analyze(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    gets = [r for r in rows if r["kind"] == "get"]
    calls = [r for r in rows if r["kind"] == "provider_start"]
    get_calls = [r for r in calls if str(r.get("request_id", "")).startswith("get")]
    by_request = collections.defaultdict(list)
    for r in rows:
        by_request[r.get("request_id")].append(r)
    mismatch, historical, exact, unavailable, unknown = [], [], [], [], []
    latency = collections.defaultdict(list)
    for r in gets:
        body = r.get("response") or {}
        summary, trace = body.get("summary"), body.get("trace", {})
        mat, expected = trace.get("materialization", {}), r.get("expected", {})
        eligible = trace.get("reuse_eligibility")
        label = "exact" if summary and eligible == "EXACT_VALIDATED" else "historical" if summary and eligible == "LATEST_STORED" else "pending" if r.get("status") == 202 else "other"
        if isinstance(r.get("duration"), (int,float)):
            latency[(r.get("phase"),label)].append(r["duration"])
        if not summary:
            unavailable.append(r.get("request_id")); continue
        if eligible == "LATEST_STORED":
            historical.append(r.get("request_id"))
        elif eligible == "EXACT_VALIDATED":
            exact.append(r.get("request_id"))
        for field, observed in (("asset_id",summary.get("asset_id")),("event_id",(summary.get("snapshot_basis") or {}).get("event_id",mat.get("event_id")))):
            if expected.get(field) is not None and observed is not None and expected[field] != observed:
                mismatch.append(dict(request_id=r.get("request_id"),field=field,expected=expected[field],observed=observed))
        # Compare request packet key captured BEFORE lookup with persisted return key.
        # It is runtime-derived, not an independent replacement for input-field checks.
        stages = [x for x in by_request[r.get("request_id")] if x["kind"]=="stage_start" and x.get("stage")=="cached_agent_review_summary_for_packet" and x.get("expected")]
        if stages:
            key = stages[-1]["expected"].get("summary_key")
            if key != mat.get("summary_key"):
                mismatch.append(dict(request_id=r.get("request_id"),field="summary_key",expected=key,observed=mat.get("summary_key"),historical_disclosed=eligible=="LATEST_STORED"))
        else:
            unknown.append(r.get("request_id"))
    before = [r for r in rows if r["kind"]=="business_snapshot" and r.get("position")=="before"]
    after = [r for r in rows if r["kind"]=="business_snapshot" and r.get("position")=="after"]
    business = {"status":"unknown"}
    if before and after:
        business = {"status":"equal" if before[-1]["data"]==after[-1]["data"] else "changed","before":before[-1]["data"],"after":after[-1]["data"]}
    counts = collections.Counter((r.get("expected") or {}).get("summary_key") for r in calls)
    phases = {r.get("name"):r["monotonic"] for r in rows if r["kind"]=="phase"}
    measurement = phases.get("drain",0)-phases.get("measurement",0) if "measurement" in phases and "drain" in phases else None
    polls = [r for r in rows if r["kind"]=="poll" and r.get("phase")=="measurement"]
    return {
        "raw":str(path),"rows":len(rows),"get_n":len(gets),"provider_start_n":len(calls),
        "get_provider_calls":len(get_calls),"get_provider_call_records":get_calls,
        "exact_response_n":len(exact),"historical_response_n":len(historical),"no_summary_n":len(unavailable),
        "identity_mismatch_records":mismatch,"missing_request_key_observation_n":len(unknown),
        "business_digest_comparison":business,
        "duplicate_call_candidates":{k:n for k,n in counts.items() if n>1 and k is not None},
        "latency_seconds":{"/".join(str(x) for x in k):{"n":len(v),"p95":percentile(v),"max":max(v)} for k,v in latency.items()},
        "measurement_seconds":measurement,"measurement_poll_completions":len(polls),
        "minimum_window_met":measurement is not None and measurement>=180 and len(polls)>=3,
        "interpretation":"Historical disclosed mismatch is strict-exact-contract failure, not hidden rebinding. Duplicate candidates require retry/refresh classification. Business comparison only covers supplied digest tables. Missing fields and service-derived expected key limit independence. This analyzer does not establish input-event conservation, SLA or capacity."
    }


if __name__ == "__main__":
    print(json.dumps(analyze(sys.argv[1]),indent=2,ensure_ascii=False))
