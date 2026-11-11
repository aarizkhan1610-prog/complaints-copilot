"""Related cases: other open complaints that look connected, so one handler sees the pattern."""
import re
from datetime import date

INCIDENT_RE = re.compile(r"\bINC-\d+\b")
SYSTEMIC_MIN = 3        # this many open cases with the same product and root cause suggests a systemic issue
WINDOW_DAYS = 30


def incidents(case):
    text = case["complaint"] + " " + " ".join(n["text"] for n in case["case_notes"])
    return set(INCIDENT_RE.findall(text))


def related_cases(case_id, cases, analyses):
    """cases: {id: case}; analyses: {id: CaseAnalysis}. Returns (matches, systemic_note)."""
    me, a = cases[case_id], analyses.get(case_id)
    if a is None or not a.is_complaint:
        return [], None
    my_inc, my_day = incidents(me), date.fromisoformat(me["received"])
    out = []
    for cid, c in cases.items():
        b = analyses.get(cid)
        if cid == case_id or b is None or not b.is_complaint:
            continue
        reasons, score = [], 0
        shared = my_inc & incidents(c)
        if shared:
            reasons.append("same incident " + ", ".join(sorted(shared)))
            score += 3
        if b.root_cause == a.root_cause and b.product == a.product:
            reasons.append(f"same root cause and product ({a.root_cause}, {a.product})")
            score += 2
        elif b.root_cause == a.root_cause:
            reasons.append(f"same root cause ({a.root_cause})")
            score += 1
        if not score:
            continue
        days = abs((date.fromisoformat(c["received"]) - my_day).days)
        if days <= WINDOW_DAYS:
            score += 0.5
        out.append({"case_id": cid, "score": score, "reasons": reasons, "days_apart": days,
                    "summary": b.summary, "product": b.product, "root_cause": b.root_cause})
    out.sort(key=lambda x: (-x["score"], x["days_apart"], x["case_id"]))
    cluster = [x for x in out if "same root cause and product" in " ".join(x["reasons"]) and x["days_apart"] <= WINDOW_DAYS]
    note = None
    if any(x["reasons"][0].startswith("same incident") for x in out):
        note = "Another complaint names the same incident. Check whether one fix and one root-cause review cover both."
    elif len(cluster) + 1 >= SYSTEMIC_MIN:
        note = (f"{len(cluster) + 1} open complaints about {a.root_cause.lower()} on {a.product.lower()} within "
                f"{WINDOW_DAYS} days. This may be systemic (CH-6): consider telling Senior Complaints Review.")
    return out[:5], note
