"""Complaints Copilot - Streamlit front end.

Run locally:  streamlit run streamlit_app.py
All data is synthetic. Harbourline Bank is fictional.
"""
import json

import pandas as pd
import streamlit as st

from copilot import audit, config, impact
from copilot.ai import AIUnavailable, Hybrid, LiveClaude, LocalOllama, SavedResponses
from copilot.data import get_complaint, load_complaints, load_labels, load_policies
from copilot.deadlines import deadline_info, priority_score
from copilot.pipeline import handover_markdown, run_case
from copilot.redact import reidentify
from copilot.schemas import RootCause, Product, Team
from typing import get_args

st.set_page_config(page_title="Complaints Copilot", page_icon="🗂️", layout="wide")

PRODUCTS, CAUSES, TEAMS = list(get_args(Product)), list(get_args(RootCause)), list(get_args(Team))
STATUS_ICON = {"Breached": "⛔", "Critical": "🔴", "At risk": "🟠", "On track": "🟢"}


# ----------------------------------------------------------------------------- state
def ss():
    s = st.session_state
    s.setdefault("reviews", {})      # case_id -> review record
    s.setdefault("handovers", {})    # case_id -> handover record for specialists
    s.setdefault("live_runs", {})    # case_id -> live result (this session)
    s.setdefault("session_live_used", 0)
    return s


BACKENDS = {"Claude (Anthropic API)": "claude", "Local model (Ollama on this machine)": "local"}


def backend():
    return BACKENDS.get(st.session_state.get("backend"), "claude")


@st.cache_resource
def _provider(kind):
    if kind == "local":
        local = LocalOllama()
        return Hybrid(live=local if local.available() else None, saved=SavedResponses(config.LOCAL_CACHE_DIR))
    key = config.get_api_key()
    return Hybrid(live=LiveClaude(key) if key else None, saved=SavedResponses(config.CACHE_DIR))


def provider():
    return _provider(backend())


@st.cache_data(show_spinner=False)
def saved_result(cid, kind):
    """Saved-response analysis for a case (cached for the whole app)."""
    try:
        return run_case(get_complaint(cid), _provider(kind), want_live=False, log_audit=False)
    except AIUnavailable:
        return None


def get_result(cid):
    s = ss()
    return s["live_runs"].get((backend(), cid)) or saved_result(cid, backend())


def review_status(cid):
    s = ss()
    if cid in s["handovers"]:
        return s["handovers"][cid]["status"]
    if cid in s["reviews"]:
        return s["reviews"][cid]["decision"]
    return "Not reviewed"


# ----------------------------------------------------------------------------- sidebar
def sidebar():
    s = ss()
    st.sidebar.title("🗂️ Complaints Copilot")
    st.sidebar.caption("Harbourline Bank (fictional) · synthetic data only")
    page = st.sidebar.radio("View", ["Impact", "Complaint queue", "Review a case", "Specialist inbox",
                                     "Audit log", "How it works"], key="page")
    st.sidebar.divider()
    have_local = any(config.LOCAL_CACHE_DIR.glob("*.json")) or LocalOllama().available()
    if have_local:
        st.sidebar.radio("AI backend", list(BACKENDS), key="backend",
                         help="Compare Claude with a model running locally. Each has its own saved responses.")
    p = provider()
    if p.live:
        left = min(p.quota.remaining(), config.SESSION_LIVE_CAP - s["session_live_used"])
        st.sidebar.toggle("Use live AI", key="use_live", value=False,
                          help="Off: replays real responses saved earlier (free). On: calls the model now.")
        st.sidebar.caption(f"Live runs left: {max(0, left)} this session · {p.quota.remaining()} today")
    else:
        st.sidebar.info("Demo mode: showing saved AI responses. Live AI is off "
                        "(no API key, or no local model running).")
    model = f"ollama/{config.OLLAMA_MODEL}" if backend() == "local" else f"{config.MODEL} (effort {config.EFFORT})"
    st.sidebar.caption(f"Live model: `{model}` · prompt `{config.PROMPT_VERSION}`")
    if backend() != "local":
        st.sidebar.caption(f"Saved responses: `{config.SAVED_MODEL}` (each result shows the model that produced it)")
    st.sidebar.caption(f"'Today' is fixed at {config.AS_OF:%a %d %b %Y} so deadlines are reproducible.")
    return page



