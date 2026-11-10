"""Load the synthetic complaints and the fictional policy clauses."""
import json
import re
from functools import lru_cache

from .config import DATA_DIR, POLICY_DIR

CLAUSE_RE = re.compile(r"^\*\*([A-Z]{2,3}-\d+) ([^*]+?)\.\*\*\s*(.*?)(?=^\*\*[A-Z]{2,3}-\d+ |\Z)", re.M | re.S)


@lru_cache
def load_complaints():
    return json.loads((DATA_DIR / "complaints.json").read_text())


def get_complaint(cid):
    return next(c for c in load_complaints() if c["id"] == cid)


@lru_cache
def load_labels():
    return json.loads((DATA_DIR / "labels.json").read_text())


@lru_cache
def load_policies():
    """Return {clause_id: {"id", "title", "text", "policy"}} for every clause."""
    clauses = {}
    for f in sorted(POLICY_DIR.glob("*.md")):
        raw = f.read_text()
        policy_title = raw.splitlines()[0].lstrip("# ").strip()
        for m in CLAUSE_RE.finditer(raw):
            cid, title, body = m.group(1), m.group(2).strip(), m.group(3).strip()
            clauses[cid] = {"id": cid, "title": title, "text": body, "policy": policy_title}
    return clauses


@lru_cache
def policy_corpus_text():
    """All policy clauses as one block of text for the model (small enough to send whole)."""
    lines = []
    current = None
    for c in load_policies().values():
        if c["policy"] != current:
            current = c["policy"]
            lines.append(f"\n## {current}")
        lines.append(f"[{c['id']}] {c['title']}. {c['text']}")
    return "\n".join(lines).strip()
