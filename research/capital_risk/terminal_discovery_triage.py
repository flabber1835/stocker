"""Refine a completed private metadata inventory without rereading market data."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

from .terminal_discovery import category, digest, file_hash, load, native, save


def action_priority(event):
    roles = {role for refs in event["observed_references"].values() for role in refs}
    if event["known_blockers"]:
        return 0, "ACTUAL_BLOCKER"
    if any("OWNED_AT" in role or "PENDING_AT" in role or "HELD_IN" in role for role in roles):
        return 1, "OBSERVED_HOLDING_OR_PENDING_REFERENCE_NOT_EVENT_ENTITLEMENT"
    if any("LEADERSHIP" in role or "INTENT" in role for role in roles):
        return 2, "EXPLICIT_SELECTION_OR_INTENT_REFERENCE"
    if roles:
        return 3, "OTHER_REFERENCE_ONLY"
    if event["source_support"]["ever_eligible"]:
        return 4, "SOURCE_ELIGIBLE_WITHOUT_OBSERVED_REFERENCE"
    return 5, "RETAIN_LOWER_PRIORITY_NO_NEGATIVE_REACHABILITY_CLAIM"


def repair_documents(config):
    """Exact descriptor availability, never a union of historical terms as active."""
    result = {}
    for arm, spec in config["candidates"].items():
        root = native(spec["root"])
        cp = load(root / "book/checkpoint.json.gz")
        docs = []
        for descriptor in cp["repairs"]:
            path = root / "book/repairs" / descriptor["filename"]
            item = {"descriptor": descriptor, "available": path.exists()}
            if path.exists():
                actual = file_hash(path)
                if actual != descriptor["sha256"]:
                    raise ValueError("repair descriptor bytes differ")
                value = load(path)
                item.update(schema=value["schema"], sha256=actual,
                            added_rows=len(value.get("add", [])), suppressed_rows=len(value.get("suppress", [])))
            docs.append(item)
        result[arm] = {"checkpoint_outer_sha256": cp["sha256"], "descriptors": docs,
                       "all_descriptors_locally_available": all(x["available"] for x in docs),
                       "effective_semantics_independently_mapped_here": arm == "P02"}
    return result


def render_report(root, summary, batch, coverage, schedule_lineage):
    esc = lambda value: html.escape(str(value))
    rows = []
    for arm, value in sorted(coverage.items()):
        rows.append("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in
            (arm, value["session"], value["measured_closes"],
             f"{sum(v['available'] for v in value['journals'].values())}/4",
             "Available" if value["supplementary"]["correlation-inputs.jsonl.gz"]["available"] else "Missing")) + "</tr>")
    groups = "".join(f"<tr><td>{esc(k)}</td><td>{v:,}</td></tr>" for k, v in sorted(summary["unresolved_by_problem"].items()))
    priorities = "".join(f"<tr><td>{esc(k)}</td><td>{v:,}</td></tr>" for k, v in sorted(summary["unresolved_by_action_priority"].items()))
    blockers = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in
        (b["ticker"], b["native_session"], ", ".join(b["blocker_arms"]), b["question"])) + "</tr>"
        for b in batch["actual_unresolved_blockers"])
    future = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in
        (e["ticker"], e["native_session"], e["action_priority"], e["problem_group"], ", ".join(e["reference_arms"]))) + "</tr>"
        for e in batch["p02_next_calendar_year_observed_queue"])
    lines = ["<!doctype html><html><head><meta charset='utf-8'><title>Terminal discovery</title>",
        "<style>body{max-width:1120px;margin:40px auto;padding:0 22px;font:16px/1.55 system-ui;color:#172332;background:#f8fafc}h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%;background:white;margin:18px 0}td,th{padding:9px 12px;border-bottom:1px solid #dce3eb;text-align:left;vertical-align:top}th{background:#eaf0f6}.lead{font-size:20px}.note{padding:14px 18px;background:#e9f2f2}code{overflow-wrap:anywhere}a{color:#135c9e}</style></head><body>",
        "<h1>Terminal discovery: batch the data work before more replay</h1>",
        "<p class='lead'>Discovery is complete. The repeated stops reflect a large unresolved corporate-action/data-contract backlog. This pass neither optimizes the strategy nor establishes a new accounting defect.</p>",
        f"<p>The source scan read {summary['source_rows_read']:,} rows across 11 annual files in {summary['source_scan_seconds']:.1f} seconds, plus retained evidence for all 12 candidates. It covered 2016-04-26 formation warmup through 2026-07-31, including all 2,156 evaluation sessions.</p>",
        f"<p>It catalogued <b>{summary['native_records']:,}</b> active-bundle terminal records: 792 during warmup and 6,001 during evaluation. <b>{summary['unresolved_queue']:,}</b> lack mapped complete terms; {summary['conditional_sensor_models']} of these have admitted conditional P02 sensor models, not holder settlement accounting. {summary['p02_fact_replacements_available']} native records have effective P02 factual replacements and 85 already have complete fields in the active bundle. All records remain retained.</p>",
        "<p class='note'>A delisting, bankruptcy label or acquisition value is not a per-share payout. Never ignore the event to fabricate a continuation, assume tender participation, value a contingent right at an endpoint, upgrade an issuer/type, or round away an unsupported conversion.</p>",
        "<h2>Actionable queue</h2><p>Priority reflects observed evidence, not certainty that a future book will hold the instrument. Historical holdings references do not prove entitlement on the event date. Generic state/journal references are separated from explicit selection and intent.</p>",
        "<table><tr><th>Priority</th><th>Unresolved records</th></tr>" + priorities + "</table>",
        "<h2>Known terminal blockers</h2><table><tr><th>Instrument</th><th>Native date</th><th>Arms</th><th>Open factual question</th></tr>" + blockers + "</table>",
        "<p>ARRY1 has a factual replacement in the admitted P02 basis, but P07 still needs its own exact predecessor-bound adoption. ALDR and ZGNX are conditional unowned/unordered sensor treatments; they are not completed cash/CVR accounting for an owner.</p>",
        "<h2>What to do before the next P02 suffix</h2>",
        "<p>Resolve GBT and batch the observed acquisition/conversion names in the next calendar year. Verify mandatory holder treatment, complete consideration, effective time, frozen delivery identity/quotes and any fractional-share convention with primary sources. Keep listing/bankruptcy gaps and contingent rights as distinct workstreams. Bind each correction to the actual arm's checkpoint and input history, then use one accurate canonical continuation. Retain the full later-period queue so work can proceed in batches rather than one failure at a time.</p>",
        "<p>The table below is a bounded work batch, not a shortened backtest or a claim that names outside it cannot matter. It contains unresolved terminal records with actual holding/selection/intent references from 2022-10-01 through 2023-09-30.</p>",
        "<table><tr><th>Instrument</th><th>Native date</th><th>Priority</th><th>Problem group</th><th>Observed arms</th></tr>" + future + "</table>",
        "<h2>Problem types</h2><table><tr><th>Metadata triage group</th><th>Records</th></tr>" + groups + "</table>",
        "<p>These groups organize research. Primary evidence can change a group: for example DTV is the retained DTE corporate-unit identity problem, and FMSA is a known mixed-consideration question even though the native kind says cash merger.</p>",
        "<h2>Coverage and candid limits</h2><table><tr><th>Arm</th><th>Actual retained checkpoint</th><th>Committed closes</th><th>Local full journals</th><th>Held snapshots</th></tr>" + "".join(rows) + "</table>",
        f"<p>{summary['missing_journal_files']} of the 48 journal files are absent from the selected local evidence exports. Every available journal's actual committed byte prefix was checked, and its unsent rows remained separately labelled. Missing files and unscanned historical checkpoints prevent an exhaustive historical ownership/leadership claim for those arms. They do not prevent a complete inventory of the frozen terminal schedule. Absence of an observed reference is never an exclusion rule.</p>",
        f"<p>The archived pre-correction base has {len(schedule_lineage['base_only_rows_in_period'])} additional date/identity keys (CNR2 and VVNT); their retained active-bundle replacements are preserved in schedule-lineage.json. They are not silently reactivated. Effective P02 semantics, including supersession, are taken from the independently admitted basis, not a union of old repair documents.</p>",
        "<p>P02's latest independently reviewed checkpoint is 2022-09-30 / 1,196 closes. Its stopped run preserved 2,644 accounting snapshots, all daily factors, historical prefixes and recovered tails. The next actual refusal is GBT on 2022-10-04; Oct 3 is an unsent day, not a substitute checkpoint. No financial job is currently running and none was launched by discovery.</p>",
        "<p>The P04 permission/recovery issue, P09 exact-fraction representation refusal and P10 causal-axis issue are separate engineering queues. Terminal discovery does not fix them. P00/P08 existing full paths are preserved, but this pass does not certify comparable final performance across all arms.</p>",
        "<p><b>Conclusion:</b> this was a necessary data-readiness inventory that should have preceded repeated financial continuations. The immediate bottleneck is incomplete/mislabelled action coverage and some independent engineering failures; it is not evidence that the existing parameters are optimal. No new CAGR/max drawdown result, production fix, winner, or unseen out-of-sample claim follows from discovery. PAPER, production sources, broker/database connections and shared services were untouched.</p>",
        "<h2>Retained evidence</h2><p><a href='triage-summary.json'>Triage summary</a> · <a href='batch-plan.json'>Batch plan</a> · <a href='triage-inventory.jsonl'>Full enriched inventory</a> · <a href='inventory.jsonl'>Original scan</a> · <a href='candidate-coverage.json'>Coverage</a> · <a href='repair-descriptor-coverage.json'>Repair availability</a> · <a href='schedule-lineage.json'>Schedule lineage</a> · <a href='evidence-manifest.json'>Evidence hashes</a></p></body></html>"]
    (root / "REPORT.html").write_text("\n".join(lines), encoding="utf-8")


def run(output):
    root = native(output)
    config = load(root / "request.json")
    scan = load(root / "summary.json")
    if scan["status"] != "COMPLETE_METADATA_DISCOVERY_NOT_FINANCIAL_REPLAY":
        raise ValueError("incomplete raw discovery")
    original_manifest = load(root / "evidence-manifest.json")
    for name, item in original_manifest.items():
        if file_hash(root / name) != item["sha256"]:
            raise ValueError("original discovery output differs")
    save(root / "raw-scan-evidence-manifest.json", original_manifest)
    basis = load(root / "effective-p02-basis.json")["value"]
    models = basis["model_semantics"]
    models = models if isinstance(models, list) else [models]
    by_model_sid = {str(v["security_id"]): v for v in models if v.get("sensor_only")}
    events = [json.loads(raw) for raw in (root / "inventory.jsonl").read_text(encoding="utf-8").splitlines()]
    for event in events:
        event["problem_group"] = category(event)
        if event["native"]["ticker"] == "DTV" and event["known_blockers"]:
            event["problem_group"] = "KNOWN_UNIT_SETTLEMENT_AND_FROZEN_IDENTITY_CONFLICT"
        elif event["native"]["ticker"] == "FMSA" and event["known_blockers"]:
            event["problem_group"] = "KNOWN_STOCK_AND_CASH_CONSIDERATION"
        elif event["native"]["ticker"] == "AAAP1" and event["known_blockers"]:
            event["problem_group"] = "TENDER_VERSUS_MANDATORY_HOLDER_TREATMENT"
        event["conditional_p02_sensor_model"] = by_model_sid.get(event["security_id"])
        event["action_priority"], event["action_priority_reason"] = action_priority(event)
    events.sort(key=lambda e: (e["action_priority"], e["native_session"], e["id"]))
    with (root / "triage-inventory.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    unresolved = [e for e in events if e["unresolved_or_special_model"]]
    row = lambda e: {"id": e["id"], "ticker": e["native"]["ticker"], "security_id": e["security_id"],
        "native_session": e["native_session"], "action_priority": e["action_priority"], "problem_group": e["problem_group"],
        "reference_arms": sorted(e["observed_references"]), "conditional_model_only": bool(e["conditional_p02_sensor_model"])}
    batch = {"schema": "research.terminal-discovery-batch-plan/1", "no_financial_dispatch": True,
        "actual_unresolved_blockers": [row(e) | {"blocker_arms": sorted({a for b in e["known_blockers"] for a in b["arms"]}),
                "question": "; ".join(b["unresolved_question"] for b in e["known_blockers"])} for e in unresolved if e["known_blockers"]],
        "p02_next_calendar_year_observed_queue": [row(e) for e in unresolved
            if "2022-10-01" <= e["native_session"] <= "2023-09-30" and e["action_priority"] <= 2],
        "all_remaining_p02_period_observed_queue": [row(e) for e in unresolved
            if e["native_session"] >= "2022-10-01" and e["action_priority"] <= 2],
        "full_unresolved_queue": [row(e) for e in unresolved],
        "separate_engineering": {"P04": "Permission/recovery boundary", "P09": "Exact-fraction trim representation; no rounding or skipped trade", "P10": "Causal-axis validation"},
        "unchanged_target": "Finish P02 then the existing full-period Core candidates sequentially; no short screen or parameter change",
        "next": "Resolve relevant common facts in batches, then own exact predecessor-bound canonical continuation; never invent or ignore a term"}
    save(root / "batch-plan.json", batch)
    bundle = native(config["bundle"])
    original = load(bundle / "terminal-schedule.json")
    base = load(bundle / "repaired-base-terminal-schedule.json")
    keys = {(r["effective_session"], r["security_id"]) for r in original}
    differences = [r for r in base if (r["effective_session"], r["security_id"]) not in keys
                   and config["warmup_start"] <= r["effective_session"] <= config["end"]]
    schedule_lineage = {"active_bundle_schedule_path": str(bundle / "terminal-schedule.json"),
        "archived_base_path": str(bundle / "repaired-base-terminal-schedule.json"),
        "base_only_rows_in_period": differences, "active_replacements_for_same_security": [r for r in original
            if r["security_id"] in {v["security_id"] for v in differences}],
        "archived_rows_not_reactivated": True}
    save(root / "schedule-lineage.json", schedule_lineage)
    save(root / "repair-descriptor-coverage.json", repair_documents(config))
    summary = {"schema": "research.terminal-discovery-triage/1", "raw_scan_sha256": file_hash(root / "summary.json"),
        "native_records": scan["native_records"], "unresolved_queue": len(unresolved),
        "p02_fact_replacements_available": scan["p02_fact_replacements_available"],
        "conditional_sensor_models": sum(bool(e["conditional_p02_sensor_model"]) for e in unresolved),
        "unresolved_by_action_priority": dict(Counter(e["action_priority_reason"] for e in unresolved)),
        "unresolved_by_problem": dict(Counter(e["problem_group"] for e in unresolved)),
        "p02_next_year_observed_queue": len(batch["p02_next_calendar_year_observed_queue"]),
        "p02_remaining_period_observed_queue": len(batch["all_remaining_p02_period_observed_queue"]),
        "source_rows_read": sum(y["all_rows"] for y in scan["source_scan"]["years"]),
        "source_scan_seconds": scan["source_scan"]["seconds"], "missing_journal_files": scan["candidate_missing_journal_files"],
        "financial_simulation": False, "production_contacted": False, "no_event_ignored": True}
    save(root / "triage-summary.json", summary)
    render_report(root, summary, batch, load(root / "candidate-coverage.json"), schedule_lineage)
    save(root / "evidence-manifest.json", {p.name: {"bytes": p.stat().st_size, "sha256": file_hash(p)}
        for p in root.iterdir() if p.is_file() and p.name not in {"evidence-manifest.json", "source-scan-progress.json"}})
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    run(parser.parse_args().output)