# ----------------------------------------------------------------------------- impact
def all_metrics():
    """Per-case measures for every case with an AI result."""
    labels = load_labels()
    items, metrics = [], []
    for c in load_complaints():
        r = get_result(c["id"])
        if r is None:
            continue
        dl = r["deadline"]
        items.append({"case_id": c["id"], "received": c["received"], "days_left": dl["days_left"],
                      "priority": r["priority"], "urgent": impact.is_urgent(labels[c["id"]], dl["status"])})
        metrics.append(impact.case_metrics(c, r, labels[c["id"]]))
    return items, metrics


def assumption_inputs():
    with st.expander("Assumptions behind the time estimates (change them to test the case)", expanded=False):
        st.caption("These are illustrative. A pilot would replace them with timed manual and assisted triages. "
                   "Every case count on this page is measured; only the minutes and hours depend on these inputs.")
        c1, c2, c3 = st.columns(3)
        a = impact.Assumptions(
            manual_triage_min=c1.number_input("Manual triage, minutes per case", 5, 120, 30),
            copilot_review_min=c1.number_input("Reviewing the copilot draft, minutes", 1, 60, 10),
            manual_handover_min=c2.number_input("Writing a handover by hand, minutes", 5, 90, 20),
            copilot_handover_min=c2.number_input("Filling flagged gaps and sending, minutes", 1, 60, 5),
            return_rework_min=c3.number_input("Rework when a handover is returned, minutes", 5, 180, 30),
            complaints_per_month=c3.number_input("Complaints per month", 50, 100000, 1000, step=50),
        )
    return a


def compare(rows):
    """Render a Measure / Before / After / Basis table."""
    rows = [[str(x) for x in r] for r in rows]
    st.dataframe(pd.DataFrame(rows, columns=["Measure", "Before (today)", "After (with copilot)", "Basis"]),
                 hide_index=True, use_container_width=True)


def before_after(before, after):
    l, r = st.columns(2)
    l.markdown(f"**Before:** {before}")
    r.markdown(f"**After:** {after}")


