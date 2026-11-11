"""Complaints Copilot - Streamlit front end.

Run locally:  streamlit run streamlit_app.py
All data is synthetic. Harbourline Bank is fictional.
"""
import json
import re

import pandas as pd
import streamlit as st

from copilot import audit, config
from copilot.ask import SUGGESTED, ask_live, saved_answer, verify as verify_answer
from copilot.related import related_cases
from copilot.gapchaser import QUESTIONS, customer_message
from copilot.sources import highlight_html, policy_document
from copilot.ai import AIUnavailable, Hybrid, LiveClaude, LocalOllama, SavedResponses
from copilot.data import get_complaint, load_complaints, load_labels, load_policies
from copilot.deadlines import deadline_info, priority_score, summary_resolution_by
from copilot.pipeline import handover_markdown, run_case
from copilot.redact import reidentify
from copilot.schemas import RootCause, Product, Team
from typing import get_args

st.set_page_config(page_title="Complaints Copilot", layout="wide")

PRODUCTS, CAUSES, TEAMS = list(get_args(Product)), list(get_args(RootCause)), list(get_args(Team))
VAGUE_RE = re.compile(r"(?i)(see (notes?|file|screenshots?|above|attached)|tbc|tbd|n/?a|unknown|ask customer|-+|\?+)")


# ----------------------------------------------------------------------------- state
def ss():
    s = st.session_state
    s.setdefault("reviews", {})      # case_id -> review record
    s.setdefault("handovers", {})    # case_id -> handover record for specialists
    s.setdefault("live_runs", {})    # case_id -> live result (this session)
    s.setdefault("session_live_used", 0)
    s.setdefault("trace", {})        # case_id -> {"source", "quote", "label"} for jump to source
    s.setdefault("answers", {})      # (case_id, question) -> live answer this session
    if not s.get("examples_seeded"):
        s["examples_seeded"] = True
        seed_examples(s)
    return s


# Example handovers so the specialist side can be seen without first reviewing a case.
# Values a handler "added" are fictional and contain no personal data.
EXAMPLES = {
    "C002": {"status": "Sent to specialist", "note": "Customer called back on 10/11 and answered the open questions.",
             "questions": [{"q": "Has the receiving bank been asked to recall the £4,250 yet?", "a": None}],
             "filled": {"products_accounts": "Easy Access Saver (account on file)",
                        "vulnerability_assessment": "Asked on 10/11: recently bereaved, finds calls stressful, "
                                                    "wants large print and a named contact",
                        "frd_payee_details": "Payee name [PERSON_1]; sort code and account on the payment record",
                        "frd_security_details": "Customer read a one-time passcode to the caller"}},
    "C014": {"status": "Accepted by specialist", "note": "Executor confirmed support needs by phone.",
             "filled": {"vulnerability_assessment": "Asked the executor: bereaved, wants one named contact",
                        "contact_preference": "Phone to the executor, mornings"}},
    "C021": {"status": "Returned to handler", "note": "",
             "filled": {"products_accounts": "Current account", "contact_preference": "Email",
                        "frd_payment_details": "See notes", "frd_payee_details": "See screenshots",
                        "account_secured": "Yes"},
             "returns": [{"missing": ["FRD-3 payment details", "FRD-3 payee details"],
                          "reason": "'See notes' is not enough. FRD-3 needs the date, time and amount of each "
                                    "payment and the payee's name and account. Please add them and resend."}]},
}


def seed_examples(s):
    for cid, ex in EXAMPLES.items():
        r = saved_result(cid, "claude")
        if r is None:
            continue
        teams = list(r["analysis"].specialist_teams)
        md = handover_markdown(r, reviewer_note=ex["note"])
        md += "\n\n### Added by reviewer\n" + "\n".join(f"- **{k}**: {v}" for k, v in ex["filled"].items())
        s["reviews"].setdefault(cid, {"decision": "Approve AI triage", "changes": {}, "filled": ex["filled"],
                                      "still_missing": [], "note": ex["note"], "teams": teams, "example": True})
        s["handovers"].setdefault(cid, {"teams": teams, "pack": md, "status": ex["status"],
                                        "returns": list(ex.get("returns", [])), "example": True,
                                        "questions": [dict(q) for q in ex.get("questions", [])]})


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
PAGES = {
    "Start here": "Start here",
    "Complaint queue": "Complaint queue · handler",
    "Review a case": "Review a case · handler",
    "Specialist inbox": "Specialist inbox · specialist",
    "Audit log": "Audit log · compliance",
}


