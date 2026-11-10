"""Deadline and priority rules. Pure code, no AI: dates must be exact (policy CH-4, CH-5)."""
from datetime import date, timedelta

from .config import AS_OF

FINAL_RESPONSE_DAYS = 56  # CH-4: 8 weeks


def deadline_info(received: str, as_of: date = AS_OF):
    rec = date.fromisoformat(received)
    due = rec + timedelta(days=FINAL_RESPONSE_DAYS)
    left = (due - as_of).days
    if left < 0:
        status = "Breached"
    elif left <= 7:
        status = "Critical"
    elif left <= 21:
        status = "At risk"
    else:
        status = "On track"
    return {"received": received, "due": due.isoformat(), "days_left": left, "status": status}


STATUS_WEIGHT = {"Breached": 40, "Critical": 30, "At risk": 15, "On track": 0}
SEVERITY_WEIGHT = {"High": 30, "Medium": 15, "Low": 0}


def priority_score(deadline_status, severity=None, vulnerable=False):
    """Higher = work it sooner. Transparent and explainable on purpose."""
    score = STATUS_WEIGHT[deadline_status]
    if severity:
        score += SEVERITY_WEIGHT.get(severity, 0)
    if vulnerable:
        score += 25
    return score