def page_impact():
    st.header("Impact: the three problems in the brief, before and after")
    st.caption("The brief describes a growing backlog, staff spending time finding information across case notes "
               "and policy documents, and specialist teams receiving incomplete handovers. Each section compares "
               "today's process with the copilot on the 25 synthetic cases, scored against the hand-written answer "
               "key. **Measured** figures come from the cases; **Estimate** figures depend on the assumptions below.")
    a = assumption_inputs()
    items, metrics = all_metrics()
    if not metrics:
        st.error("No AI results available to measure.")
        return
    b = impact.backlog_summary(items, a)
    info = impact.information_summary(metrics)
    h = impact.handover_summary(metrics)
    hs = ss()["handovers"]
    returned_now = sum(1 for x in hs.values() if x["returns"])

    spec = h["specialist_cases"] or 1
    t = impact.time_summary(a, h["specialist_cases"] / len(metrics), h["incomplete_as_written"] / spec,
                            (h["incomplete_as_written"] - h["blocked_before_send"]) / spec)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Handler time per complaint", f"{t['after_min']:.0f} min", f"{-t['saved_min']:.0f} min vs {t['before_min']:.0f}",
              delta_color="inverse", help="Estimate: triage + handover + rework on returned handovers.")
    c2.metric("Handler hours back a month", f"{t['hours_per_month']:,.0f}", f"≈ {t['fte']:.1f} FTE",
              delta_color="off", help=f"Estimate at {a.complaints_per_month:,} complaints a month.")
    c3.metric("Urgent cases near the top", f"{b['urgent_in_top_copilot']} of {b['urgent']}",
              f"{b['urgent_in_top_copilot'] - b['urgent_in_top_arrival']:+d} vs arrival order",
              help=f"Measured: urgent cases within the first {b['top_k']} places of the queue.")
    c4.metric("Incomplete handovers stopped", f"{h['blocked_before_send']} of {h['incomplete_as_written']}",
              help="Measured: blocked before reaching a specialist, against the answer key.")

    st.divider()
    st.subheader("1 · The growing backlog")
    before_after("cases are worked in arrival order. Severity and vulnerability are only known after a handler "
                 "has read the file, so an urgent case waits its turn.",
                 "every case is triaged on arrival and the queue is ordered by deadline risk (CH-5), severity "
                 "(CH-6) and vulnerability, so urgent cases are seen first and each one takes less time.")
    compare([
        ["Average queue position of an urgent case", f"{b['mean_pos_arrival']:.1f}", f"{b['mean_pos_copilot']:.1f}", "Measured"],
        [f"Urgent cases in the first {b['top_k']} places", f"{b['urgent_in_top_arrival']} of {b['urgent']}",
         f"{b['urgent_in_top_copilot']} of {b['urgent']}", "Measured"],
        ["Cases one handler gets through per day", b["per_day_manual"], b["per_day_copilot"], "Estimate"],
        ["Days for one handler to reach every urgent case", b["day_all_urgent_manual"], b["day_all_urgent_copilot"], "Estimate"],
        [f"Days for one handler to clear these {b['cases']} cases", b["days_backlog_manual"], b["days_backlog_copilot"], "Estimate"],
    ])
    urgent = {x["case_id"] for x in items if x["urgent"]}
    mark = lambda o: " ".join(f"**{c}**" if c in urgent else c for c in o[:b["top_k"]])
    st.caption(f"Urgent = vulnerable, high severity, or deadline breached/critical, per the answer key (bold).  \n"
               f"First {b['top_k']} in arrival order: {mark(b['arrival_order'])}  \n"
               f"First {b['top_k']} in copilot order: {mark(b['copilot_order'])}  \n"
               "Switch between the two orders on the Complaint queue page.")

    st.divider()
    st.subheader("2 · Finding information across case notes and policy documents")
    before_after("the handler reads the complaint and every note, searches the policy library for the clauses "
                 "that apply, and builds the timeline by hand.",
                 "the copilot returns a summary, a dated timeline and the clauses that apply, each quoted word "
                 "for word and checked against the policy text in code. The handler checks rather than searches.")
    compare([
        ["Policy text to search per case", f"{info['clauses_total']} clauses in {info['policy_docs']} documents "
         f"({info['policy_words']:,} words)", f"{info['avg_clauses_cited']:.1f} cited clauses "
         f"({info['avg_cited_words']:.0f} words, {info['avg_cited_words'] / max(1, info['policy_words']) * 100:.0f}%)",
         "Measured"],
        ["Citations checked against the source text", "Not checked", f"{info['citations_verified']} of "
         f"{info['citations_total']} verified; failures removed", "Measured"],
        ["Timeline events per case", f"{info['avg_timeline_events']:.1f} built by hand",
         f"{info['avg_timeline_events']:.1f} drafted with sources", "Measured"],
        ["Triage time per case", f"{a.manual_triage_min:.0f} min", f"{a.copilot_review_min:.0f} min", "Estimate"],
    ])
    st.caption(f"The handler still reads the case (about {info['avg_case_words']:.0f} words here): the copilot "
               "removes the search, not the responsibility. Synthetic files are short; real ones are longer, "
               "so the saving would likely be larger.")

    st.divider()
    st.subheader("3 · Incomplete handovers to specialist teams")
    before_after("the handler writes the handover from memory. Gaps are found by the specialist, who sends it "
                 "back (ESC-4) while the customer waits.",
                 "the copilot drafts all ten ESC-3 fields (plus FRD-3/4 for fraud and VUL-6 for third parties) "
                 "and the app will not send a handover until every gap is filled.")
    compare([
        ["Handovers missing a required field", f"{h['incomplete_as_written']} of {h['specialist_cases']} reach the specialist",
         f"{h['incomplete_as_written'] - h['blocked_before_send']} of {h['specialist_cases']} reach the specialist", "Measured"],
        ["Missing fields found before sending", "Found by the specialist", f"{h['gaps_caught']} of {h['gaps_total']} "
         f"flagged ({h['gaps_caught'] / max(1, h['gaps_total']) * 100:.0f}%)", "Measured"],
        ["Required handover fields", "All written by hand", f"{h['avg_fields_drafted']:.1f} per handover drafted "
         "for checking", "Measured"],
        ["Handover time", f"{a.manual_handover_min:.0f} min + {a.return_rework_min:.0f} min rework if returned",
         f"{a.copilot_handover_min:.0f} min", "Estimate"],
        ["Returned by specialists in this session", "Not tracked", f"{returned_now} of {len(hs)}" if hs else "none sent yet", "Live"],
    ])
    if h["missed"]:
        st.caption("Missed by the copilot, but the handover was still blocked by other gaps: " +
                   "; ".join(f"{c} ({', '.join(g)})" for c, g in h["missed"].items()))

    with st.expander("Per-case measures"):
        st.dataframe(pd.DataFrame([{
            "Case": m["case_id"], "Words to read": m["case_words"], "Clauses cited (verified)": m["clauses_cited"],
            "Timeline events": m["timeline_events"], "Needs specialist": "Yes" if m["needs_specialist"] else "No",
            "Missing fields (key)": len(m["true_gaps"]), "Flagged": len(m["gaps_caught"]),
            "Stopped before send": "Yes" if m["blocked_before_send"] else ("n/a" if not m["would_be_returned"] else "No"),
        } for m in metrics]), hide_index=True, use_container_width=True)