def go(page):
    st.session_state["page"] = page


def sidebar():
    s = ss()
    st.sidebar.title("Complaints Copilot")
    page = st.sidebar.radio("Go to", list(PAGES), format_func=PAGES.get, key="page")
    have_local = any(config.LOCAL_CACHE_DIR.glob("*.json")) or LocalOllama().available()
    if have_local:
        st.sidebar.radio("AI backend", list(BACKENDS), key="backend",
                         help="Choose which AI model prepares the draft.")
    p = provider()
    if p.live:
        st.sidebar.divider()
        left = min(p.quota.remaining(), config.SESSION_LIVE_CAP - s["session_live_used"])
        st.sidebar.toggle("Use live AI", key="use_live", value=False,
                          help="Run the AI on the open case now.")
        st.sidebar.caption(f"Live runs left: {max(0, left)} this session · {p.quota.remaining()} today")
    return page


# ----------------------------------------------------------------------------- start
def page_start():
    st.title("Complaints Copilot")
    st.markdown("#### Prepares complaint cases for review, so handlers can decide faster and specialists get "
                "complete handovers.")

    st.markdown("### Who uses it")
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**Complaints handler**")
        st.caption("Works through a queue sorted by urgency, checks the AI draft, corrects it and sends a complete "
                   "handover.")
        st.button("Open the queue", on_click=go, args=("Complaint queue",), use_container_width=True, type="primary")
    with c2.container(border=True):
        st.markdown("**Specialist (e.g. Fraud & Scams)**")
        st.caption("Receives handovers that already contain the ten required fields, then accepts them or sends "
                   "them back.")
        st.button("Open the specialist inbox", on_click=go, args=("Specialist inbox",), use_container_width=True)
    with c3.container(border=True):
        st.markdown("**Team leader / compliance**")
        st.caption("Sees a record of every AI draft and every human decision on each case.")
        st.button("Open the audit log", on_click=go, args=("Audit log",), use_container_width=True)


