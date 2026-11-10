"""Code checks on every AI output. The model's answer is never trusted on its own."""
import re

from .data import load_policies

INJECTION_RE = re.compile(
    r"(?i)(ignore (all |any )?(previous|prior|above) instructions|system (note|prompt|message)|"
    r"note to (the )?ai|as an ai|you are now|do not mention this|disregard (the|your) (rules|instructions))")


def _norm(s):
    return re.sub(r"[^a-z0-9£%\[\]_ ]+", " ", s.lower()).split()


def quote_found(quote, source):
    """True if the quote appears in the source (ignoring punctuation and case), or almost all of it does."""
    q, src = _norm(quote), _norm(source)
    if not q:
        return False
    qs, ss = " ".join(q), " ".join(src)
    if qs in ss:
        return True
    # Allow small differences (an ellipsis, a dropped word): 90% of the quote's words in order-insensitive overlap
    # within a window of the source.
    words = set(src)
    # Any number in the quote (amounts, days, percentages) must appear exactly in the source.
    if any(re.search(r"\d", w) and w not in words for w in q):
        return False
    return len(q) >= 6 and sum(w in words for w in q) / len(q) >= 0.9


def verify_citations(analysis):
    policies = load_policies()
    out = []
    for c in analysis.policy_citations:
        clause = policies.get(c.clause_id.strip().upper())
        if clause is None:
            out.append({"clause_id": c.clause_id, "status": "invented", "detail": "No such clause exists in the policy set"})
        elif not quote_found(c.quote, clause["title"] + ". " + clause["text"]):
            out.append({"clause_id": c.clause_id, "status": "misquoted", "detail": "Quoted words not found in that clause"})
        else:
            out.append({"clause_id": c.clause_id, "status": "verified", "detail": clause["title"]})
    return out


def verify_evidence(analysis, redacted_parts):
    out = []
    for e in analysis.evidence:
        src = redacted_parts.get(e.source.strip())
        if src is None:
            ok = any(quote_found(e.quote, t) for t in redacted_parts.values())
        else:
            ok = quote_found(e.quote, src)
        out.append({"field": e.field, "quote": e.quote, "source": e.source,
                    "status": "verified" if ok else "not found in case text"})
    for t in analysis.timeline:
        if t.source.strip() not in redacted_parts:
            out.append({"field": "timeline", "quote": t.event, "source": t.source,
                        "status": "unknown source"})
    return out


def injection_flags(raw_parts):
    hits = []
    for part, text in raw_parts.items():
        for m in INJECTION_RE.finditer(text):
            hits.append({"part": part, "match": m.group(0)})
    return hits


MISSING_RE = re.compile(r"(?i)^\s*(missing|not (recorded|stated|known|provided|on file)|unknown|none recorded|n/?a)\b")


def _missing(v):
    if v is None:
        return True
    if isinstance(v, list):
        return len([x for x in v if not _missing(x)]) == 0
    return not str(v).strip() or bool(MISSING_RE.match(str(v))) or "MISSING" in str(v)


def completeness(analysis, deadline):
    """ESC-3 (plus FRD-3/4 and VUL-6 where relevant). Returns a list of checklist rows."""
    h = analysis.handover
    v = analysis.vulnerability
    vuln_ok = v.customer_was_asked and not _missing(h.vulnerability_assessment)
    rows = [
        ("summary", "ESC-3.1 Complaint summary", not _missing(h.complaint_summary), h.complaint_summary),
        ("deadline", "ESC-3.2 Date received and deadline status", True,
         f"Received {deadline['received']}; due {deadline['due']} ({deadline['status']}, {deadline['days_left']} days)"),
        ("products_accounts", "ESC-3.3 Products and accounts affected", not _missing(h.products_and_accounts), h.products_and_accounts),
        ("desired_outcome", "ESC-3.4 Customer's desired outcome", not _missing(h.desired_outcome), h.desired_outcome),
        ("timeline", "ESC-3.5 Timeline of events", any(t.date.lower() != "undated" for t in analysis.timeline),
         f"{len(analysis.timeline)} events"),
        ("actions_taken", "ESC-3.6 Actions taken so far", not _missing(h.actions_taken), h.actions_taken),
        ("evidence_held", "ESC-3.7 Evidence held", not _missing(h.evidence_held), h.evidence_held),
        ("vulnerability_assessment", "ESC-3.8 Vulnerability assessment (and whether the customer was asked)",
         vuln_ok, h.vulnerability_assessment + ("" if v.customer_was_asked else " [customer not asked]")),
        ("contact_preference", "ESC-3.9 Contact preference and adjustments", not _missing(h.contact_preference), h.contact_preference),
        ("open_questions", "ESC-3.10 Open questions for the specialist", not _missing(h.open_questions), h.open_questions),
    ]
    tpa = (h.third_party_authority or "").strip()
    if tpa and not tpa.lower().startswith("not applicable"):
        ok = not _missing(tpa) and not re.search(r"(?i)\b(no|not)\b.*\b(authority|mandate|on file)|^no\b", tpa)
        rows.append(("third_party_authority", "VUL-6 Third-party authority on file", ok, tpa))
    if "Fraud & Scams" in analysis.specialist_teams and analysis.fraud_details:
        f = analysis.fraud_details
        rows += [
            ("frd_payment_details", "FRD-3 Date, time and amount of each payment", not _missing(f.payment_details), f.payment_details),
            ("frd_payee_details", "FRD-3 Payee details", not _missing(f.payee_details), f.payee_details),
            ("frd_contact_method", "FRD-3 How the fraudster made contact", not _missing(f.fraudster_contact_method), f.fraudster_contact_method),
            ("frd_security_details", "FRD-3 Whether security details were shared", not _missing(f.security_details_shared), f.security_details_shared),
            ("account_secured", "FRD-4 Account secured and recorded", not _missing(f.account_secured), f.account_secured),
        ]
    return [{"key": k, "label": lab, "ok": bool(ok), "value": val} for k, lab, ok, val in rows]


def gaps(rows):
    return [r["key"] for r in rows if not r["ok"]]