def case_impact(case, r):
    """What the copilot saved on this case, for the three problems in the brief."""
    label = load_labels().get(case["id"])
    if not label:
        return
    m = impact.case_metrics(case, r, label)
    items, _ = all_metrics()
    arrival, copilot = impact.queue_orders(items)
    with st.expander("What the copilot did on this case (before → after)", expanded=False):
        c1, c2, c3 = st.columns(3)
        if case["id"] in arrival:
            d = copilot.index(case["id"]) - arrival.index(case["id"])
            move = "same place as arrival order" if d == 0 else \
                f"{abs(d)} places {'earlier' if d < 0 else 'later'} than arrival order"
            c1.metric("Backlog: queue position", copilot.index(case["id"]) + 1, move,
                      delta_color="normal" if d < 0 else "off",
                      help="Urgent cases move up; routine ones move down so urgent work is seen first.")
        c2.metric("Information: policy clauses to read", f"{m['clauses_cited']} of {m['clauses_total']}",
                  f"{m['timeline_events']} timeline events drafted", delta_color="off")
        if m["needs_specialist"]:
            c3.metric("Handover: fields drafted", f"{m['fields_drafted']} of {m['fields_total']}",
                      (f"{len(m['gaps_caught'])} gaps flagged before sending" if m["true_gaps"] else "complete"),
                      delta_color="off")
        else:
            c3.metric("Handover", "Not needed", "handler resolves", delta_color="off")