# ----------------------------------------------------------------------------- queue
def short(text, n=90):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def page_queue():
    st.header("Complaint queue")
    st.markdown("**Click any row to open that case.** The most urgent cases are at the top.")
    rows = []
    for c in load_complaints():
        dl = deadline_info(c["received"])
        r = get_result(c["id"])
        a = r["analysis"] if r else None
        rows.append({
            "Case": c["id"],
            "Deadline": f"{dl['status']}",
            "Days left": dl["days_left"],
            "What it's about (AI summary)": short(a.summary) if a else "No AI draft: triage manually",
            "Severity": a.severity if a else "-",
            "Vulnerable": ("Yes" if a.vulnerability.indicators_found else "No") if a else "-",
            "Goes to": ", ".join(a.specialist_teams) or "Handler resolves" if a else "-",
            "Status": review_status(c["id"]),
            "Received": c["received"],
            "Priority": r["priority"] if r else priority_score(dl["status"]),
        })
    df = pd.DataFrame(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open complaints", len(df))
    c2.metric("Breached or critical deadline", int(df["Deadline"].str.contains("Breached|Critical").sum()))
    c3.metric("Possible vulnerable customers", int((df["Vulnerable"] == "Yes").sum()))
    c4.metric("Reviewed so far", int((df["Status"] != "Not reviewed").sum()))
    df = df.sort_values(["Priority", "Days left"], ascending=[False, True])
    ev = st.dataframe(
        df.drop(columns=["Priority", "Received"]), hide_index=True, use_container_width=True, on_select="rerun",
        selection_mode="single-row", key="queue_table", height=560,
        column_config={"Case": st.column_config.TextColumn(width="small"),
                       "Days left": st.column_config.NumberColumn(width="small"),
                       "What it's about (AI summary)": st.column_config.TextColumn(width="large"),
                       "Severity": st.column_config.TextColumn(width="small"),
                       "Vulnerable": st.column_config.TextColumn(width="small")})
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        st.session_state["pending_open"] = df.iloc[sel[0]]["Case"]
        st.rerun()


# ----------------------------------------------------------------------------- review
def open_case(cid):
    st.session_state["case_id"] = cid
    st.session_state["case_pick"] = cid
    st.session_state["page"] = "Review a case"


def queue_order():
    items = []
    for c in load_complaints():
        r = get_result(c["id"])
        dl = deadline_info(c["received"])
        items.append((-(r["priority"] if r else priority_score(dl["status"])), dl["days_left"], c["id"]))
    return [i[2] for i in sorted(items)]


def next_case(cid):
    """The next most urgent case that nobody has reviewed yet."""
    order = queue_order()
    todo = [c for c in order if review_status(c) == "Not reviewed" and c != cid]
    if not todo:
        return None
    after = [c for c in order[order.index(cid) + 1:] if c in todo]
    return (after or todo)[0]


def low_risk(r):
    a = r["analysis"]
    return (a.is_complaint and a.severity == "Low" and not a.vulnerability.indicators_found
            and not a.specialist_teams and not r["warnings"] and not r.get("name_flags")
            and all(c["status"] == "verified" for c in r["citations"])
            and all(e["status"] == "verified" for e in r["evidence_checks"]))


def quick_approve(cid, r):
    s = ss()
    rec = {"decision": "Approve AI triage", "changes": {}, "filled": {}, "still_missing": [], "note": "",
           "teams": [], "quick": True}
    s["reviews"][cid] = rec
    audit.log("human_review", cid, role="Complaints handler", **rec, ai_source=r["meta"].get("provider"),
              prompt_version=r["meta"].get("prompt_version"))
    nxt = next_case(cid)
    if nxt:
        open_case(nxt)


def quick_paths(case, r):
    cid, a = case["id"], r["analysis"]
    last, possible = summary_resolution_by(case["received"])
    if a.is_complaint and possible and not a.specialist_teams and not a.vulnerability.indicators_found:
        st.success(f"**Quick fix possible:** if you resolve this to the customer's satisfaction by "
                   f"{last:%a %d %b}, it can be closed with a summary resolution letter (CH-3), with no full "
                   f"investigation.")
    if low_risk(r) and review_status(cid) == "Not reviewed":
        with st.container(border=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="center")
            c1.markdown("**Low-risk case:** low severity, no vulnerability, no specialist needed and every "
                        "check passed. Read the draft, then approve it in one click.")
            c2.button("Approve and next →", type="primary", key=f"quick_{cid}", on_click=quick_approve,
                      args=(cid, r), use_container_width=True)


def name_check(cid, r):
    flags = r.get("name_flags") or []
    if not flags:
        return
    with st.container(border=True):
        words = sorted({f["word"] for f in flags})
        st.markdown("**Possible names that were not masked:** " +
                    ", ".join(f"**{w}** ({', '.join(sorted({f['part'] for f in flags if f['word'] == w}))})"
                              for w in words))
        c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
        c1.multiselect("Mask these before the AI sees the case", words, key=f"masks_{cid}")
        c2.checkbox("I've checked these words", key=f"names_ok_{cid}")


def set_trace(cid, tr):
    st.session_state["trace"][cid] = tr


def trace_button(cid, source, quote, label, key):
    st.button("Show", key=key, help="Highlight this in the case file", on_click=set_trace,
              args=(cid, {"source": source, "quote": quote, "label": label}))


def badge(conf):
    return {"high": "High", "medium": "Medium", "low": "Low"}[conf]


def page_review():
    s = ss()
    ids = [c["id"] for c in load_complaints()]
    st.header("Review a case")

    def label(i):
        res = get_result(i)
        dl = deadline_info(get_complaint(i)["received"])
        return f"{i} · {dl['status']} · " + (short(res["analysis"].summary, 70) if res else "no AI draft")
    cid = st.selectbox("Choose a case", ids, index=ids.index(s.get("case_id", ids[0])), key="case_pick",
                       format_func=label)
    s["case_id"] = cid
    case = get_complaint(cid)

    p = provider()
    want_live = bool(st.session_state.get("use_live")) and p.live is not None
    top = st.columns([3, 1])
    with top[1]:
        prev = get_result(cid)
        flags_open = bool(prev and prev.get("name_flags")) and not st.session_state.get(f"names_ok_{cid}")
        if want_live and st.button("Run live AI on this case", type="primary", disabled=flags_open,
                                   help="Check the possible names below first." if flags_open else None):
            with st.spinner("Calling the model on the redacted case..."):
                try:
                    r = run_case(case, p, want_live=True, extra_names=st.session_state.get(f"masks_{cid}", []),
                                 session_left=config.SESSION_LIVE_CAP - s["session_live_used"])
                    if r["meta"].get("provider") == "live":
                        s["session_live_used"] += 1
                    s["live_runs"][(backend(), cid)] = r
                except AIUnavailable as e:
                    st.error(str(e))
    r = get_result(cid)
    if r is None:
        st.error("No AI draft is available for this case. Triage it manually.")
        show_case(case, None)
        return
    if r.get("fallback_reason"):
        st.warning("Live AI is unavailable right now, so the existing draft is shown.")
    meta = r["meta"]
    with top[0]:
        dl = r["deadline"]
        st.subheader(f"Case {cid} · {dl['status']} · reply due {dl['due']} "
                     f"({dl['days_left']} days left)")

    s1, s2, s3 = st.columns(3)
    s1.info("**1. Read the case** on the left. Use *Show* to find where each point comes from.")
    s2.info("**2. Check the AI draft** on the right. Only rely on points marked *Verified*.")
    s3.info("**3. Decide** in *Your review* below: approve, correct (with a reason) or reject. "
            "[Jump there ↓](#your-review)")
    nxt = next_case(cid)
    if nxt:
        st.button(f"Next case → {nxt}", on_click=open_case, args=(nxt,), key=f"next_{cid}")
    quick_paths(case, r)
    name_check(cid, r)
    if r["warnings"]:
        st.warning("**Things to check on this case**\n" + "\n".join(f"- {w}" for w in r["warnings"]))

    left, right = st.columns([2, 3], gap="large")
    with left:
        show_case(case, r)
    with right:
        cases = {c["id"]: c for c in load_complaints()}
        matches, note = related_cases(cid, cases, {k: (get_result(k) or {}).get("analysis") for k in cases})
        t1, t2, t3 = st.tabs(["AI analysis", "Ask the case", f"Related cases ({len(matches)})" + (" · possible pattern" if note else "")])
        with t1:
            show_analysis(r)
        with t2:
            ask_panel(cid, r)
        with t3:
            show_related(cid, matches, note)
        reviewer_panel(case, r)


STICKY_CSS = """<style>
div[data-testid="stColumn"]:has(#case-file-anchor) {position: sticky; top: 3.5rem; align-self: flex-start;
  max-height: calc(100vh - 4.5rem); overflow-y: auto;}
mark {background: #ffe27a; color: inherit; padding: 0 2px; border-radius: 3px;}
</style>"""


def show_case(case, r):
    st.markdown(STICKY_CSS + "<span id='case-file-anchor'></span>", unsafe_allow_html=True)
    st.markdown("#### Case file")
    reveal = st.toggle("Show personal data (authorised reviewer only)", value=False, key=f"reveal_{case['id']}",
                       help="Re-identification happens on this screen only. The AI only ever received the redacted text.")
    if r is None:
        st.text(case["complaint"])
        return
    red, mp = r["redacted"], r["mapping"]
    show = (lambda t: reidentify(t, mp)) if reveal else (lambda t: t)
    tr = ss()["trace"].get(case["id"])
    if tr:
        c1, c2 = st.columns([4, 1])
        c1.success(f"Showing the source for: {tr['label']}")
        c2.button("Clear", key=f"clear_trace_{case['id']}", on_click=set_trace, args=(case["id"], None))

    def block(part, title, boxed=False):
        text = show(red[part])
        hit = tr and tr["source"] == part
        body = highlight_html(text, show(tr["quote"]) if hit and tr.get("quote") else None,
                              whole=bool(hit and not tr.get("quote")))
        style = ("border-left:4px solid #e0a800;padding-left:10px;" if hit else "") + \
                ("background:rgba(28,131,225,0.08);padding:10px;border-radius:6px;" if boxed else "")
        st.markdown(f"**{title}**")
        st.markdown(f"<div style='{style}font-size:0.92rem;line-height:1.5'>{body}</div>", unsafe_allow_html=True)

    block("complaint", f"Complaint · {case['channel']} · received {case['received']}", boxed=True)
    for i, n in enumerate(case["case_notes"], 1):
        block(f"note_{i}", f"note_{i} · {n['date']} · {n['author']}")
    st.markdown("**Evidence on file:** " + ("; ".join(case["evidence"]) or "none listed"))
    with st.expander(f"Redaction: {len(mp)} items masked before the AI call"):
        st.dataframe(pd.DataFrame([{"Token": k, "Type": k.strip("[]").rsplit("_", 1)[0],
                                    "Original": v if reveal else "•••"} for k, v in mp.items()]),
                     hide_index=True, use_container_width=True)
    with st.expander("Exactly what the AI received"):
        st.code(r["message_sent"], language=None)


def show_analysis(r):
    a = r["analysis"]
    st.markdown("#### AI draft for your review")
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
    md = "| Field | AI suggestion | Confidence |\n|---|---|---|\n" + "\n".join(
        f"| **{x['Field']}** | {x['AI suggestion'].replace('|', '/')} | {x['Confidence']} |" for x in t.to_dict("records"))
    st.markdown(md)

    if a.estimated_financial_loss_gbp:
        st.caption(f"Estimated financial loss mentioned: £{a.estimated_financial_loss_gbp:,.2f}")

    cid = r["case_id"]
    with st.expander(f"Evidence quotes behind the draft ({sum(e['status'] == 'verified' for e in r['evidence_checks'])}"
                     f"/{len(r['evidence_checks'])} found in the case text)", expanded=False):
        for i, e in enumerate(r["evidence_checks"]):
            ok = "Found:" if e["status"] == "verified" else "Not found:"
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"{ok} **{e['field']}** ({e['source']}): “{e['quote']}”")
            if e["field"] != "timeline":
                with c2:
                    trace_button(cid, e["source"], e["quote"], f"{e['field']} evidence", f"tr_ev_{cid}_{i}")
    nver = sum(x['status'] == 'verified' for x in r['citations'])
    with st.expander(f"Policy rules that apply ({nver}/{len(r['citations'])} quotes checked against the policy, "
                     f"{'all verified' if nver == len(r['citations']) else 'check these'})", expanded=False):
        pol = load_policies()
        for cit, chk in zip(a.policy_citations, r["citations"]):
            st.markdown(f"**{cit.clause_id}** · {chk['status'].capitalize()}: “{cit.quote}”  \n_{cit.how_it_applies}_")
            if cit.clause_id in pol:
                doc = policy_document(cit.clause_id)
                with st.popover(f"Full policy: {pol[cit.clause_id]['policy'].split('—')[-1].strip()}",
                                use_container_width=False):
                    st.markdown(doc or pol[cit.clause_id]["text"])
    with st.expander(f"Timeline ({len(a.timeline)} events, click Show to see each source)", expanded=False):
        for i, ev in enumerate(a.timeline):
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"**{ev.date}** {ev.event} _({ev.source})_")
            if ev.source in r["redacted"]:
                with c2:
                    trace_button(cid, ev.source, None, f"timeline: {ev.date}", f"tr_tl_{cid}_{i}")
    if a.vulnerability.indicators_found:
        st.info(f"**Vulnerability support suggested:** {a.vulnerability.suggested_support}")
    st.markdown(f"**Suggested next step:** {a.suggested_next_step}")


