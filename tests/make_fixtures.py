"""Hand-written TEST FIXTURES (not model output) used to test the checks and the UI offline.

They deliberately include one invented clause and one misquote so the verification
code can be tested. Real saved model responses live in data/cached_responses/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot.ai import SavedResponses, input_hash  # noqa: E402
from copilot.data import get_complaint  # noqa: E402
from copilot.pipeline import prepare  # noqa: E402
from copilot.prompts import system_prompt  # noqa: E402
from copilot.schemas import CaseAnalysis  # noqa: E402

FIX = Path(__file__).parent / "fixtures"

C002 = {
    "is_complaint": True, "is_complaint_reason": "Customer reports losing £4,250 to a scam and wants it back.",
    "summary": "[PERSON_4] was tricked by a fake HMRC text and a caller posing as bank security into moving £4,250 "
               "to a 'safe account' in the name of [PERSON_2] on 12/09. She is 78, recently bereaved and finds online "
               "banking hard. No fraud team referral was made and she has chased twice.",
    "timeline": [
        {"date": "12/09", "event": "Customer transfers £4,250 to [PERSON_2] after scam call", "source": "complaint"},
        {"date": "2026-09-14", "event": "Card blocked, credentials reset, customer told fraud team will call", "source": "note_1"},
        {"date": "2026-09-30", "event": "Customer chases; no referral found; asks for large print", "source": "note_2"},
        {"date": "2026-10-21", "event": "Chased internally; still no fraud owner", "source": "note_3"},
    ],
    "product": "Current account", "root_cause": "Authorised push payment scam", "severity": "High",
    "severity_reason": "Scam with loss over £1,000 and a vulnerable customer (CH-6).",
    "estimated_financial_loss_gbp": 4250.0,
    "vulnerability": {"indicators_found": True, "drivers": ["life events", "capability"], "customer_was_asked": False,
                      "suggested_support": "Large print letters, named contact, refer to Vulnerable Customer Support."},
    "specialist_teams": ["Fraud & Scams", "Vulnerable Customer Support"],
    "routing_reason": "APP scam must go to Fraud & Scams (FRD-2); bereavement and low capability trigger VUL-4.",
    "policy_citations": [
        {"clause_id": "FRD-2", "quote": "the case must be handed to the Fraud & Scams team within 1 business day",
         "how_it_applies": "Referral is overdue by several weeks."},
        {"clause_id": "VUL-4", "quote": "must be referred to the Vulnerable Customer Support team",
         "how_it_applies": "Bereavement plus low digital capability."},
        {"clause_id": "FRD-9", "quote": "scam victims over 75 are always refunded",
         "how_it_applies": "FIXTURE: deliberately invented clause to test verification."},
        {"clause_id": "CH-4", "quote": "must receive a Final Response within 4 weeks",
         "how_it_applies": "FIXTURE: deliberately misquoted to test verification."},
    ],
    "evidence": [
        {"field": "root_cause", "quote": "They told her to move her savings to a 'safe account'", "source": "complaint"},
        {"field": "vulnerability", "quote": "since my husband died last year I don't really understand all this online banking", "source": "complaint"},
    ],
    "handover": {
        "complaint_summary": "Customer lost £4,250 to a bank impersonation scam on 12/09 and wants reimbursement.",
        "products_and_accounts": "Current account (reference in system)",
        "desired_outcome": "Reimbursement of £4,250",
        "actions_taken": ["Card blocked", "Online banking credentials reset"],
        "evidence_held": ["Payment record FPS 12/09"],
        "vulnerability_assessment": "Indicators: bereavement, low digital capability, age 78. Customer not asked about support needs.",
        "contact_preference": "Letters in large print",
        "third_party_authority": "Not applicable",
        "open_questions": ["Did the customer share any security details?", "Has the receiving bank been contacted?"],
    },
    "fraud_details": {"payment_details": "£4,250 Faster Payment on 12/09 at 14:32", "payee_details": "Account in the name of [PERSON_2]",
                      "fraudster_contact_method": "Text claiming to be HMRC, then phone call posing as bank security",
                      "security_details_shared": "MISSING", "account_secured": "Card blocked and credentials reset on 2026-09-14"},
    "other_gaps": ["Receiving bank details not recorded"],
    "suggested_next_step": "Hand to Fraud & Scams today and refer to Vulnerable Customer Support.",
    "confidence": {"product": "high", "root_cause": "high", "severity": "high", "vulnerability": "high", "specialist_teams": "high"},
    "suspicious_instructions": None,
}


def main():
    s = SavedResponses(FIX)
    for cid, data in [("C002", C002)]:
        case = get_complaint(cid)
        _, _, _, msg = prepare(case)
        a = CaseAnalysis.model_validate(data)
        s.save(cid, a, {"provider": "fixture", "model": "hand-written-fixture", "prompt_version": "fixture",
                        "input_hash": input_hash(system_prompt(), msg)})
    print("fixtures written")


if __name__ == "__main__":
    main()