# ----------------------------------------------------------------------------- queue
def page_queue():
    st.header("Complaint queue")
    st.caption("Ordered by priority: deadline risk (CH-5) + severity (CH-6) + vulnerability. "
               "Deadlines are calculated in code, never by the AI.")
    rows = []
    for c in load_complaints():
        dl = deadline_info(c["received"])
        r = get_result(c["id"])
        a = r["analysis"] if r else None
        rows.append({
            "Case": c["id"],
            "Deadline": f"{STATUS_ICON[dl['status']]} {dl['status']}",
            "Days left": dl["days_left"],
            "Received": c["received"],
            "Channel": c["channel"],
            "Product (AI)": a.product if a else "-",
            "Severity (AI)": a.severity if a else "-",
            "Vulnerable (AI)": ("Yes" if a.vulnerability.indicators_found else "No") if a else "-",
            "Route to (AI)": ", ".join(a.specialist_teams) or "Handler" if a else "-",
            "Gaps": len(r["gaps"]) if r and a and a.specialist_teams else 0,
            "Status": review_status(c["id"]),
            "Priority": r["priority"] if r else priority_score(dl["status"]),
        })
    order = st.radio("Queue order", ["Copilot priority (after)", "Arrival order, oldest first (before)"],
                     horizontal=True, key="queue_order",
                     help="Before the copilot, nobody knows a case is vulnerable or high severity until a handler "
                          "has read it, so cases are worked in arrival order.")
    df = pd.DataFrame(rows)
    if order.startswith("Arrival"):
        df = df.sort_values(["Received", "Case"])
        st.warning("Before view: cases in the order they arrived. The AI columns are shown only so you can see where "
                   "urgent cases end up; without the copilot they would be blank until a handler had read each file.")
    else:
        df = df.sort_values(["Priority", "Days left"], ascending=[False, True])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open complaints", len(df))
    c2.metric("Breached or critical", int(df["Deadline"].str.contains("Breached|Critical").sum()))
    c3.metric("Flagged vulnerable", int((df["Vulnerable (AI)"] == "Yes").sum()))
    c4.metric("Reviewed this session", int((df["Status"] != "Not reviewed").sum()))
    ev = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun",
                      selection_mode="single-row", key="queue_table")
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        cid = df.iloc[sel[0]]["Case"]
        st.session_state["case_id"] = cid
        st.button(f"Open case {cid} for review →", type="primary", on_click=open_case, args=(cid,))
    else:
        st.info("Select a row to open the case.")


# ----------------------------------------------------------------------------- review
def open_case(cid):
    st.session_state["case_id"] = cid
    st.session_state["case_pick"] = cid
    st.session_state["page"] = "Review a case"


