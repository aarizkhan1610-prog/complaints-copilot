"""Save answers to the fixed Ask the case questions for every case, so it works without live AI.

Usage: python scripts/build_answers.py [CASE_ID ...]   (needs an API key; uses the saved-response model)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import anthropic  # noqa: E402

from copilot import config  # noqa: E402
from copilot.ask import SUGGESTED, ask_live, save_answer, saved_answer  # noqa: E402
from copilot.data import get_complaint  # noqa: E402
from copilot.pipeline import prepare  # noqa: E402

from copilot.data import load_complaints  # noqa: E402


def main(ids):
    client = anthropic.Anthropic(api_key=config.get_api_key(), max_retries=2, timeout=120)
    for cid in ids:
        _, _, _, message = prepare(get_complaint(cid))
        for q in SUGGESTED:
            if saved_answer(cid, message, q):
                continue
            ans, meta = ask_live(client, config.SAVED_MODEL, message, q)
            save_answer(cid, message, q, ans, meta)
            print(cid, "|", q[:40], "|", ans.found_in_file, len(ans.supporting_quotes), "quotes", meta["latency_s"], "s")


if __name__ == "__main__":
    main(sys.argv[1:] or [c["id"] for c in load_complaints()])
