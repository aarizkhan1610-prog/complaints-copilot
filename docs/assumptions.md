# Assumptions, scope and limitations

This file is the running record of every assumption made while building the
prototype, in line with the brief: "Choose the scope and make any assumptions explicit."

## Scope
- **In scope:** the stages between a complaint arriving and a specialist (or the
  handler) starting the investigation: intake, redaction, summary, triage, policy
  lookup, handover pack, human review, specialist acceptance or return.
- **Out of scope:** deciding whether a complaint is upheld, setting redress amounts,
  writing final response letters, and any contact with the customer. These stay
  with people (policies CH-8 and RED-5).

## Data
- Harbourline Bank, its policies, customers and cases are entirely fictional.
- 25 complaints is a demonstration set, not a statistically meaningful sample.
  Results from it show how the evaluation works, not how a production system would perform.
- Policies are simplified. They borrow the general shape of UK complaint handling
  (an 8-week final response deadline, an independent ombudsman, vulnerability
  drivers) but are not a statement of any regulator's rules.
- The answer key in `data/labels.json` was written by one person. Where a case is
  genuinely ambiguous, alternative answers are accepted (`root_cause_alt`, `severity_alt`).

## Dates
- The app uses a fixed "today" of **Monday 9 November 2026** so deadline statuses
  are reproducible for assessors. In production this would be the real date.

## Technology choices and trade-offs
- **One structured AI call per case** rather than several: lower cost and latency, and the output is checked
  field by field in code afterwards. The trade-off is that one prompt does several jobs.
- **Whole policy set sent with each call** (41 clauses, about 3,000 words) instead of a search index. At this size
  it is simpler and more accurate, and prompt caching makes the repeated part cheap. A real bank's policy library
  would need retrieval.
- **Rule-based redaction** instead of a trained recogniser (spaCy / Presidio were considered; spaCy would not
  install cleanly on the build machine's Python version, and rules keep hosting simple). It is strong on structured
  identifiers and weaker on names with no context: see the held-out results in `eval/results.md`.
- **Default model** `claude-sonnet-5-5` at low effort. Opus 5.5, Sonnet 5.5 and Haiku 5.5 were run on the same
  25 cases (`eval/model_comparison.md`). All three caught every vulnerable customer with fully verified citations;
  Sonnet matched Opus on routing at about 40% of the cost and half the latency, while Haiku made more routing and
  handover-gap errors.
- **Saved responses for demo mode** are real model outputs. They are tied to a hash of the exact prompt and input,
  so an edited case or prompt cannot silently reuse an old answer.

## Limitations
- Redaction recall on new text is lower than on the development set; residual names could reach the model. In
  production: a trained recogniser, a second-pass check, and a contractual zero-retention arrangement with the
  model provider.
- The completeness check depends partly on the AI writing MISSING correctly; the human reviewer is the backstop.
- Audit records are a local file. Production needs write-once storage, access control and retention rules.
- Session state (reviews, handovers) is per browser session in the demo; a real deployment needs a case system.
