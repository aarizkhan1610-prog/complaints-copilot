"""Before/after measures for the three problems named in the brief.

1. A growing backlog            -> queue order and triage throughput
2. Finding information across case notes and policy documents -> reading and lookup load
3. Incomplete handovers to specialist teams -> handovers that would have gone out incomplete

Measured figures come from the 25 synthetic cases, the saved AI responses and the hand-written
answer key (data/labels.json). Time figures depend on the assumptions below, which a pilot would
replace with real timings.
"""
from dataclasses import dataclass

from .data import load_policies

URGENT_STATUSES = {"Breached", "Critical"}


@dataclass
class Assumptions:
    manual_triage_min: float = 30.0      # read notes, search policies, classify, check deadline
    copilot_review_min: float = 10.0     # check the AI draft, verified quotes and flags
    manual_handover_min: float = 20.0    # write the ESC-3 pack by hand
    copilot_handover_min: float = 5.0    # fill flagged gaps and send
    return_rework_min: float = 30.0      # a returned handover: chase, re-gather, re-send
    complaints_per_month: int = 1000
    handler_minutes_per_day: int = 390   # 6.5 productive hours


def is_urgent(label, deadline_status):
    """A case that should be seen first, according to the answer key and the deadline."""
    return bool(label["vulnerable"] or label["severity"] == "High" or deadline_status in URGENT_STATUSES)


def case_metrics(case, result, label):
    """Measured effort for one case, without and with the copilot."""
    a = result["analysis"]
    pol = load_policies()
    case_words = len(case["complaint"].split()) + sum(len(n["text"].split()) for n in case["case_notes"])
    verified = [c for c, chk in zip(a.policy_citations, result["citations"]) if chk["status"] == "verified"]
    cited_ids = sorted({c.clause_id for c in verified})
    needs_specialist = bool(label["specialist_team"])
    true_gaps = set(label["handover_gaps"]) if needs_specialist else set()
    flagged = set(result["gaps"]) if a.specialist_teams else set()
    rows = result["completeness"]
    return {
        "case_id": case["id"],
        "case_words": case_words,
        "notes": len(case["case_notes"]),
        "clauses_total": len(pol),
        "policy_docs": len({k.split("-")[0] for k in pol}),
        "policy_words": sum(len(v["text"].split()) for v in pol.values()),
        "clauses_cited": len(cited_ids),
        "cited_words": sum(len(pol[c]["text"].split()) for c in cited_ids if c in pol),
        "cited_ids": cited_ids,
        "citations_total": len(result["citations"]),
        "citations_verified": len(verified),
        "timeline_events": len(a.timeline),
        "fields_drafted": sum(1 for r in rows if r["ok"]),
        "fields_total": len(rows),
        "needs_specialist": needs_specialist,
        "true_gaps": sorted(true_gaps),
        "gaps_caught": sorted(true_gaps & flagged),
        "gaps_missed": sorted(true_gaps - flagged),
        "would_be_returned": bool(true_gaps),
        "blocked_before_send": bool(true_gaps) and bool(flagged),
    }


def queue_orders(items):
    """items: list of dicts with case_id, received, days_left, priority, urgent.
    Returns (arrival_order, copilot_order) as lists of case ids."""
    arrival = [x["case_id"] for x in sorted(items, key=lambda x: (x["received"], x["case_id"]))]
    copilot = [x["case_id"] for x in sorted(items, key=lambda x: (-x["priority"], x["days_left"], x["case_id"]))]
    return arrival, copilot


def backlog_summary(items, a: Assumptions):
    arrival, copilot = queue_orders(items)
    urgent = {x["case_id"] for x in items if x["urgent"]}
    n_urgent = len(urgent)

    def mean_pos(order):
        pos = [i + 1 for i, c in enumerate(order) if c in urgent]
        return sum(pos) / len(pos) if pos else 0

    def in_top(order, k):
        return sum(1 for c in order[:k] if c in urgent)

    per_day_manual = max(1, int(a.handler_minutes_per_day // a.manual_triage_min))
    per_day_copilot = max(1, int(a.handler_minutes_per_day // a.copilot_review_min))
    # Day on which the last urgent case is reached by one handler.
    def day_all_urgent(order, per_day):
        last = max((i for i, c in enumerate(order) if c in urgent), default=-1)
        return last // per_day + 1 if last >= 0 else 0

    return {
        "cases": len(items),
        "urgent": n_urgent,
        "arrival_order": arrival,
        "copilot_order": copilot,
        "mean_pos_arrival": mean_pos(arrival),
        "mean_pos_copilot": mean_pos(copilot),
        "top_k": n_urgent,
        "urgent_in_top_arrival": in_top(arrival, n_urgent),
        "urgent_in_top_copilot": in_top(copilot, n_urgent),
        "per_day_manual": per_day_manual,
        "per_day_copilot": per_day_copilot,
        "days_backlog_manual": -(-len(items) // per_day_manual),
        "days_backlog_copilot": -(-len(items) // per_day_copilot),
        "day_all_urgent_manual": day_all_urgent(arrival, per_day_manual),
        "day_all_urgent_copilot": day_all_urgent(copilot, per_day_copilot),
    }


def information_summary(metrics):
    n = len(metrics) or 1
    m0 = metrics[0] if metrics else {}
    return {
        "policy_docs": m0.get("policy_docs", 0),
        "clauses_total": m0.get("clauses_total", 0),
        "policy_words": m0.get("policy_words", 0),
        "avg_case_words": sum(m["case_words"] for m in metrics) / n,
        "avg_clauses_cited": sum(m["clauses_cited"] for m in metrics) / n,
        "avg_cited_words": sum(m["cited_words"] for m in metrics) / n,
        "avg_timeline_events": sum(m["timeline_events"] for m in metrics) / n,
        "citations_total": sum(m["citations_total"] for m in metrics),
        "citations_verified": sum(m["citations_verified"] for m in metrics),
    }


def handover_summary(metrics):
    spec = [m for m in metrics if m["needs_specialist"]]
    incomplete = [m for m in spec if m["would_be_returned"]]
    blocked = [m for m in incomplete if m["blocked_before_send"]]
    true_total = sum(len(m["true_gaps"]) for m in spec)
    caught = sum(len(m["gaps_caught"]) for m in spec)
    return {
        "specialist_cases": len(spec),
        "incomplete_as_written": len(incomplete),
        "blocked_before_send": len(blocked),
        "gaps_total": true_total,
        "gaps_caught": caught,
        "avg_fields_drafted": sum(m["fields_drafted"] for m in spec) / (len(spec) or 1),
        "missed": {m["case_id"]: m["gaps_missed"] for m in spec if m["gaps_missed"]},
    }


def time_summary(a: Assumptions, handover_share, return_share_before, return_share_after):
    """Minutes per complaint, before and after, and handler hours back each month."""
    before = a.manual_triage_min + handover_share * (a.manual_handover_min + return_share_before * a.return_rework_min)
    after = a.copilot_review_min + handover_share * (a.copilot_handover_min + return_share_after * a.return_rework_min)
    hours = a.complaints_per_month * (before - after) / 60
    return {"before_min": before, "after_min": after, "saved_min": before - after,
            "hours_per_month": hours, "fte": hours / (a.handler_minutes_per_day / 60 * 21)}