def badge(conf):
    return {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 low"}[conf]


def page_review():
    s = ss()
    ids = [c["id"] for c in load_complaints()]
    cid = st.selectbox("Case", ids, index=ids.index(s.get("case_id", ids[0])), key="case_pick")
    s["case_id"] = cid
    case = get_complaint(cid)

    p = provider()
    want_live = bool(st.session_state.get("use_live")) and p.live is not None
    top = st.columns([3, 1])
    with top[1]:
        if want_live and st.button("Run live AI on this case", type="primary"):
            with st.spinner("Calling the model on the redacted case..."):
                try:
                    r = run_case(case, p, want_live=True,
                                 session_left=config.SESSION_LIVE_CAP - s["session_live_used"])
                    if r["meta"].get("provider") == "live":
                        s["session_live_used"] += 1
                    s["live_runs"][(backend(), cid)] = r
                except AIUnavailable as e:
                    st.error(str(e))
    r = get_result(cid)
    if r is None:
        st.error("No saved AI response exists for this case yet, and live AI is off. "
                 "The case must be triaged manually.")
        show_case(case, None)
        return
    if r.get("fallback_reason"):
        st.warning(r["fallback_reason"])
    meta = r["meta"]
    with top[0]:
        dl = r["deadline"]
        st.subheader(f"Case {cid} · {STATUS_ICON[dl['status']]} {dl['status']} · due {dl['due']} ({dl['days_left']} days)")
        st.caption(f"AI source: **{meta.get('provider')}** · model `{meta.get('model')}` · prompt "
                   f"`{meta.get('prompt_version')}`" + (f" · saved {meta['saved_at']}" if meta.get("saved_at") else ""))

    for w in r["warnings"]:
        st.error("⚠️ " + w)

    case_impact(case, r)
    left, right = st.columns([2, 3], gap="large")
    with left:
        show_case(case, r)
    with right:
        show_analysis(r)
        reviewer_panel(case, r)


def show_case(case, r):
    st.markdown("#### Case file")
    reveal = st.toggle("Show personal data (authorised reviewer only)", value=False, key=f"reveal_{case['id']}",
                       help="Re-identification happens on this screen only. The AI only ever received the redacted text.")
    if r is None:
        st.text(case["complaint"])
        return
    red, mp = r["redacted"], r["mapping"]
    show = (lambda t: reidentify(t, mp)) if reveal else (lambda t: t)
    st.markdown(f"**Complaint** · {case['channel']} · received {case['received']}")
    st.info(show(red["complaint"]))
    for i, n in enumerate(case["case_notes"], 1):
        st.markdown(f"**note_{i}** · {n['date']} · {n['author']}")
        st.text(show(red[f"note_{i}"]))
    st.markdown("**Evidence on file:** " + ("; ".join(case["evidence"]) or "none listed"))
    with st.expander(f"Redaction: {len(mp)} items masked before the AI call"):
        st.dataframe(pd.DataFrame([{"Token": k, "Type": k.strip("[]").rsplit("_", 1)[0],
                                    "Original": v if reveal else "•••"} for k, v in mp.items()]),
                     hide_index=True, use_container_width=True)
    with st.expander("Exactly what the AI received"):
        st.code(r["message_sent"], language=None)


def show_analysis(r):
    a = r["analysis"]
    st.markdown("#### AI analysis (draft for your review)")
    st.write(a.summary)
    c = a.confidence
    t = pd.DataFrame([
        {"Field": "Is a complaint (CH-1)", "AI suggestion": "Yes" if a.is_complaint else "No", "Confidence": ""},
        {"Field": "Product", "AI suggestion": a.product, "Confidence": badge(c.product)},
        {"Field": "Root cause (CH-7)", "AI suggestion": a.root_cause, "Confidence": badge(c.root_cause)},
        {"Field": "Severity (CH-6)", "AI suggestion": f"{a.severity}: {a.severity_reason}", "Confidence": badge(c.severity)},
        {"Field": "Vulnerability (VUL-1)", "AI suggestion": ("Indicators: " + ", ".join(a.vulnerability.drivers))
         if a.vulnerability.indicators_found else "None found", "Confidence": badge(c.vulnerability)},
        {"Field": "Route to (ESC-1)", "AI suggestion": (", ".join(a.specialist_teams) or "Handler resolves")
         + f": {a.routing_reason}", "Confidence": badge(c.specialist_teams)},
    ])
    st.dataframe(t, hide_index=True, use_container_width=True)
    if a.estimated_financial_loss_gbp:
        st.caption(f"Estimated financial loss mentioned: £{a.estimated_financial_loss_gbp:,.2f}")

    with st.expander("Supporting evidence from the case (checked against the text)", expanded=False):
        for e in r["evidence_checks"]:
            ok = "✅" if e["status"] == "verified" else "❌"
            st.markdown(f"{ok} **{e['field']}** ({e['source']}): “{e['quote']}”")
    with st.expander(f"Policy citations ({sum(x['status'] == 'verified' for x in r['citations'])}/"
                     f"{len(r['citations'])} verified)", expanded=True):
        pol = load_policies()
        for cit, chk in zip(a.policy_citations, r["citations"]):
            icon = {"verified": "✅", "misquoted": "⚠️", "invented": "❌"}[chk["status"]]
            st.markdown(f"{icon} **{cit.clause_id}** · {chk['status']}: “{cit.quote}”  \n_{cit.how_it_applies}_")
            if cit.clause_id in pol:
                st.caption(f"Source clause: {pol[cit.clause_id]['text'][:400]}")
    with st.expander("Timeline", expanded=False):
        for ev in a.timeline:
            st.markdown(f"- **{ev.date}** {ev.event} _({ev.source})_")
    if a.vulnerability.indicators_found:
        st.info(f"**Vulnerability support suggested:** {a.vulnerability.suggested_support}")
    st.markdown(f"**Suggested next step:** {a.suggested_next_step}")


def reviewer_panel(case, r):
    s = ss()
    a = r["analysis"]
    cid = case["id"]
    st.divider()
    st.markdown("#### Your review")
    st.caption("The AI suggests; you decide (CH-8). Every change and its reason goes in the audit log.")

    with st.form(f"review_{cid}"):
        c1, c2 = st.columns(2)
        product = c1.selectbox("Product", PRODUCTS, index=PRODUCTS.index(a.product))
        cause = c2.selectbox("Root cause", CAUSES, index=CAUSES.index(a.root_cause))
        sev = c1.selectbox("Severity", ["Low", "Medium", "High"], index=["Low", "Medium", "High"].index(a.severity))
        vuln = c2.selectbox("Vulnerability indicators", ["Yes", "No"],
                            index=0 if a.vulnerability.indicators_found else 1)
        teams = st.multiselect("Route to specialist team(s) (empty = I will resolve it)", TEAMS,
                               default=list(a.specialist_teams))

        st.markdown("**Handover completeness (ESC-3)**")
        fills = {}
        needs_handover = bool(teams)
        for row in r["completeness"]:
            if row["ok"]:
                st.markdown(f"✅ {row['label']}")
            else:
                st.markdown(f"❌ {row['label']}")
                if needs_handover:
                    fills[row["key"]] = st.text_input(f"Add what's missing: {row['label']}", key=f"fill_{cid}_{row['key']}",
                                                      placeholder="Leave blank if you need to contact the customer first")
        if a.other_gaps:
            st.caption("Other gaps the AI noticed: " + "; ".join(a.other_gaps))
        note = st.text_area("Reviewer note / reason for any change", key=f"note_{cid}")
        decision = st.radio("Decision", ["Approve AI triage", "Approve with my changes", "Reject AI output (manual triage)"],
                            horizontal=True)
        submitted = st.form_submit_button("Submit review", type="primary")

    if submitted:
        changes = {k: {"ai": ai, "human": hu} for k, ai, hu in [
            ("product", a.product, product), ("root_cause", a.root_cause, cause), ("severity", a.severity, sev),
            ("vulnerable", "Yes" if a.vulnerability.indicators_found else "No", vuln),
            ("specialist_teams", list(a.specialist_teams), teams)] if ai != hu}
        if changes and decision == "Approve AI triage":
            st.error("You changed fields, so choose 'Approve with my changes' and give a reason.")
            return
        if (changes or decision.startswith("Reject")) and not note.strip():
            st.error("A reason is required when you change or reject the AI's suggestions.")
            return
        still_missing = [k for k, v in fills.items() if not v.strip()]
        rec = {"decision": decision, "changes": changes, "filled": {k: v for k, v in fills.items() if v.strip()},
               "still_missing": still_missing, "note": note, "teams": teams}
        s["reviews"][cid] = rec
        audit.log("human_review", cid, role="Complaints handler", **rec,
                  ai_source=r["meta"].get("provider"), prompt_version=r["meta"].get("prompt_version"))
        if decision.startswith("Reject"):
            st.success("Recorded. The case goes to manual triage and the AI output is kept only in the audit log.")
        elif teams and still_missing:
            st.warning("Review saved, but the handover is blocked: ESC-3 says a handover is complete only when every "
                       "field is present. Still missing: " + ", ".join(still_missing))
        elif teams:
            md = handover_markdown(r, reviewer_note=note)
            if rec["filled"]:
                md += "\n\n### Added by reviewer\n" + "\n".join(f"- **{k}**: {v}" for k, v in rec["filled"].items())
            s["handovers"][cid] = {"teams": teams, "pack": md, "status": "Sent to specialist", "returns": []}
            audit.log("handover_sent", cid, role="Complaints handler", teams=teams)
            st.success(f"Handover sent to {', '.join(teams)}. It now appears in the Specialist inbox.")
        else:
            st.success("Approved. You remain the owner and will resolve this complaint.")

    if cid in s["handovers"]:
        with st.expander("Handover pack as sent"):
            st.markdown(s["handovers"][cid]["pack"])


# ----------------------------------------------------------------------------- specialist
def page_specialist():
    s = ss()
    st.header("Specialist inbox")
    st.caption("Specialists accept a handover or return it as incomplete, naming the missing ESC-3 fields (ESC-4). "
               "Returns are tracked as a quality measure.")
    hs = s["handovers"]
    if not hs:
        st.info("No handovers yet. Review a case that needs a specialist and send it from the review screen.")
        return
    returned = sum(1 for h in hs.values() if h["returns"])
    st.metric("Handovers returned as incomplete", f"{returned} of {len(hs)}")
    for cid, h in hs.items():
        with st.expander(f"{cid} · {', '.join(h['teams'])} · {h['status']}", expanded=h["status"] == "Sent to specialist"):
            st.markdown(h["pack"])
            if h["status"] == "Sent to specialist":
                c1, c2 = st.columns(2)
                if c1.button("Accept handover", key=f"acc_{cid}"):
                    h["status"] = "Accepted by specialist"
                    audit.log("specialist_accepted", cid, role="Specialist", teams=h["teams"])
                    st.rerun()
                with c2.popover("Return as incomplete"):
                    missing = st.multiselect("Missing fields", ["Summary", "Products and accounts", "Desired outcome",
                                                                "Timeline", "Actions taken", "Evidence held",
                                                                "Vulnerability assessment", "Contact preference",
                                                                "Open questions"], key=f"miss_{cid}")
                    why = st.text_input("Reason", key=f"why_{cid}")
                    if st.button("Return to handler", key=f"ret_{cid}") and missing:
                        h["status"] = "Returned to handler"
                        h["returns"].append({"missing": missing, "reason": why})
                        audit.log("specialist_returned", cid, role="Specialist", missing=missing, reason=why)
                        st.rerun()


# ----------------------------------------------------------------------------- audit
def page_audit():
    st.header("Audit log")
    st.caption("Append-only record of each AI analysis (redacted input, model, prompt version, output, checks) "
               "and each human decision. In production this would be write-once storage.")
    recs = audit.read()
    if not recs:
        st.info("Nothing logged yet in this deployment. Run live AI or submit a review.")
        return
    df = pd.DataFrame([{"Time (UTC)": x["ts"], "Event": x["event"], "Case": x["case_id"],
                        "Who": x.get("role", "AI (" + str(x.get("provider")) + ")"),
                        "Detail": x.get("decision") or x.get("model") or x.get("teams") or x.get("missing")}
                       for x in recs][::-1])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button("Download full log (JSON lines)", "\n".join(json.dumps(x, ensure_ascii=False) for x in recs),
                       file_name="audit_log.jsonl")


def page_about():
    st.header("How it works")
    st.markdown("""
**The problem (from the brief):** a growing backlog, staff hunting across case notes and policies, and incomplete
handovers to specialist teams.

**What this prototype does, in order:**
1. **Redacts personal data** with local rules before anything leaves the bank. The AI sees tokens like `[PERSON_1]`.
2. **Calculates deadlines in code** (8 weeks, CH-4) and sorts the queue by deadline risk, severity and vulnerability.
3. **Asks the AI for a structured analysis**: summary, timeline, product, root cause, severity, vulnerability,
   routing, policy citations and a draft ESC-3 handover, in a fixed format.
4. **Checks the AI's work in code**: every cited clause must exist and be quoted accurately; every evidence quote must
   appear in the case text; the handover is checked against all ten ESC-3 fields; prompt-injection text is flagged.
5. **A person reviews everything.** Changes need a reason. A handover with missing fields cannot be sent.
6. **Specialists accept or return** handovers, and returns are measured.
7. **Everything is logged**: input (redacted), model, prompt version, output, checks and each human decision.

**What the AI never does:** decide whether a complaint is upheld, set redress, contact the customer, or see real
personal data.

**Impact page:** shows, for each of the three problems in the brief, the process before and after, measured on the
25 cases against the answer key. Time savings are estimates from adjustable assumptions and are labelled as such.

**Demo mode:** without an API key the app replays real model responses saved earlier, so it is free to explore.
""")


# ----------------------------------------------------------------------------- main
def main():
    page = sidebar()
    {"Impact": page_impact, "Complaint queue": page_queue, "Review a case": page_review, "Specialist inbox": page_specialist,
     "Audit log": page_audit, "How it works": page_about}[page]()


main()
