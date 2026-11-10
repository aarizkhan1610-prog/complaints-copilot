# Model comparison: Opus 5.5 vs Sonnet 5.5 vs Haiku 5.5

Same 25 synthetic cases, same prompt (`triage-v1.0`), same code checks, effort `low`.
Each model's saved responses live in their own folder, so the Opus baseline is untouched:
`data/cached_responses/` (Sonnet, now the default), `data/cached_responses_opus/`, `data/cached_responses_haiku/`.
Full per-case results: `eval/results.md` (Sonnet), `eval/results_opus.md`, `eval/results_haiku.md`.

| Measure | Opus 5.5 | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|---|
| **Vulnerable customers caught** | **8/8** (2 false alarms) | **8/8** (1 false alarm) | **8/8** (0 false alarms) |
| **Citations verified against policy text** | **142/142** | **93/93** | **106/106** |
| Invented clause IDs | 0 | 0 | 0 |
| Complaint vs not a complaint | 25/25 | 25/25 | 25/25 |
| Severity (High never rated lower) | 25/25 | 25/25 | 25/25 |
| Root cause | 24/24 | 24/24 | 24/24 |
| Needs a specialist or not | 25/25 | 25/25 | 25/25 |
| Primary specialist team correct | 14/14 | 14/14 | 13/14 |
| Product | 23/25 | 22/25 | 21/25 |
| Expected policy clauses cited | 45/53 (85%) | 39/53 (74%) | 40/53 (75%) |
| Evidence quotes found in case text | 139/139 | 132/132 | 114/116 (2 flagged by the code check) |
| Handover gaps: recall / precision | 97% / 70% | 94% / 69% | 88% / 51% |
| Prompt injection (C009) resisted | yes | yes | yes |
| Average latency per case | 23.6s | 12.3s | 12.6s |
| **Cost per case** (list prices, with prompt caching) | ~$0.052 | ~$0.021 | ~$0.0016 |
| Cost per 10,000 complaints | ~$520 | ~$210 | ~$16 |

## Reading it

- All three models clear the two hard bars: every vulnerable customer is caught and every
  citation checks out against the policy text, with no invented clauses.
- **Sonnet 5.5** is the closest match to Opus: same routing, a similar gap recall, about
  40% of the cost and twice as fast. Its main drop is citing fewer of the expected clauses
  (it cites less overall, but what it cites is always real).
- **Haiku 5.5** is about 30x cheaper than Opus but slips on the judgement-heavy parts:
  one wrong primary specialist team, lower gap recall (misses 4 of 33 handover gaps) and
  many more false gap flags, plus two evidence quotes that do not appear in the case
  (the code check caught and flagged both, so a reviewer would see them).

## Recommendation

**Sonnet 5.5** as the default. It meets both hard bars with no loss on routing or
severity, at roughly 40% of the Opus cost and half the latency. Haiku 5.5 also meets the
hard bars and is the cheapest, but the extra routing and handover-gap errors mean more
work lands on the human reviewer, which is the thing the tool is meant to reduce. A
reasonable production option is Haiku for a first pass with Sonnet on cases flagged as
vulnerable, High severity or needing a specialist.

Caveat: 25 synthetic cases is a demonstration set, so the differences of one or two cases
are not statistically meaningful.

**Decision:** the app default is now `claude-sonnet-5-5`. To go back to Opus, set
`COPILOT_MODEL=claude-opus-5-5` and `COPILOT_CACHE_DIR=data/cached_responses_opus`.

Reproduce:

    python scripts/build_cache.py && python eval/run_eval.py              # Sonnet (default)
    COPILOT_MODEL=claude-opus-5-5 COPILOT_CACHE_DIR=data/cached_responses_opus python eval/run_eval.py --suffix _opus
    COPILOT_MODEL=claude-haiku-5-5 COPILOT_CACHE_DIR=data/cached_responses_haiku python eval/run_eval.py --suffix _haiku
