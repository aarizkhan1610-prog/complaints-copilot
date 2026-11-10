"""Run the real model over the sample cases and save the responses for demo mode.

    ANTHROPIC_API_KEY=... python scripts/build_cache.py            # all cases missing a fresh response
    python scripts/build_cache.py --local                          # use a local Ollama model instead (free)
    ANTHROPIC_API_KEY=... python scripts/build_cache.py C002 C009  # just these
    ... --force                                                     # re-run even if a fresh one exists

Costs money (roughly 5-8p per case on the default model). Saved files hold only the
redacted input hash, model metadata and the model's output, never personal data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from copilot import config  # noqa: E402
from copilot.ai import AIUnavailable, LiveClaude, LocalOllama, SavedResponses  # noqa: E402
from copilot.data import load_complaints  # noqa: E402
from copilot.pipeline import prepare  # noqa: E402
from copilot.prompts import system_prompt  # noqa: E402


def main(args):
    force = "--force" in args
    only = {a for a in args if not a.startswith("--")}
    if "--local" in args:
        live = LocalOllama()
        if not live.available():
            sys.exit(f"Ollama is not running or model '{config.OLLAMA_MODEL}' is not pulled. "
                     f"Install from https://ollama.com, then: ollama pull {config.OLLAMA_MODEL}")
        saved = SavedResponses(config.LOCAL_CACHE_DIR)
    else:
        key = config.get_api_key()
        if not key:
            sys.exit("Set ANTHROPIC_API_KEY (or COPILOT_ANTHROPIC_KEY) first (never commit it), or use --local for a local model.")
        live, saved = LiveClaude(key), SavedResponses()
    system = system_prompt()
    total_in = total_out = 0
    for case in load_complaints():
        if only and case["id"] not in only:
            continue
        _, _, _, msg = prepare(case)
        if saved.has(case["id"], system, msg) and not force:
            print(f"{case['id']}: up to date")
            continue
        try:
            analysis, meta = live.analyse(case["id"], system, msg)
        except AIUnavailable as e:
            print(f"{case['id']}: FAILED - {e}")
            continue
        saved.save(case["id"], analysis, meta)
        u = meta["usage"]
        total_in += u["input"] + u["cache_read"] + u["cache_write"]
        total_out += u["output"]
        print(f"{case['id']}: saved ({u['input']}+{u['cache_read']} cached in, {u['output']} out, {meta['latency_s']}s)")
    print(f"Total tokens: {total_in:,} in, {total_out:,} out")


if __name__ == "__main__":
    main(sys.argv[1:])
