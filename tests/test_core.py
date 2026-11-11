import json
from pathlib import Path

import pytest

from copilot.ai import Hybrid, SavedResponses
from copilot.checks import injection_flags, quote_found
from copilot.data import get_complaint, load_complaints, load_labels, load_policies
from copilot.deadlines import deadline_info
from copilot.pipeline import prepare, run_case
from copilot.redact import case_parts, redact_case

FIX = Path(__file__).parent / "fixtures"


def test_all_policy_clauses_parsed():
    p = load_policies()
    assert len(p) == 41
    assert "ESC-3" in p and "ten fields" in p["ESC-3"]["text"]


@pytest.mark.parametrize("received,status", [("2026-09-10", "Breached"), ("2026-09-14", "Critical"),
                                             ("2026-09-29", "At risk"), ("2026-11-06", "On track")])
def test_deadline_status(received, status):
    assert deadline_info(received)["status"] == status


def test_redaction_removes_every_labelled_item_on_dev_set():
    labels = load_labels()
    for c in load_complaints():
        text = "\n".join(redact_case(case_parts(c)).text_by_part.values()).lower()
        for p in labels[c["id"]]["pii"]:
            assert p["value"].lower() not in text, (c["id"], p)


def test_redaction_is_deterministic():
    msgs = [prepare(get_complaint("C022"))[3] for _ in range(3)]
    assert len(set(msgs)) == 1


def test_no_personal_data_in_model_message():
    labels = load_labels()
    for c in load_complaints():
        msg = prepare(c)[3].lower()
        for p in labels[c["id"]]["pii"]:
            assert p["value"].lower() not in msg


def test_quote_check_rejects_changed_numbers():
    src = "All other complaints must receive a Final Response within 8 weeks (56 calendar days) of receipt."
    assert quote_found("must receive a Final Response within 8 weeks", src)
    assert not quote_found("must receive a Final Response within 4 weeks of receipt", src)


def test_injection_detector_flags_c009_only():
    flagged = [c["id"] for c in load_complaints() if injection_flags(case_parts(c))]
    assert flagged == ["C009"]


def test_fixture_pipeline_catches_invented_and_misquoted_clauses(tmp_path, monkeypatch):
    monkeypatch.setattr("copilot.config.AUDIT_LOG", tmp_path / "a.jsonl")
    r = run_case(get_complaint("C002"), Hybrid(saved=SavedResponses(FIX)), log_audit=False)
    status = {c["clause_id"]: c["status"] for c in r["citations"]}
    assert status["FRD-9"] == "invented" and status["CH-4"] == "misquoted" and status["FRD-2"] == "verified"
    assert set(r["gaps"]) == set(load_labels()["C002"]["handover_gaps"])
    assert r["deadline"]["status"] == "Critical"


def test_saved_responses_contain_no_personal_data():
    labels = load_labels()
    for f in Path("data/cached_responses").glob("*.json"):
        text = f.read_text().lower()
        for p in labels[f.stem]["pii"]:
            if len(p["value"]) > 3:
                assert p["value"].lower() not in text, (f.stem, p)


def test_find_span_and_highlight():
    from copilot.sources import find_span, highlight_html, policy_document
    t = "Card blocked. Payment £4,250 FPS 12/09 14:32. Told cust fraud team will be in touch."
    a, b = find_span(t, "payment £4,250 FPS 12/09")
    assert t[a:b] == "Payment £4,250 FPS 12/09"
    assert "<mark>" in highlight_html(t, "fraud team will be in touch") and find_span(t, "nothing like this") is None
    assert "Cited clause" in policy_document("FEE-2")


def test_related_cases_shared_incident():
    from types import SimpleNamespace as NS
    from copilot.related import related_cases
    mk = lambda cid, text, rc="Fees and charges", prod="Current account": (
        {"id": cid, "received": "2026-10-01", "complaint": text, "case_notes": []},
        NS(is_complaint=True, root_cause=rc, product=prod, summary="s"))
    rows = [mk("A", "late salary INC-1"), mk("B", "fee INC-1", rc="Service delay", prod="Savings account"),
            mk("C", "unrelated", rc="Staff conduct", prod="Mortgage")]
    cases, an = {c["id"]: c for c, _ in rows}, {c["id"]: a for c, a in rows}
    m, note = related_cases("A", cases, an)
    assert [x["case_id"] for x in m] == ["B"] and "same incident" in note


def test_ask_verify_rejects_invented_quote():
    from copilot.ask import Answer, verify
    ans = Answer(answer="x", found_in_file="yes", supporting_quotes=[
        {"source": "note_1", "quote": "Told cust fraud team will be in touch"},
        {"source": "note_1", "quote": "refund of £5,000 was promised"},
        {"source": "FRD-5", "quote": "Handlers must not promise a refund or reimbursement"}])
    v = verify(ans, {"note_1": "Card blocked. Told cust fraud team will be in touch."})
    assert [x["verified"] for x in v] == [True, False, True]