def show_related(cid, matches, note):
    if True:
        if note:
            st.warning(note)
        if not matches:
            st.caption("No other open complaint shares this incident, root cause or product.")
        for m in matches:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{m['case_id']}** · {'; '.join(m['reasons'])} · {m['days_apart']} days apart  \n"
                        f"<span style='font-size:0.85rem'>{m['summary'][:220]}…</span>", unsafe_allow_html=True)
            c2.button("Open", key=f"rel_{cid}_{m['case_id']}", on_click=open_case, args=(m["case_id"],))


def ask_panel(cid, r):
    s = ss()
    st.markdown("#### Ask the case")
    st.caption("Pick a question. Use *Show* to see each quote in the case file.")
    p = provider()
    live_ok = backend() == "claude" and p.live is not None and bool(st.session_state.get("use_live"))
    for i, q in enumerate(SUGGESTED):
        if st.button(q, key=f"sugg_{cid}_{i}", use_container_width=True):
            s["ask_q"] = (cid, q)
    pending = s.get("ask_q")
    if not pending or pending[0] != cid:
        return
    q = pending[1]
    res = s["answers"].get((cid, q)) or saved_answer(cid, r["message_sent"], q)
    if res is None and live_ok:
        left = min(p.quota.remaining(), config.SESSION_LIVE_CAP - s["session_live_used"])
        if left <= 0:
            st.warning("Live quota used up for now.")
            return
        with st.spinner("Asking the model about the redacted case..."):
            try:
                p.quota.use()
                s["session_live_used"] += 1
                res = ask_live(p.live.client, p.live.model, r["message_sent"], q)
                s["answers"][(cid, q)] = res
            except AIUnavailable as e:
                st.error(str(e))
                return
    if res is None:
        st.info("This question can't be answered for this case right now.")
        return
    ans, meta = res
    checks = verify_answer(ans, r["redacted"])
    if (cid, q) not in s.setdefault("ask_logged", set()):
        s["ask_logged"].add((cid, q))
        audit.log("ask_the_case", cid, provider=meta.get("provider"), model=meta.get("model"), question=q,
                  answer=ans.answer, quotes_verified=sum(c["verified"] for c in checks), quotes=len(checks))
    st.markdown(f"**Q: {q}**")
    found = {"yes": "Answered from the file", "partly": "Partly in the file", "no": "Not in the file"}
    st.markdown(f"{ans.answer}  \n_{found[ans.found_in_file]} · {sum(c['verified'] for c in checks)}/{len(checks)} "
                f"quotes verified_")
    pol = load_policies()
    for i, c in enumerate(checks):
        c1, c2 = st.columns([5, 1], vertical_alignment="center")
        c1.markdown(f"{'Verified' if c['verified'] else 'Not found'}: **{c['source']}**: “{c['quote']}”")
        if c["source"] in r["redacted"]:
            with c2:
                trace_button(cid, c["source"], c["quote"], f"answer quote from {c['source']}", f"tr_ask_{cid}_{i}")
        elif c["source"].upper() in pol:
            with c2.popover("Policy"):
                st.markdown(policy_document(c["source"].upper()) or "")
    if any(not c["verified"] for c in checks):
        st.warning("Some quotes could not be found in the source. Treat those parts of the answer as unconfirmed.")


