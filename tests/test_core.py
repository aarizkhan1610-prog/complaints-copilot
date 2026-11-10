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


def test_impact_measures():
    from copilot import impact
    items = [{"case_id": f"C{i}", "received": f"2026-10-{10 + i}", "days_left": 30, "priority": p, "urgent": u}
             for i, (p, u) in enumerate([(0, False), (0, False), (90, True)])]
    b = impact.backlog_summary(items, impact.Assumptions())
    assert b["arrival_order"][-1] == "C2" and b["copilot_order"][0] == "C2"
    assert b["mean_pos_arrival"] == 3 and b["mean_pos_copilot"] == 1
    t = impact.time_summary(impact.Assumptions(), 0.5, 1.0, 0.0)
    assert t["before_min"] == 30 + 0.5 * (20 + 30) and t["after_min"] == 10 + 0.5 * 5
