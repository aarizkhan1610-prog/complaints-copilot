# Brief traceability

Every requirement below is quoted from the Ankura interview exercise email
(Scenario 1: Banking | Complaint handling). Each line points to the part of the
prototype or the slide deck that answers it. Status is updated as the build progresses.

## Scenario 1 wording

| Brief wording | Where it is answered | Status |
|---|---|---|
| "a growing backlog of customer complaints" | Priority queue ordered by deadline risk and vulnerability, with a before/after toggle (arrival order); Impact page section 1 | Built |
| "Staff spend time finding information across case notes and policy documents" | AI case summary + timeline (each event linked to its source note); policy search with cited clause IDs; Impact page section 2 and per-case panel | Built |
| "specialist teams receive incomplete handovers" | Handover pack built against the required fields in policy `ESC-3`; completeness check blocks handover until gaps are filled; specialist can return a pack as incomplete; Impact page section 3 | Built |
| "decide where AI could improve the service" | Opportunity map across the complaint journey (deck, slide 1) | Planned |
| "protect customer information" | Redaction runs before any AI call; only synthetic data; key held server-side; data residency options on controls slide | Data ready (PII ground truth) |
| "keep decisions reviewable" | Human approve / edit / reject on every AI output; audit log of input (redacted), prompt version, model, output and reviewer decision | Planned |
| "consider how complaints staff and specialists would use the solution" | Two views: complaint handler and specialist; workflow before/after on slide 5 | Planned |
| "Explain the expected value" | Value estimate with explicit assumptions (deck, slide 1) | Planned |
| "the controls and human review" | Controls slide; prompt-injection, made-up citation and over-flagging tests | Data ready (adversarial cases) |
| "the changes to staff roles or handoffs" | Workforce slide: task shift, new reviewer skills, training | Planned |
| "Choose the scope and make any assumptions explicit" | `docs/assumptions.md`; scope statement on slide 1 | Started |

## "Your submission should consider"

| Brief wording | Where it is answered | Status |
|---|---|---|
| "The potential business value" | Slide 1 value estimate | Planned |
| "Relevant risks, controls and human oversight" | Slide 4; controls built into the app | Planned |
| "How people's roles or workflows may change" | Slide 5 | Planned |
| "Any assumptions, limitations or trade-offs" | `docs/assumptions.md`; slide 3 limitations; deployment options trade-off | Started |
| "The AI tools used and your assessment of them" | Slide 2: Claude API models used in the app, and AI tools used to build it, with an honest assessment | Planned |
| "use only fictional or synthetic data" | All data in `data/` is invented; see `data/README.md` | Done |

## "What to submit"

| Brief wording | Where it is answered | Status |
|---|---|---|
| "A working build … with clear instructions so that we can open and test the prototype" | Hosted link (live, capped) + saved-response fallback + local run instructions in README | Planned |
| Deck "no more than five pages" | 5-slide PowerPoint | Planned |
| "The client problem and why you chose your approach" | Slide 1 | Planned |
| "How you built the prototype and used AI tools" | Slide 2 | Planned |
| "What you tested, including the results and limitations" | Slide 3, from `eval/run_eval.py` output | Planned |
| "The controls, human review requirements and potential effects on staff" | Slides 4–5 | Planned |
| Solution sets: "AI Strategy, Governance Engineering and Workforce AI Transformation" | Deck structured around these three | Planned |

Deadline: 5.30pm GMT, Wednesday 11 November 2026.