def reviewer_panel(case, r):
    s = ss()
    a = r["analysis"]
    cid = case["id"]
    st.divider()
    st.markdown("#### Your review")
    h = s["handovers"].get(cid)
    if h and h["returns"]:
        for ret in h["returns"]:
            st.error(f"**The specialist returned this handover.** Missing: {', '.join(ret['missing'])}. {ret['reason']}")

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
                st.markdown(f"Present: {row['label']}")
            else:
                st.markdown(f"**Missing:** {row['label']}")
                if row["key"] in QUESTIONS and needs_handover:
                    who, q = QUESTIONS[row["key"]]
                    st.caption(("Ask the customer: " if who == "customer" else "Check internally: ") + q)
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
        vague = [k for k, v in fills.items() if VAGUE_RE.fullmatch(v.strip())]
        if vague:
            st.warning("Answers such as 'see notes' or 'TBC' don't complete a field, because the specialist can't act "
                       "on them (this is the most common reason for a return). Treated as still missing: " +
                       ", ".join(vague))
        fills = {k: ("" if k in vague else v) for k, v in fills.items()}
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

    open_gaps = [row["key"] for row in r["completeness"] if not row["ok"]]
    if a.specialist_teams and open_gaps:
        msg = customer_message(open_gaps)
        if msg:
            with st.expander("Draft message asking the customer for the missing details", expanded=False):
                st.caption("Edit it if needed and send it from your usual channel. Nothing is sent automatically.")
                st.text_area("Message", msg, height=260, key=f"msg_{cid}", label_visibility="collapsed")
                if st.button("I've sent this to the customer", key=f"msgsent_{cid}"):
                    audit.log("customer_info_requested", cid, role="Complaints handler", fields=open_gaps)
                    st.success("Logged. Fill in the fields above when the customer replies, then send the handover.")

    h = s["handovers"].get(cid)
    for i, qa in enumerate(h.get("questions", []) if h else []):
        with st.container(border=True):
            st.markdown(f"**{', '.join(h['teams'])} asked:** {qa['q']}")
            if qa.get("a"):
                st.markdown(f"**Your answer:** {qa['a']}")
            else:
                ans = st.text_input("Your answer", key=f"qa_{cid}_{i}")
                if st.button("Send answer", key=f"qasend_{cid}_{i}") and ans.strip():
                    qa["a"] = ans.strip()
                    audit.log("handler_answered", cid, role="Complaints handler", question=qa["q"], answer=qa["a"])
                    st.rerun()

    if cid in s["handovers"]:
        with st.expander("Handover pack as sent"):
            st.markdown(s["handovers"][cid]["pack"])


