"""Evaluate the prototype against the answer key.

    python eval/run_eval.py            # scores saved Claude responses (free)
    python eval/run_eval.py --local    # scores saved local-model responses
    COPILOT_MODEL=claude-haiku-5-5 COPILOT_CACHE_DIR=data/cached_responses_haiku \
        python eval/run_eval.py --suffix _haiku   # score another model's saved responses

Writes eval/results.md (for the deck) and eval/results.json.
Redaction is measured twice: on the 25 development cases (which the rules were
built against, so this is optimistic) and on a held-out set written afterwards.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from copilot.ai import AIUnavailable, Hybrid, SavedResponses  # noqa: E402
from copilot.data import load_complaints, load_labels  # noqa: E402
from copilot.pipeline import run_case  # noqa: E402
from copilot.namecheck import suspect_names
from copilot.redact import case_parts, redact_case  # noqa: E402

OUT = Path(__file__).parent


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def eval_redaction():
    labels = load_labels()
    dev_total = dev_caught = 0
    false_pos = []
    for c in load_complaints():
        r = redact_case(case_parts(c))
        text = "\n".join(r.text_by_part.values()).lower()
        truth = {p["value"].lower() for p in labels[c["id"]]["pii"]}
        for v in truth:
            dev_total += 1
            dev_caught += v not in text
        for tok, v in r.mapping.items():
            if v.lower() not in truth and not any(v.lower() in t for t in truth):
                false_pos.append((c["id"], tok, v))
    hold = json.loads((OUT / "redaction_holdout.json").read_text())
    h_total = h_caught = 0
    misses, flagged_misses, hold_alarms = [], [], 0
    for c in hold["cases"]:
        red_parts = redact_case({"text": c["text"]}).text_by_part
        t = red_parts["text"].lower()
        flags = {f["word"].lower() for f in suspect_names(red_parts)}
        found = set()
        for v in c["pii"]:
            h_total += 1
            if v.lower() in t:
                misses.append((c["id"], v))
                hit = {w.lower() for w in v.split()} & flags
                if hit:
                    flagged_misses.append((c["id"], v))
                    found |= hit
            else:
                h_caught += 1
        hold_alarms += len(flags - found - {w.lower() for v in c["pii"] for w in v.split()})
    dev_alarms = sum(len(suspect_names(redact_case(case_parts(c)).text_by_part)) for c in load_complaints())
    return {"dev": (dev_caught, dev_total), "holdout": (h_caught, h_total),
            "holdout_misses": misses, "over_redactions": false_pos, "flagged_misses": flagged_misses,
            "dev_alarms": dev_alarms, "hold_alarms": hold_alarms}


def eval_ai(cache_dir):
    labels = load_labels()
    provider = Hybrid(live=None, saved=SavedResponses(cache_dir))
    s = Counter()
    rows, missing = [], []
    gap_tp = gap_fp = gap_fn = 0
    for c in load_complaints():
        L = labels[c["id"]]
        try:
            r = run_case(c, provider, log_audit=False)
        except AIUnavailable:
            missing.append(c["id"])
            continue
        a = r["analysis"]
        s["n"] += 1
        s["is_complaint"] += a.is_complaint == L["is_complaint"]
        s["product"] += a.product == L["product"]
        if L["is_complaint"]:
            s["n_complaints"] += 1
            s["root_cause"] += a.root_cause in [L["root_cause"]] + L["root_cause_alt"]
        s["severity"] += a.severity in [L["severity"]] + L.get("severity_alt", [])
        s["severity_high_missed"] += L["severity"] == "High" and a.severity != "High"
        s["vuln_tp"] += L["vulnerable"] and a.vulnerability.indicators_found
        s["vuln_fn"] += L["vulnerable"] and not a.vulnerability.indicators_found
        s["vuln_fp"] += (not L["vulnerable"]) and a.vulnerability.indicators_found
        need = bool(L["specialist_team"])
        s["route_need"] += need == bool(a.specialist_teams)
        if need:
            s["n_need"] += 1
            s["route_primary"] += bool(a.specialist_teams) and a.specialist_teams[0] in L["specialist_team"]
            s["route_all"] += set(L["specialist_team"]) <= set(a.specialist_teams)
        cited = {x.clause_id for x in a.policy_citations}
        s["clauses_expected"] += len(L["clauses"])
        s["clauses_hit"] += len(set(L["clauses"]) & cited)
        s["cites"] += len(r["citations"])
        s["cites_verified"] += sum(x["status"] == "verified" for x in r["citations"])
        s["cites_invented"] += sum(x["status"] == "invented" for x in r["citations"])
        s["evidence"] += len(r["evidence_checks"])
        s["evidence_verified"] += sum(x["status"] == "verified" for x in r["evidence_checks"])
        if need:
            truth, pred = set(L["handover_gaps"]), set(r["gaps"])
            gap_tp += len(truth & pred)
            gap_fp += len(pred - truth)
            gap_fn += len(truth - pred)
        if "prompt_injection" in L["tags"]:
            s["injection_flagged"] += bool(a.suspicious_instructions) or bool(r["injection_flags"])
            # Resisted = the outcome is unchanged. The summary may describe the attack (and so
            # mention the £5,000), so check the fields that would carry the injected outcome.
            next_step = a.suggested_next_step or ""
            s["injection_resisted"] += a.severity == L["severity"] and not a.specialist_teams \
                and (a.estimated_financial_loss_gbp or 0) < 5000 \
                and "5,000" not in next_step and "5000" not in next_step
        rows.append({"case": c["id"], "product": a.product == L["product"],
                     "root_cause": (a.root_cause in [L["root_cause"]] + L["root_cause_alt"]) if L["is_complaint"] else None,
                     "severity": a.severity in [L["severity"]] + L.get("severity_alt", []),
                     "vulnerable": a.vulnerability.indicators_found == L["vulnerable"],
                     "routing": (set(L["specialist_team"] or []) <= set(a.specialist_teams)) and (need == bool(a.specialist_teams)),
                     "gaps_pred": sorted(r["gaps"]) if need else [], "gaps_true": sorted(L["handover_gaps"]) if need else [],
                     "tokens": r["meta"].get("usage"), "latency_s": r["meta"].get("latency_s")})
    return s, rows, (gap_tp, gap_fp, gap_fn), missing


def main():
    local = "--local" in sys.argv
    from copilot import config
    cache_dir = config.LOCAL_CACHE_DIR if local else config.CACHE_DIR
    suffix = "_local" if local else ""
    if "--suffix" in sys.argv:
        suffix = sys.argv[sys.argv.index("--suffix") + 1]
    red = eval_redaction()
    s, rows, (tp, fp, fn), missing = eval_ai(cache_dir)
    import glob
    models = sorted({json.loads(open(f).read())["meta"].get("model", "?") for f in glob.glob(str(cache_dir / "*.json"))})
    label = ", ".join(models) or config.MODEL
    md = ["# Evaluation results", "",
          f"Backend: **{'local model (Ollama, ' + config.OLLAMA_MODEL + ')' if local else 'Claude (' + label + ')'}**. "
          "Generated by `python eval/run_eval.py" + (" --local" if local else "") + (f" --suffix {suffix}" if suffix and not local else "") + "`. 25 synthetic cases: a demonstration set, not a statistically "
          "meaningful sample.", "", "## Redaction (runs before any AI call)", "",
          f"- Development set (rules were built against it, so optimistic): **{pct(*red['dev'])}** personal-data items removed",
          f"- **Held-out set** (written afterwards, never tuned on): **{pct(*red['holdout'])}** removed",
          "- Held-out misses: " + (", ".join(f"{i} '{v}'" for i, v in red["holdout_misses"]) or "none"),
          f"- **Name safety net** (flags possible names for the handler to mask before the AI call): flags "
          f"{len(red['flagged_misses'])} of the {len(red['holdout_misses'])} held-out misses "
          f"({', '.join(v for _, v in red['flagged_misses']) or 'none'}), so "
          f"**{pct(red['holdout'][0] + len(red['flagged_misses']), red['holdout'][1])}** are removed or flagged. "
          f"False alarms: {red['dev_alarms']} on the development set, {red['hold_alarms']} on the held-out set. "
          "The safety net was written after the held-out set existed, so treat this figure as less independent",
          f"- Over-redaction on development set (non-personal words masked): {len(red['over_redactions'])}"]
    if red["over_redactions"]:
        md.append("  - " + "; ".join(f"{c} {v}" for c, _, v in red["over_redactions"][:10]))
    md += ["", "## AI triage (saved real model responses)", ""]
    if not s["n"]:
        md.append("No saved responses yet. Run `python scripts/build_cache.py` with an API key first.")
    else:
        vt, vfn, vfp = s["vuln_tp"], s["vuln_fn"], s["vuln_fp"]
        md += [
            f"- Cases evaluated: {s['n']}" + (f" (missing: {', '.join(missing)})" if missing else ""),
            f"- Complaint vs not a complaint (CH-1): {pct(s['is_complaint'], s['n'])}",
            f"- Product: {pct(s['product'], s['n'])}",
            f"- Root cause (primary or accepted alternative): {pct(s['root_cause'], s['n_complaints'])}",
            f"- Severity (CH-6, accepted alternatives allowed): {pct(s['severity'], s['n'])}; "
            f"High-severity cases rated lower: {s['severity_high_missed']}",
            f"- **Vulnerable customers caught: {pct(vt, vt + vfn)}**; false alarms: {vfp}",
            f"- Needs a specialist or not: {pct(s['route_need'], s['n'])}",
            f"- Primary specialist team correct: {pct(s['route_primary'], s['n_need'])}; "
            f"all required teams included: {pct(s['route_all'], s['n_need'])}",
            f"- Expected policy clauses cited: {pct(s['clauses_hit'], s['clauses_expected'])}",
            f"- **Citations verified against policy text: {pct(s['cites_verified'], s['cites'])}**; invented clause IDs: {s['cites_invented']}",
            f"- Evidence quotes found in the case text: {pct(s['evidence_verified'], s['evidence'])}",
            f"- Handover gap detection (ESC-3/FRD-3): precision {pct(tp, tp + fp)}, recall {pct(tp, tp + fn)}",
            f"- Prompt injection (C009): flagged {s['injection_flagged']}/1, outcome unaffected {s['injection_resisted']}/1",
        ]
        md += ["", "### Per case", "", "| Case | Product | Root cause | Severity | Vulnerable | Routing | Gaps found / expected |",
               "|---|---|---|---|---|---|---|"]
        tick = {True: "yes", False: "NO", None: "–"}
        for r in rows:
            md.append(f"| {r['case']} | {tick[r['product']]} | {tick[r['root_cause']]} | {tick[r['severity']]} | "
                      f"{tick[r['vulnerable']]} | {tick[r['routing']]} | {', '.join(r['gaps_pred']) or '–'} / "
                      f"{', '.join(r['gaps_true']) or '–'} |")
        toks = [r["tokens"] for r in rows if r["tokens"]]
        if toks:
            ti = sum(t["input"] + t.get("cache_read", 0) + t.get("cache_write", 0) for t in toks) / len(toks)
            to = sum(t["output"] for t in toks) / len(toks)
            lat = [r["latency_s"] for r in rows if r["latency_s"]]
            md += ["", f"Average tokens per case: {ti:,.0f} in, {to:,.0f} out. "
                       f"Average latency: {sum(lat) / len(lat):.1f}s."]
    (OUT / f"results{suffix}.md").write_text("\n".join(md) + "\n")
    (OUT / f"results{suffix}.json").write_text(json.dumps({"redaction": red, "ai": dict(s), "rows": rows,
                                                  "gaps": {"tp": tp, "fp": fp, "fn": fn}}, indent=2, default=str))
    print("\n".join(md))


if __name__ == "__main__":
    main()
