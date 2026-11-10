"""Append-only audit log (JSON lines). Records what went in, what the AI said and what people decided."""
import json
from datetime import datetime, timezone

from .config import AUDIT_LOG


def log(event, case_id, **fields):
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, "case_id": case_id, **fields}
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass
    return rec


def read(case_id=None):
    try:
        lines = AUDIT_LOG.read_text().splitlines()
    except OSError:
        return []
    recs = [json.loads(x) for x in lines if x.strip()]
    return [r for r in recs if case_id is None or r["case_id"] == case_id]
