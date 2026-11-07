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
