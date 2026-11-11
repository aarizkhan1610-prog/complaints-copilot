"""Ask the case: a handler's question answered only from the redacted case file and the policies,
with every supporting quote checked in code. Saved answers make suggested questions work in demo mode."""
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import List, Literal

from pydantic import BaseModel, Field

from . import config
from .ai import AIUnavailable
from .checks import quote_found
from .data import load_policies
from .prompts import system_prompt

ASK_VERSION = "ask-v1.0"
ASK_DIR = config.DATA_DIR / "cached_answers"
SUGGESTED = [
    "What does the customer want, and has the bank promised anything so far?",
    "What happened, in date order, and what is still unknown?",
    "Which policy rules decide this case, and what do they require the handler to do?",
]


class Support(BaseModel):
    source: str = Field(description="'complaint', 'note_N', or a policy clause ID such as FEE-2")
    quote: str = Field(description="Exact words copied from that source")


class Answer(BaseModel):
    answer: str = Field(description="Plain-English answer, at most 120 words. Say clearly what is not in the file.")
    found_in_file: Literal["yes", "partly", "no"]
    supporting_quotes: List[Support]


ASK_INSTRUCTIONS = """

You are now answering one question from the complaints handler about this case. Answer only from the case \
text and the policy clauses. Back every factual statement with a supporting quote copied word for word, giving \
its source ('complaint', 'note_N' or the clause ID). If the file does not contain the answer, say so and set \
found_in_file to "no"; never guess. Do not decide the outcome or redress."""


def _hash(case_message, question):
    return hashlib.sha256((ASK_VERSION + case_message + question.strip().lower()).encode()).hexdigest()[:16]


def verify(answer, redacted_parts):
    pol = load_policies()
    out = []
    for s in answer.supporting_quotes:
        src = s.source.strip()
        if src.upper() in pol:
            c = pol[src.upper()]
            ok = quote_found(s.quote, c["title"] + ". " + c["text"])
        elif src in redacted_parts:
            ok = quote_found(s.quote, redacted_parts[src])
        else:
            ok = False
        out.append({"source": src, "quote": s.quote, "verified": ok})
    return out


def _saved_path(case_id):
    return ASK_DIR / f"{case_id}.json"


def load_saved(case_id):
    p = _saved_path(case_id)
    return json.loads(p.read_text()) if p.exists() else {}


def saved_answer(case_id, case_message, question):
    rec = load_saved(case_id).get(_hash(case_message, question))
    if not rec:
        return None
    return Answer.model_validate(rec["answer"]), dict(rec["meta"], provider="saved", saved_at=rec["saved_at"])


def save_answer(case_id, case_message, question, answer, meta):
    ASK_DIR.mkdir(parents=True, exist_ok=True)
    d = load_saved(case_id)
    d[_hash(case_message, question)] = {"question": question, "saved_at": datetime.now(timezone.utc).isoformat(
        timespec="seconds"), "meta": meta, "answer": answer.model_dump()}
    _saved_path(case_id).write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def ask_live(client, model, case_message, question, effort=config.EFFORT):
    """client: anthropic.Anthropic. Returns (Answer, meta)."""
    import anthropic as a
    t0 = time.time()
    try:
        resp = client.messages.parse(
            model=model, max_tokens=4000,
            system=[{"type": "text", "text": system_prompt() + ASK_INSTRUCTIONS, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": case_message + "\n\n<question>\n" + question.strip() + "\n</question>"}],
            output_format=Answer, output_config={"effort": effort},
        )
    except a.APIError as e:
        raise AIUnavailable(f"Live AI unavailable: {getattr(e, 'message', e)}") from e
    if resp.parsed_output is None:
        raise AIUnavailable("The model did not return an answer")
    return resp.parsed_output, {"provider": "live", "model": resp.model, "ask_version": ASK_VERSION,
                                "latency_s": round(time.time() - t0, 1)}