# ----------------------------------------------------------------------------- specialist
def page_specialist():
    s = ss()
    st.header("Specialist inbox")
    hs = s["handovers"]
    if not hs:
        st.info("No handovers yet. Review a case that needs a specialist and send it from the review screen.")
        return
    teams_all = sorted({t for h in hs.values() for t in h["teams"]})
    team = st.selectbox("Specialist team", ["All teams"] + teams_all, key="spec_team",
                        help="Each team would see only its own inbox.")
    shown = {c: h for c, h in hs.items() if team == "All teams" or team in h["teams"]}
    returned = sum(1 for h in shown.values() if h["returns"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Waiting for a specialist", sum(1 for h in shown.values() if h["status"] == "Sent to specialist"))
    c2.metric("Accepted", sum(1 for h in shown.values() if h["status"] == "Accepted by specialist"))
    c3.metric("Returned as incomplete", f"{returned} of {len(shown)}")
    for cid, h in shown.items():
        with st.expander(f"{cid} · {', '.join(h['teams'])} · {h['status']}",
                         expanded=False):
            for ret in h["returns"]:
                st.error(f"**Returned:** missing {', '.join(ret['missing'])}. {ret['reason']}")
            for qa in h.get("questions", []):
                st.info(f"**You asked:** {qa['q']}  \n" + (f"**Handler:** {qa['a']}" if qa.get("a") else "_Waiting for the handler_"))
            st.markdown(h["pack"])
            if h["status"] == "Sent to specialist":
                c1, c3, c2 = st.columns(3)
                if c1.button("Accept handover", key=f"acc_{cid}"):
                    h["status"] = "Accepted by specialist"
                    audit.log("specialist_accepted", cid, role="Specialist", teams=h["teams"])
                    st.rerun()
                with c3.popover("Ask the handler a question"):
                    q = st.text_input("Question", key=f"askq_{cid}",
                                      placeholder="e.g. Has the receiving bank been asked to recall the payment?")
                    if st.button("Send question", key=f"askqs_{cid}") and q.strip():
                        h.setdefault("questions", []).append({"q": q.strip(), "a": None})
                        audit.log("specialist_question", cid, role="Specialist", question=q.strip())
                        st.rerun()
                with c2.popover("Return as incomplete"):
                    missing = st.multiselect("Missing fields", ["Summary", "Products and accounts", "Desired outcome",
                                                                "Timeline", "Actions taken", "Evidence held",
                                                                "Vulnerability assessment", "Contact preference",
                                                                "Open questions", "FRD-3 payment details",
                                                                "FRD-3 payee details", "FRD-3 contact method",
                                                                "FRD-3 security details", "FRD-4 account secured",
                                                                "VUL-6 third-party authority"], key=f"miss_{cid}")
                    why = st.text_input("Reason", key=f"why_{cid}")
                    if st.button("Return to handler", key=f"ret_{cid}") and missing:
                        h["status"] = "Returned to handler"
                        h["returns"].append({"missing": missing, "reason": why})
                        audit.log("specialist_returned", cid, role="Specialist", missing=missing, reason=why)
                        st.rerun()


# ----------------------------------------------------------------------------- audit
def page_audit():
    st.header("Audit log")
    recs = audit.read()
    if not recs:
        st.info("Nothing logged yet. Submit a review to add an entry.")
        return
    df = pd.DataFrame([{"Time (UTC)": x["ts"], "Event": x["event"], "Case": x["case_id"],
                        "Who": x.get("role", "AI (" + str(x.get("provider")) + ")"),
                        "Detail": x.get("decision") or x.get("model") or x.get("teams") or x.get("missing")}
                       for x in recs][::-1])
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button("Download full log (JSON lines)", "\n".join(json.dumps(x, ensure_ascii=False) for x in recs),
                       file_name="audit_log.jsonl")


# ----------------------------------------------------------------------------- main
def main():
    pending = st.session_state.pop("pending_open", None)
    if pending:
        open_case(pending)
        st.session_state.pop("queue_table", None)
    page = sidebar()
    {"Start here": page_start, "Complaint queue": page_queue, "Review a case": page_review, "Specialist inbox": page_specialist,
     "Audit log": page_audit}[page]()


main()
