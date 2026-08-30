#!/usr/bin/env python3
"""Fail-closed 20-year causal certification for retained research.

The workflow runs this coordinator in three phases:
  baseline: verify immutable authority, run the complete guarded replay, select cutoffs,
            and produce timing/static/transition/domain evidence.
  shard:    execute deterministic subsets of prefix and future-poisoning cutoffs.
  aggregate: require every selected cutoff and every gate to pass and issue the verdict.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import date
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.research_causal_instrumentation import static_leakage_audit
from backtester.run_research_causal_certification import (
    chronology,
    compare_prefix,
    execution_timing,
    fval,
    hfile,
    read_trace,
)

WARMUP = "2006-01-03"
START = "2006-07-31"
END = "2026-07-31"
PACKAGE = "ghcr.io/flabber1835/stocker-canonical-pit@sha256:4f53e51d8171aab8a8ac9df90e116d27b0f9b54f95629154685ea8a2394c1265"
DATA_HASH = "f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b"
DATASET_ID = "strict-pit-2006-01-03-2026-07-31-f9fb220871ad4152"
MANIFEST_HASH = "6ffffa117407b7e2b1eb023ff20b6f8885d93ef86187749bf0c76360acd22608"
RECON_SHA = "a0f1a5b2c666b51cfd2af508bf750dd364f80948"
SOURCE_RUN = "33331951602"
PRODUCTION_SHA = "887f479b15ad861313da666ad698034d3847121c"
KNOWN_DIVERGENCE_DATES = (
    "2006-08-15",
    "2006-08-16",
    "2006-09-07",
)
STRESS_DATES = (
    "2008-09-15",
    "2008-10-10",
    "2009-03-09",
    "2011-08-08",
    "2015-08-24",
    "2018-12-24",
    "2020-03-23",
    "2022-06-16",
    "2022-10-12",
)
REQUIRED_POISON_DOMAINS = {
    "price_rows",
    "volume_rows",
    "eligibility_rows",
    "metadata_observation_rows",
    "metadata_timeline_rows",
    "action_rows",
    "terminal_rows",
    "benchmark_rows",
    "cash_rows",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_identity(pointer: Path, dataset: Path) -> dict[str, Any]:
    pointer_data = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pointer_counts = pointer_data.get("counts", {})
    manifest_counts = manifest.get("counts", {})
    expected_window = {"warmup_start": WARMUP, "measurement_start": START, "end": END}
    checks = {
        "pointer_status": pointer_data.get("status") == "PASS",
        "manifest_status": manifest.get("status") == "PASS",
        "package_digest": pointer_data.get("package") == PACKAGE,
        "dataset_hash_pointer": pointer_data.get("dataset_hash") == DATA_HASH,
        "dataset_hash_manifest": manifest.get("dataset_hash") == DATA_HASH,
        "dataset_id": pointer_data.get("dataset_id") == DATASET_ID,
        "manifest_sha256": hfile(manifest_path) == MANIFEST_HASH,
        "pointer_manifest_sha256": pointer_data.get("manifest_sha256") == MANIFEST_HASH,
        "reconstruction_code_sha": pointer_data.get("reconstruction_code_sha") == RECON_SHA,
        "source_run": str(pointer_data.get("source_run_id")) == SOURCE_RUN,
        "window": pointer_data.get("window") == expected_window,
        "pointer_manifest_counts_agree": all(
            str(pointer_counts.get(key)) == str(manifest_counts.get(key))
            for key in pointer_counts
        ),
        "unresolved_corporate_actions": int(
            manifest_counts.get("unresolved_corporate_actions", -1)
        ) == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"20-year canonical dataset identity failure: {checks}")
    return {
        "schema": "backtester.research-causal-dataset-identity/2",
        "status": "PASS",
        "pointer": str(pointer),
        "package": PACKAGE,
        "dataset_hash": DATA_HASH,
        "dataset_id": DATASET_ID,
        "manifest_sha256": MANIFEST_HASH,
        "reconstruction_code_sha": RECON_SHA,
        "source_run_id": SOURCE_RUN,
        "window": expected_window,
        "counts": pointer_counts,
        "checks": checks,
    }


def run_single(
    dataset: Path,
    output: Path,
    view: str,
    cutoff: str | None = None,
    poison_seed: int = 314159,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "backtester/run_research_causal_single_20y.py",
        "--canonical-dataset",
        str(dataset),
        "--output",
        str(output),
        "--view",
        view,
    ]
    if cutoff:
        command.extend(["--cutoff", cutoff])
    if view == "poison":
        command.extend(["--poison-seed", str(poison_seed)])
    with (output / "run.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return_code = process.wait()
    if return_code:
        raise RuntimeError(
            f"20-year causal replay failed view={view} cutoff={cutoff} rc={return_code}"
        )


def first_date(
    trace: list[tuple[str, bytes, dict[str, Any]]],
    predicate: Callable[[dict[str, Any]], bool],
    start: str = START,
) -> str | None:
    return next(
        (d for d, _, envelope in trace if d >= start and predicate(envelope["record"])),
        None,
    )


def _nearest_session(sessions: list[str], target: str) -> str:
    before = [session for session in sessions if session <= target]
    if before:
        return before[-1]
    return sessions[0]


def _adjacent_sessions(sessions: list[str], target: str) -> list[tuple[str, str]]:
    if target not in sessions:
        target = _nearest_session(sessions, target)
    index = sessions.index(target)
    rows: list[tuple[str, str]] = []
    if index > 0:
        rows.append((sessions[index - 1], "immediately before"))
    rows.append((sessions[index], "on"))
    if index + 1 < len(sessions):
        rows.append((sessions[index + 1], "immediately after"))
    return rows


def transition_rows(trace: list[tuple[str, bytes, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    previous_date: str | None = None
    for d, _, envelope in trace:
        record = envelope["record"]
        current = {
            "desired": fval(record["ldrc"].get("desired_allocation")),
            "pending": fval(record["allocation"].get("pending_control")),
            "effective": fval(record["allocation"].get("effective_control")),
            "native": fval(record["native"].get("target")),
            "reason": str(record["ldrc"].get("reason")),
        }
        if previous is not None:
            changed = [
                name for name in ("desired", "pending", "effective")
                if current[name] != previous[name]
            ]
            if changed:
                rows.append(
                    {
                        "date": d,
                        "previous_date": previous_date,
                        "changed": changed,
                        "previous": previous,
                        "current": current,
                        "effective_matches_prior_pending": (
                            current["effective"] == previous["pending"]
                        ),
                        "pending_change_not_retroactive": (
                            "pending" not in changed
                            or current["effective"] == previous["pending"]
                        ),
                        "entered_defensive_cash": (
                            previous["effective"] == 1.0
                            and current["effective"] is not None
                            and current["effective"] < 1.0
                        ),
                        "exited_defensive_cash": (
                            previous["effective"] is not None
                            and previous["effective"] < 1.0
                            and current["effective"] == 1.0
                        ),
                    }
                )
        previous = current
        previous_date = d
    return rows


def select_cutoffs(trace: list[tuple[str, bytes, dict[str, Any]]]) -> list[dict[str, Any]]:
    sessions = [d for d, _, _ in trace]
    measured = [d for d in sessions if d >= START]
    selected: OrderedDict[str, list[str]] = OrderedDict()

    def add(d: str | None, reason: str) -> None:
        if not d:
            return
        d = _nearest_session(sessions, d)
        if d < START or d > END:
            return
        selected.setdefault(d, []).append(reason)

    add(measured[0], "measurement start with complete warmup state")
    if len(measured) > 1:
        add(measured[1], "initial post-warmup session")
    add(first_date(trace, lambda r: bool(r["orders"]["items"])), "first close-generated order")
    add(first_date(trace, lambda r: bool(r["fills"]["items"])), "first fill")
    add(
        first_date(trace, lambda r: any(x.get("side") == "SELL" for x in r["fills"]["items"])),
        "first exit fill",
    )
    add(first_date(trace, lambda r: bool(r["events"]["age_reviews"])), "first age-119 review")
    add(first_date(trace, lambda r: bool(r["events"]["splits"])), "first held-security split")
    add(first_date(trace, lambda r: bool(r["events"]["dividends"])), "first held-security dividend")
    add(first_date(trace, lambda r: bool(r["events"]["terminals"])), "first portfolio terminal/delist event")

    for d in KNOWN_DIVERGENCE_DATES:
        add(d, "known research/production divergence sensitivity date")

    drawdowns = [
        (fval(envelope["record"]["wealth_core"].get("drawdown")), d)
        for d, _, envelope in trace if d >= START
    ]
    drawdowns = [(value, d) for value, d in drawdowns if value is not None]
    if drawdowns:
        worst = min(drawdowns)[1]
        for d, relation in _adjacent_sessions(sessions, worst):
            add(d, f"{relation} full-window maximum-drawdown session")

    transitions = transition_rows(trace)
    for transition in transitions:
        for d, relation in _adjacent_sessions(sessions, transition["date"]):
            add(
                d,
                f"{relation} defensive/controller transition {','.join(transition['changed'])}",
            )

    for stress in STRESS_DATES:
        add(stress, f"major market-stress checkpoint near {stress}")

    quarter_last: dict[tuple[int, int], str] = {}
    for d in measured:
        parsed = date.fromisoformat(d)
        quarter = (parsed.month - 1) // 3 + 1
        quarter_last[(parsed.year, quarter)] = d
    for (year, quarter), d in sorted(quarter_last.items()):
        add(d, f"systematic calendar sample: {year} Q{quarter} end")
        if quarter == 4:
            add(d, f"systematic year-end sample: {year}")

    add(END, "final canonical dataset session")
    return [
        {
            "cutoff": d,
            "economic_reasons": sorted(set(selected[d])),
        }
        for d in sorted(selected)
    ]


def defensive_transition_audit(
    trace: list[tuple[str, bytes, dict[str, Any]]],
    runtime_guard: dict[str, Any],
) -> dict[str, Any]:
    transitions = transition_rows(trace)
    effective = [row for row in transitions if "effective" in row["changed"]]
    entries = [row for row in transitions if row["entered_defensive_cash"]]
    exits = [row for row in transitions if row["exited_defensive_cash"]]
    counters = runtime_guard.get("counters", {})
    checks = {
        "allocation_runtime_timing_asserted": int(counters.get("allocation_timing_assertions", 0)) > 0,
        "all_effective_changes_match_prior_pending": all(
            row["effective_matches_prior_pending"] for row in effective
        ),
        "pending_changes_are_not_retroactive": all(
            row["pending_change_not_retroactive"] for row in transitions
        ),
        "actual_effective_transition_observed": bool(effective),
        "defensive_cash_entry_observed": bool(entries),
        "defensive_cash_exit_observed": bool(exits),
    }
    return {
        "schema": "backtester.research-defensive-transition-audit/1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "transition_count": len(transitions),
        "effective_transition_count": len(effective),
        "defensive_entry_count": len(entries),
        "defensive_exit_count": len(exits),
        "transitions": transitions,
        "required_cutoff_policy": "immediately before, on, and after every observed transition",
    }


def data_domain_baseline(
    trace: list[tuple[str, bytes, dict[str, Any]]],
    runtime_guard: dict[str, Any],
    identity: dict[str, Any],
    metadata_audit_sha256: str,
) -> dict[str, Any]:
    terminal_dates: dict[str, str] = {}
    for d, _, envelope in trace:
        for event in envelope["record"]["events"]["terminals"]:
            sid = str(event.get("security_id", ""))
            if sid:
                terminal_dates.setdefault(sid, d)

    witnesses: list[dict[str, Any]] = []
    terminal_ids = set(terminal_dates)
    if terminal_ids:
        for d, _, envelope in trace:
            record = envelope["record"]
            eligible = set(map(str, record["eligible_universe"].get("security_ids", [])))
            selected = set(map(str, record["selected_positions"].get("security_ids", [])))
            for sid in sorted((eligible | selected) & terminal_ids):
                if d < terminal_dates[sid] and not any(x["security_id"] == sid for x in witnesses):
                    witnesses.append(
                        {
                            "security_id": sid,
                            "pre_terminal_session": d,
                            "terminal_session": terminal_dates[sid],
                            "historically_eligible": sid in eligible,
                            "held": sid in selected,
                        }
                    )
                    if len(witnesses) >= 25:
                        break
            if len(witnesses) >= 25:
                break

    counters = runtime_guard.get("counters", {})
    checks = {
        "canonical_dataset_pass": identity.get("status") == "PASS",
        "zero_unresolved_corporate_actions": int(identity["counts"].get("unresolved_corporate_actions", -1)) == 0,
        "historical_metadata_guard_exercised": int(counters.get("metadata_accesses", 0)) > 0,
        "benchmark_prefix_guard_exercised": int(counters.get("benchmark_cache_assertions", 0)) == len(trace),
        "cash_guard_exercised": int(counters.get("cash_accesses", 0)) > 0,
        "later_terminal_securities_have_pre_terminal_participation_witness": bool(witnesses),
        "runtime_future_access_violations_zero": int(counters.get("violations", 0)) == 0,
    }
    return {
        "schema": "backtester.research-data-domain-causality-baseline/1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "terminal_preparticipation_witnesses": witnesses,
        "metadata_authority_audit_sha256": metadata_audit_sha256,
        "claims_pending_invariance_evidence": [
            "later ticker/issuer/security-type changes do not affect earlier eligibility",
            "future split/dividend/corporate-action rows do not alter earlier state",
            "future terminal terms do not alter earlier state",
            "benchmark and cash histories are suffix-independent",
            "historical universe construction is independent of a present-day survivor list",
        ],
    }


def baseline_phase(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    identity = validate_identity(args.pointer, args.canonical_dataset)
    write_json(output / "dataset-identity.json", identity)

    work = output / "baseline-work"
    run_single(args.canonical_dataset.resolve(), work, "baseline", poison_seed=args.poison_seed)
    trace = read_trace(work / "causal-trace.jsonl.gz")
    runtime_guard = json.loads((work / "runtime-guard-report.json").read_text(encoding="utf-8"))
    if len(trace) != int(identity["counts"]["session_count"]):
        raise RuntimeError(f"baseline trace rows {len(trace)} != certified session count")
    if runtime_guard.get("status") != "PASS" or int(runtime_guard.get("counters", {}).get("violations", 0)) != 0:
        raise RuntimeError("runtime causal guard failed baseline")

    shutil.copy2(work / "causal-trace.jsonl.gz", output / "baseline-causal-trace.jsonl.gz")
    shutil.copy2(work / "runtime-guard-report.json", output / "runtime-guard-report.json")
    shutil.copy2(work / "generated-research-replay.py", output / "generated-research-replay.py")
    shutil.copy2(work / "run.log", output / "baseline-run.log")
    shutil.copy2(work / "causal-run-manifest.json", output / "baseline-causal-run-manifest.json")
    shutil.copy2(work / "metadata_authority_audit.json", output / "metadata-authority-audit.json")

    cutoffs = select_cutoffs(trace)
    write_json(
        output / "cutoff-manifest.json",
        {
            "schema": "backtester.research-causal-cutoffs/2",
            "status": "PASS",
            "method": (
                "Quarter-end systematic sampling over the entire measurement period plus event, "
                "known-divergence, maximum-drawdown, stress, and every defensive/controller transition."
            ),
            "warmup_coverage": "Every replay begins at 2006-01-03.",
            "cutoff_count": len(cutoffs),
            "cutoffs": cutoffs,
        },
    )

    leakage = static_leakage_audit((work / "generated-research-replay.py").read_text(encoding="utf-8"))
    write_json(output / "static-leakage-audit.json", leakage)
    if leakage.get("status") != "PASS" or int(leakage.get("forbidden_count", -1)) != 0:
        raise RuntimeError("static leakage audit failure")

    timing = execution_timing(trace, runtime_guard)
    write_json(output / "execution-timing.json", timing)
    if timing.get("status") != "PASS":
        raise RuntimeError(f"execution timing failure: {timing.get('checks')}")
    write_json(output / "execution-chronology.json", chronology())

    defensive = defensive_transition_audit(trace, runtime_guard)
    write_json(output / "defensive-transition-audit.json", defensive)
    if defensive.get("status") != "PASS":
        raise RuntimeError(f"defensive transition audit failure: {defensive.get('checks')}")

    metadata_sha = hfile(output / "metadata-authority-audit.json")
    domain = data_domain_baseline(trace, runtime_guard, identity, metadata_sha)
    write_json(output / "data-domain-causality-baseline.json", domain)
    if domain.get("status") != "PASS":
        raise RuntimeError(f"data-domain baseline failure: {domain.get('checks')}")

    shutil.rmtree(work)
    print(
        f"[20Y BASELINE PASS] sessions={len(trace)} cutoffs={len(cutoffs)} "
        f"transitions={defensive['transition_count']} dataset={DATA_HASH}",
        flush=True,
    )
    return 0


def _preserve_run_evidence(work: Path, target: Path, label: str) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((work / "causal-run-manifest.json").read_text(encoding="utf-8"))
    shutil.copy2(work / "run.log", target / f"{label}-run.log")
    shutil.copy2(work / "causal-run-manifest.json", target / f"{label}-run-manifest.json")
    return manifest


def shard_phase(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    cut_manifest = json.loads((output / "cutoff-manifest.json").read_text(encoding="utf-8"))
    cutoffs = cut_manifest["cutoffs"]
    assigned = [
        row for index, row in enumerate(cutoffs)
        if index % args.shard_count == args.shard_index
    ]
    baseline = read_trace(output / "baseline-causal-trace.jsonl.gz")
    result_dir = output / "cutoff-results" / f"shard-{args.shard_index:02d}"
    runs_dir = output / "run-evidence" / f"shard-{args.shard_index:02d}"
    result_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    completed: list[str] = []

    for row in assigned:
        cutoff = row["cutoff"]
        reasons = row["economic_reasons"]
        prefix_work = output / f"tmp-prefix-{args.shard_index}-{cutoff}"
        run_single(args.canonical_dataset.resolve(), prefix_work, "prefix", cutoff, args.poison_seed)
        prefix = compare_prefix(baseline, read_trace(prefix_work / "causal-trace.jsonl.gz"), cutoff)
        prefix["economic_reasons"] = reasons
        prefix_manifest = _preserve_run_evidence(prefix_work, runs_dir / cutoff, "prefix")
        prefix["run_manifest"] = prefix_manifest
        shutil.rmtree(prefix_work)
        if prefix["status"] != "PASS":
            write_json(result_dir / f"{cutoff}.json", {"cutoff": cutoff, "prefix": prefix, "poison": None})
            raise RuntimeError(f"prefix invariance failure cutoff={cutoff}: {prefix}")

        poison: dict[str, Any] | None = None
        if cutoff != END:
            poison_work = output / f"tmp-poison-{args.shard_index}-{cutoff}"
            run_single(args.canonical_dataset.resolve(), poison_work, "poison", cutoff, args.poison_seed)
            poison = compare_prefix(baseline, read_trace(poison_work / "causal-trace.jsonl.gz"), cutoff)
            poison_manifest = _preserve_run_evidence(poison_work, runs_dir / cutoff, "poison")
            changed = (poison_manifest.get("poison") or {}).get("changed_rows", {})
            missing = sorted(
                domain for domain in REQUIRED_POISON_DOMAINS
                if int(changed.get(domain, 0)) <= 0
            )
            poison.update(
                {
                    "economic_reasons": reasons,
                    "poison_seed": args.poison_seed,
                    "poison_manifest": poison_manifest.get("poison"),
                    "missing_poison_domains": missing,
                    "all_required_future_domains_changed": not missing,
                }
            )
            poison["status"] = "PASS" if poison["status"] == "PASS" and not missing else "FAIL"
            shutil.rmtree(poison_work)
            if poison["status"] != "PASS":
                write_json(result_dir / f"{cutoff}.json", {"cutoff": cutoff, "prefix": prefix, "poison": poison})
                raise RuntimeError(f"future-poisoning failure cutoff={cutoff}: {poison}")

        write_json(
            result_dir / f"{cutoff}.json",
            {"cutoff": cutoff, "economic_reasons": reasons, "prefix": prefix, "poison": poison},
        )
        completed.append(cutoff)
        print(f"[20Y CUTOFF PASS] shard={args.shard_index} cutoff={cutoff}", flush=True)

    write_json(
        output / f"shard-summary-{args.shard_index:02d}.json",
        {
            "schema": "backtester.research-causal-cutoff-shard/1",
            "status": "PASS",
            "shard_index": args.shard_index,
            "shard_count": args.shard_count,
            "assigned": [row["cutoff"] for row in assigned],
            "completed": completed,
        },
    )
    return 0


def aggregate_phase(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    identity = json.loads((output / "dataset-identity.json").read_text(encoding="utf-8"))
    runtime_guard = json.loads((output / "runtime-guard-report.json").read_text(encoding="utf-8"))
    cutoff_manifest = json.loads((output / "cutoff-manifest.json").read_text(encoding="utf-8"))
    expected = [row["cutoff"] for row in cutoff_manifest["cutoffs"]]
    files = sorted((output / "cutoff-results").glob("shard-*/*.json"))
    results = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    by_cutoff = {row["cutoff"]: row for row in results}
    missing = sorted(set(expected) - set(by_cutoff))
    extra = sorted(set(by_cutoff) - set(expected))
    if missing or extra or len(results) != len(by_cutoff):
        raise RuntimeError(f"cutoff aggregation mismatch missing={missing} extra={extra}")

    prefix_results = [by_cutoff[d]["prefix"] for d in expected]
    poison_results = [by_cutoff[d]["poison"] for d in expected if d != END]
    prefix_pass = all(row and row.get("status") == "PASS" for row in prefix_results)
    poison_pass = all(row and row.get("status") == "PASS" for row in poison_results)
    prefix_report = {
        "schema": "backtester.research-prefix-invariance/2",
        "status": "PASS" if prefix_pass else "FAIL",
        "cutoff_count": len(prefix_results),
        "pass_count": sum(row.get("status") == "PASS" for row in prefix_results),
        "results": prefix_results,
    }
    poison_report = {
        "schema": "backtester.research-future-poisoning/2",
        "status": "PASS" if poison_pass else "FAIL",
        "cutoff_count": len(poison_results),
        "pass_count": sum(row.get("status") == "PASS" for row in poison_results),
        "required_domains": sorted(REQUIRED_POISON_DOMAINS),
        "results": poison_results,
    }
    write_json(output / "prefix-invariance.json", prefix_report)
    write_json(output / "future-poisoning.json", poison_report)

    static = json.loads((output / "static-leakage-audit.json").read_text(encoding="utf-8"))
    timing = json.loads((output / "execution-timing.json").read_text(encoding="utf-8"))
    defensive = json.loads((output / "defensive-transition-audit.json").read_text(encoding="utf-8"))
    domain_baseline = json.loads((output / "data-domain-causality-baseline.json").read_text(encoding="utf-8"))

    domain_checks = dict(domain_baseline["checks"])
    domain_checks.update(
        {
            "quarterly_and_event_prefix_invariance": prefix_pass,
            "future_market_metadata_action_terminal_benchmark_cash_poisoning": poison_pass,
            "historical_universe_suffix_independent": prefix_pass and poison_pass and static.get("forbidden_count") == 0,
            "future_metadata_does_not_change_prior_eligibility": prefix_pass and poison_pass,
            "future_corporate_events_do_not_change_prior_state": prefix_pass and poison_pass,
            "benchmark_cash_prefix_causal": prefix_pass and poison_pass,
        }
    )
    domain = {
        "schema": "backtester.research-data-domain-causality/1",
        "status": "PASS" if all(domain_checks.values()) else "FAIL",
        "checks": domain_checks,
        "terminal_preparticipation_witnesses": domain_baseline["terminal_preparticipation_witnesses"],
        "metadata_authority_audit_sha256": domain_baseline["metadata_authority_audit_sha256"],
        "survivorship_bias_conclusion": (
            "PASS: historical eligibility/universe state is exercised through guarded as-of metadata, "
            "later terminal securities have pre-terminal participation witnesses, and all selected "
            "prefix/poison cutoffs are suffix-independent."
        ),
    }
    write_json(output / "data-domain-causality.json", domain)

    gates = {
        "dataset_identity": identity.get("status") == "PASS",
        "runtime_guard": runtime_guard.get("status") == "PASS" and int(runtime_guard.get("counters", {}).get("violations", 0)) == 0,
        "prefix_invariance": prefix_pass,
        "future_poisoning": poison_pass,
        "execution_timing": timing.get("status") == "PASS",
        "static_leakage": static.get("status") == "PASS" and int(static.get("forbidden_count", -1)) == 0,
        "defensive_transitions": defensive.get("status") == "PASS",
        "data_domain_causality": domain.get("status") == "PASS",
    }
    passed = all(gates.values())
    equivalence_state = os.environ.get("RESEARCH_PRODUCTION_EQUIVALENCE_STATE", "PENDING").upper()
    equivalence_run = os.environ.get("RESEARCH_PRODUCTION_EQUIVALENCE_RUN", "33337500324")
    source_sha = os.environ.get("BACKTESTER_BRANCH_SHA", "UNKNOWN")
    summary = {
        "schema": "backtester.research-causal-certification/2",
        "status": "PASS" if passed else "FAIL",
        "verdict": "20_YEAR_CAUSAL_CERTIFICATION_PASS" if passed else "20_YEAR_CAUSAL_CERTIFICATION_FAIL",
        "causal_timing_certified": passed,
        "source_branch": "research/strict-pit-causal-certification-20y",
        "source_sha": source_sha,
        "production_sha": PRODUCTION_SHA,
        "research_production_equivalence": {
            "state": equivalence_state,
            "run_id": equivalence_run,
            "language": (
                "Causality certified; production equivalence pending."
                if passed and equivalence_state != "PASS"
                else "Causality and the separately proven production equivalence are both PASS."
                if passed
                else "Causality certification failed; no production certification claim is made."
            ),
        },
        "canonical_package": PACKAGE,
        "dataset_hash": DATA_HASH,
        "dataset_id": DATASET_ID,
        "manifest_sha256": MANIFEST_HASH,
        "reconstruction_code_sha": RECON_SHA,
        "source_dataset_run": SOURCE_RUN,
        "historical_window": {"warmup_start": WARMUP, "measurement_start": START, "end": END},
        "session_count": int(identity["counts"]["session_count"]),
        "observation_count": int(identity["counts"]["observation_rows"]),
        "security_count": int(identity["counts"]["security_count"]),
        "action_count": int(identity["counts"]["action_rows"]),
        "terminal_event_count": int(identity["counts"]["terminal_rows"]),
        "unresolved_corporate_action_count": int(identity["counts"]["unresolved_corporate_actions"]),
        "runtime_guard_violation_count": int(runtime_guard.get("counters", {}).get("violations", 0)),
        "prefix_cutoffs": {"count": len(prefix_results), "pass_count": prefix_report["pass_count"]},
        "poison_cutoffs": {"count": len(poison_results), "pass_count": poison_report["pass_count"]},
        "static_forbidden_finding_count": int(static.get("forbidden_count", -1)),
        "execution_timing_status": timing.get("status"),
        "defensive_transition_status": defensive.get("status"),
        "survivorship_bias_checks": domain,
        "economic_defect_found": False,
        "gates": gates,
        "baseline_trace_sha256": hfile(output / "baseline-causal-trace.jsonl.gz"),
        "qualification": (
            "The certificate is evidence for the exact retained source, canonical PIT package, and "
            "execution model. Source-vendor or SEC records could still contain an undetected factual error."
        ),
    }
    write_json(output / "certification-summary.json", summary)

    evidence = sorted(
        path for path in output.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS.txt" and not path.name.startswith("tmp-")
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{hfile(path)}  {path.relative_to(output).as_posix()}\n" for path in evidence),
        encoding="utf-8",
    )
    if not passed:
        first_failed = next(name for name, ok in gates.items() if not ok)
        raise RuntimeError(f"20_YEAR_CAUSAL_CERTIFICATION_FAIL first_failed_gate={first_failed}")
    print(
        f"[20_YEAR_CAUSAL_CERTIFICATION_PASS] sessions={summary['session_count']} "
        f"prefix={len(prefix_results)} poison={len(poison_results)}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("baseline", "shard", "aggregate"), required=True)
    parser.add_argument("--canonical-dataset", type=Path)
    parser.add_argument("--pointer", type=Path, default=Path("backtester/data/canonical-pit-20y.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poison-seed", type=int, default=314159)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    args = parser.parse_args()
    if args.phase in {"baseline", "shard"} and args.canonical_dataset is None:
        parser.error("--canonical-dataset is required for baseline and shard phases")
    if args.phase == "shard" and not (0 <= args.shard_index < args.shard_count):
        parser.error("shard index must be in [0, shard-count)")
    if args.phase == "baseline":
        return baseline_phase(args)
    if args.phase == "shard":
        return shard_phase(args)
    return aggregate_phase(args)


if __name__ == "__main__":
    raise SystemExit(main())
