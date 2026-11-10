# Complaints Copilot

A working prototype for **Scenario 1: Banking | Complaint handling** of the Ankura
*AI by Design* build task. A fictional bank, Harbourline Bank, has a growing complaints
backlog. Staff spend time hunting through case notes and policies, and specialist teams
receive incomplete handovers. This tool helps complaints handlers triage faster and hand
over complete, policy-checked cases. People stay in charge of every decision.

> **All data is synthetic.** Harbourline Bank, its policies, customers and cases are invented.
> See [`data/README.md`](data/README.md).

**Try it:** _hosted link will go here_ · or run it locally in two minutes (below).

---

## What it does

```
Complaint + case notes (synthetic)
   │
   1. Redaction ─────────── names, accounts, sort codes, cards, phones, emails, addresses,
   │                        dates of birth → [PERSON_1], [ACCOUNT_NUMBER_1]…  (originals never leave)
   2. Deadline + priority ─ 8-week deadline and status worked out in code (policy CH-4/CH-5)
   │
   3. AI analysis ───────── one structured call: summary, timeline, product, root cause, severity,
   │                        vulnerability, routing, cited policy clauses, draft ESC-3 handover
   4. Code checks ───────── every clause cited must exist and be quoted accurately; every evidence
   │                        quote must be in the case text; ten-field handover checklist;
   │                        prompt-injection detector
   5. Human review ──────── approve / change (reason required) / reject; fill missing fields;
   │                        incomplete handovers are blocked
   6. Specialist inbox ──── accept, or return as incomplete naming the missing fields
   │
   Audit log underneath everything: redacted input, model, prompt version, output, checks, decisions
```

**What the AI never does:** decide whether a complaint is upheld, set redress, contact the customer,
or see real personal data (policies CH-8 and RED-5 keep those with people).

Every phrase of the brief is mapped to a feature in [`BRIEF_TRACEABILITY.md`](BRIEF_TRACEABILITY.md).

## Run it locally

Requires Python 3.10+.

```bash
git clone <this repo> && cd complaints-copilot
pip install -r requirements.txt
streamlit run streamlit_app.py
```

It opens in **demo mode**: it replays real model responses that were saved earlier
(`data/cached_responses/`), so it is free to explore and needs no key.

**Live mode (optional, uses your own key):**

```bash
cp .env.example .env              # .env is git-ignored; put your key in it, or:
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run streamlit_app.py    # then switch on "Use live AI" in the sidebar
```

### A two-minute tour

1. **Complaint queue**: 25 cases sorted by deadline risk, severity and vulnerability. Select **C002** (a scam on a
   bereaved 78-year-old, due today) and open it.
2. **Review a case**: the left side shows the case as the AI saw it (redacted); toggle *Show personal data* to
   re-identify on screen only. The right side shows the AI's draft with confidence levels, verified evidence quotes
   and verified policy citations. The ESC-3 checklist shows what is missing; fill it in and submit.
3. **Specialist inbox**: accept the handover, or return it as incomplete.
4. **Audit log**: every AI call and every human decision.
5. Also try **C009** (a prompt-injection attempt), **C010** (not a complaint) and **C024** (an almost empty chaser).

## Hosting (Streamlit Community Cloud)

1. Push this repo to GitHub and create an app at share.streamlit.io pointing at `streamlit_app.py`.
2. In the app's **Settings → Secrets**, add `ANTHROPIC_API_KEY = "sk-ant-..."`. The key lives only on the server.
   It is never in the repo or sent to the browser.
3. Spend is capped in three layers: prepaid credit with auto-reload off (hard cap), a daily cap of 50 live runs
   (`COPILOT_DAILY_LIVE_CAP`) and 10 per visitor session (`COPILOT_SESSION_LIVE_CAP`). After a cap is reached, or
   if the API fails, the app falls back to saved responses and says so.

## Testing and evaluation

```bash
pip install -r requirements-dev.txt
pytest -q                        # unit tests: deadlines, redaction, quote checks, injection, pipeline
python eval/run_eval.py          # scores saved responses against the answer key → eval/results.md
python scripts/build_cache.py    # (costs money) re-runs the model over all cases and saves responses
```

The evaluation measures redaction on the development set **and on a held-out set written afterwards**, triage
accuracy, vulnerability recall, routing, citation verification, evidence verification, handover gap detection, and
prompt-injection resistance. Results: [`eval/results.md`](eval/results.md).

## Project layout

| Path | What |
|---|---|
| `streamlit_app.py` | The user interface (queue, review, specialist inbox, audit log) |
| `copilot/redact.py` | Personal-data redaction (rules + name propagation) |
| `copilot/deadlines.py` | Deadline status and priority score (pure code) |
| `copilot/prompts.py`, `copilot/schemas.py` | The prompt and the exact output format the model must follow |
| `copilot/ai.py` | Model providers: live Claude, saved responses, and the hybrid with caps and fallback |
| `copilot/checks.py` | Citation, evidence, completeness and injection checks |
| `copilot/pipeline.py` | One case end to end; handover pack |
| `copilot/audit.py` | Append-only audit log |
| `data/` | Synthetic complaints, fictional policies, answer key, saved responses |
| `eval/` | Evaluation script, held-out redaction set, results |
| `docs/assumptions.md` | Scope, assumptions and limitations |

## AI tools used

- **Optional local model:** a sidebar switch and `python scripts/build_cache.py --local` run the same pipeline on a model served by [Ollama](https://ollama.com) on your own machine (default `qwen2.5:7b`). Not used for the submitted results.
- **In the product:** Anthropic's Claude API (default `claude-sonnet-5-5` at low effort, chosen over Opus 5.5 and Haiku 5.5 in [`eval/model_comparison.md`](eval/model_comparison.md)) with structured outputs, so
  every response must match the schema in `copilot/schemas.py`. The provider is isolated in `copilot/ai.py`;
  a bank could swap in Claude through its own cloud (Amazon Bedrock, Google Vertex AI), Snowflake Cortex, or a
  locally hosted open-source model without touching the rest of the code.
- **To build it:** Claude (via Claude Code) helped draft the synthetic data, code and tests. All outputs were
  reviewed and tested. See the deck for an assessment of where it helped and where it needed correcting.

## Limitations

See [`docs/assumptions.md`](docs/assumptions.md). In short: 25 synthetic cases are a demonstration, not proof;
rule-based redaction misses names that appear without context (measured on the held-out set), so production would
need a trained recogniser plus monitoring; the policies are simplified; and the audit log is a file, not write-once
storage.
