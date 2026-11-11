"""One complaint through the whole flow: redact -> deadline -> AI -> checks -> handover pack."""
from . import audit, config
from .checks import completeness, gaps, injection_flags, verify_citations, verify_evidence
from .deadlines import deadline_info, priority_score
from .prompts import case_message, system_prompt
from .namecheck import suspect_names
from .redact import case_parts, redact_case


def prepare(case, extra_names=()):
    parts = case_parts(case)
    red = redact_case(parts, extra_names)
    dl = deadline_info(case["received"])
    message = case_message(case, red.text_by_part, dl)
    return parts, red, dl, message


def run_case(case, provider, want_live=False, session_left=None, log_audit=True, extra_names=()):
    parts, red, dl, message = prepare(case, extra_names)
    system = system_prompt()
    analysis, meta, fallback_reason = provider.analyse(case["id"], system, message,
                                                       want_live=want_live, session_left=session_left)
    cites = verify_citations(analysis)
    evidence = verify_evidence(analysis, red.text_by_part)
    inj = injection_flags(parts)
    rows = completeness(analysis, dl)
    result = {
        "case_id": case["id"], "deadline": dl, "redacted": red.text_by_part, "mapping": red.mapping,
        "message_sent": message, "analysis": analysis, "meta": meta, "fallback_reason": fallback_reason,
        "citations": cites, "evidence_checks": evidence, "injection_flags": inj,
        "completeness": rows, "gaps": gaps(rows), "name_flags": suspect_names(red.text_by_part),
        "priority": priority_score(dl["status"], analysis.severity, analysis.vulnerability.indicators_found),
        "warnings": warnings(analysis, cites, evidence, inj),
    }
    if log_audit:
        audit.log("ai_analysis", case["id"], provider=meta.get("provider"), model=meta.get("model"),
                  prompt_version=meta.get("prompt_version", config.PROMPT_VERSION),
                  input_hash=meta.get("input_hash"), redacted_input=message,
                  output=analysis.model_dump(), checks={"citations": cites, "gaps": result["gaps"],
                                                        "warnings": result["warnings"]})
    return result


def warnings(a, cites, evidence, inj):
    w = []
    if inj or a.suspicious_instructions:
        w.append("Possible prompt injection or attempt to dictate the outcome found in the case text. "
                 "The AI was told to ignore it; check the output carefully.")
    bad = [c for c in cites if c["status"] != "verified"]
    if bad:
        w.append(f"{len(bad)} policy citation(s) failed verification: " +
                 ", ".join(f"{c['clause_id']} ({c['status']})" for c in bad))
    badev = [e for e in evidence if e["status"] != "verified"]
    if badev:
        w.append(f"{len(badev)} evidence quote(s) could not be found in the case text.")
    low = [k for k, v in a.confidence.model_dump().items() if v == "low"]
    if low:
        w.append("Low confidence on: " + ", ".join(low.replace('_', ' ') for low in low))
    if not a.is_complaint:
        w.append("The AI thinks this may not be a complaint (CH-1). Confirm before closing.")
    return w


def handover_markdown(result, reviewer_note=""):
    a = result["analysis"]
    dl = result["deadline"]
    h = a.handover
    L = [f"## Specialist handover: case {result['case_id']}",
         f"**To:** {', '.join(a.specialist_teams) or 'No specialist (handler resolves)'}  ",
         f"**Deadline:** due {dl['due']} ({dl['status']}, {dl['days_left']} days left)  ",
         f"**Product / root cause / severity:** {a.product} / {a.root_cause} / {a.severity}", "",
         "### 1. Summary", h.complaint_summary, "",
         "### 3. Products and accounts", h.products_and_accounts, "",
         "### 4. Customer's desired outcome", h.desired_outcome, "",
         "### 5. Timeline"] + [f"- {t.date}: {t.event} _({t.source})_" for t in a.timeline] + [
         "", "### 6. Actions taken"] + [f"- {x}" for x in h.actions_taken] + [
         "", "### 7. Evidence held"] + [f"- {x}" for x in h.evidence_held] + [
         "", "### 8. Vulnerability assessment", h.vulnerability_assessment, "",
         "### 9. Contact preference", h.contact_preference, "",
         "### 10. Open questions"] + [f"- {x}" for x in h.open_questions] + [
         "", "### Policy clauses relied on (verified against policy text)"] + [
         f"- **{c.clause_id}**: \"{c.quote}\" ({c.how_it_applies})"
         for c, chk in zip(a.policy_citations, result["citations"]) if chk["status"] == "verified"]
    dropped = [chk["clause_id"] for chk in result["citations"] if chk["status"] != "verified"]
    if dropped:
        L.append(f"- _Removed {len(dropped)} citation(s) that failed verification: {', '.join(dropped)}_")
    if reviewer_note:
        L += ["", "### Reviewer note", reviewer_note]
    return "\n".join(L)
