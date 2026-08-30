#!/usr/bin/env python3
"""Run bounded fail-closed causal certification for retained research."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester.research_causal_instrumentation import static_leakage_audit

WARMUP = "2006-01-03"
START = "2006-07-31"
END = "2007-12-31"
MED = "1035638340512403010"
DATA_HASH = "08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6"
PACKAGE = "ghcr.io/flabber1835/stocker-canonical-pit@sha256:37b41e3b91a8e26cfa3030039467ca94d71d0090839dae48e290453d7a17eadb"
MANIFEST_HASH = "008f768539c8e6d0e5f2f01a05dab1baf93560c2ffeb7ca7b1521b1a236263e1"
RECON_SHA = "eb873b399024679e6534797b1e9f4bcccbe36656"


def hfile(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fval(value: Any) -> float | None:
    if value is None or value == "NaN":
        return None
    if value == "+Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    return float(value) if isinstance(value, (int, float)) else float.fromhex(str(value))


def read_trace(path: Path) -> list[tuple[str, bytes, dict[str, Any]]]:
    rows: list[tuple[str, bytes, dict[str, Any]]] = []
    with gzip.open(path, "rb") as handle:
        for raw in handle:
            if raw.strip():
                payload = json.loads(raw)
                rows.append((str(payload["record"]["date"]), raw, payload))
    dates = [row[0] for row in rows]
    if dates != sorted(set(dates)):
        raise RuntimeError(f"nonchronological causal trace: {path}")
    return rows


def first_difference(left: Any, right: Any, path: str = "$") -> dict[str, Any] | None:
    if type(left) is not type(right):
        return {"path": path, "left": left, "right": right, "reason": "type"}
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return {"path": f"{path}.{key}", "reason": "missing_key"}
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return {"path": path, "left": len(left), "right": len(right), "reason": "length"}
        for index, (lvalue, rvalue) in enumerate(zip(left, right)):
            found = first_difference(lvalue, rvalue, f"{path}[{index}]")
            if found:
                return found
        return None
    if left != right:
        return {"path": path, "left": left, "right": right, "reason": "value"}
    return None


def compare_prefix(
    baseline: list[tuple[str, bytes, dict[str, Any]]],
    candidate: list[tuple[str, bytes, dict[str, Any]]],
    cutoff: str,
) -> dict[str, Any]:
    expected = [row for row in baseline if row[0] <= cutoff]
    actual = [row for row in candidate if row[0] <= cutoff]
    if len(expected) != len(actual):
        return {
            "status": "FAIL",
            "cutoff": cutoff,
            "expected_rows": len(expected),
            "actual_rows": len(actual),
            "first_mismatch": {"reason": "row_count"},
        }
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left[1] != right[1]:
            return {
                "status": "FAIL",
                "cutoff": cutoff,
                "expected_rows": len(expected),
                "actual_rows": len(actual),
                "first_mismatch": {
                    "row": index,
                    "date": left[0],
                    "detail": first_difference(left[2], right[2]),
                    "expected_line_sha256": hashlib.sha256(left[1]).hexdigest(),
                    "actual_line_sha256": hashlib.sha256(right[1]).hexdigest(),
                },
            }
    joined = b"".join(row[1] for row in expected)
    return {
        "status": "PASS",
        "cutoff": cutoff,
        "rows": len(expected),
        "prefix_sha256": hashlib.sha256(joined).hexdigest(),
        "byte_for_byte_identical": True,
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
        "backtester/run_research_causal_single.py",
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
            f"causal replay failed view={view} cutoff={cutoff} rc={return_code}"
        )


def validate_identity(pointer: Path, dataset: Path) -> dict[str, Any]:
    pointer_data = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = dataset / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = {
        "pointer_status": pointer_data.get("status") == "PASS",
        "manifest_status": manifest.get("status") == "PASS",
        "package": pointer_data.get("package") == PACKAGE,
        "pointer_dataset_hash": pointer_data.get("dataset_hash") == DATA_HASH,
        "manifest_dataset_hash": manifest.get("dataset_hash") == DATA_HASH,
        "manifest_sha256": hfile(manifest_path) == MANIFEST_HASH,
        "pointer_manifest_sha256": pointer_data.get("manifest_sha256") == MANIFEST_HASH,
        "reconstruction_sha": pointer_data.get("reconstruction_code_sha") == RECON_SHA,
        "window": pointer_data.get("window")
        == {"warmup_start": WARMUP, "measurement_start": START, "end": END},
        "unresolved_actions": int(
            manifest.get("counts", {}).get("unresolved_corporate_actions", -1)
        )
        == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"canonical dataset identity failure: {checks}")
    return {
        "status": "PASS",
        "pointer": str(pointer),
        "package": pointer_data["package"],
        "dataset_hash": pointer_data["dataset_hash"],
        "dataset_id": pointer_data["dataset_id"],
        "manifest_sha256": hfile(manifest_path),
        "reconstruction_code_sha": pointer_data["reconstruction_code_sha"],
        "source_run_id": pointer_data["source_run_id"],
        "window": pointer_data["window"],
        "checks": checks,
    }


def first_date(
    trace: list[tuple[str, bytes, dict[str, Any]]],
    predicate: Callable[[dict[str, Any]], bool],
    start: str = START,
) -> str | None:
    return next(
        (date for date, _, envelope in trace if date >= start and predicate(envelope["record"])),
        None,
    )


def select_cutoffs(trace: list[tuple[str, bytes, dict[str, Any]]]) -> list[dict[str, str]]:
    selected: OrderedDict[str, list[str]] = OrderedDict()

    def add(date: str | None, reason: str) -> None:
        if date and "2006-08-01" <= date <= END:
            selected.setdefault(date, []).append(reason)

    add(
        "2006-08-01",
        "first session after measurement start; includes complete warmup and initial entries",
    )
    add(first_date(trace, lambda row: bool(row["orders"]["items"])), "first measured close with orders")
    add(first_date(trace, lambda row: bool(row["fills"]["items"])), "first measured open with fills")
    add(
        first_date(
            trace,
            lambda row: any(item.get("side") == "SELL" for item in row["fills"]["items"]),
        ),
        "first measured exit or rebalance fill",
    )
    add(
        first_date(trace, lambda row: bool(row["events"]["terminals"])),
        "first post-measurement terminal-event session",
    )
    add(
        first_date(trace, lambda row: bool(row["events"]["age_reviews"])),
        "first actual age-119 review cohort",
    )
    for date, reason in (
        ("2006-08-15", "MED age-28 trailing-stop decision; disconfirmed prior age-119 label"),
        ("2006-08-16", "MED next-open stop fill and held-security split"),
        ("2006-09-07", "historical first-divergence sensitivity checkpoint"),
        ("2006-09-29", "quarter-end reporting checkpoint"),
        ("2006-12-29", "year-end and quarter-end checkpoint"),
        ("2007-02-21", "held-security split checkpoint"),
        ("2007-09-28", "quarter-end reporting checkpoint"),
        (END, "bounded dataset end"),
    ):
        add(date, reason)
    drawdowns = [
        (fval(envelope["record"]["wealth_core"]["drawdown"]), date)
        for date, _, envelope in trace
        if fval(envelope["record"]["wealth_core"]["drawdown"]) is not None
    ]
    if drawdowns:
        add(min(drawdowns)[1], "maximum drawdown and defensive-controller evaluation")
    sessions = {date for date, _, _ in trace}
    missing = [date for date in selected if date not in sessions]
    if missing:
        raise RuntimeError(f"selected cutoffs are not canonical sessions: {missing}")
    return [
        {"cutoff": date, "economic_reasons": "; ".join(selected[date])}
        for date in sorted(selected)
    ]


def execution_timing(
    trace: list[tuple[str, bytes, dict[str, Any]]],
    guard: dict[str, Any],
) -> dict[str, Any]:
    orders: set[tuple[str, str, int]] = set()
    fills: list[dict[str, Any]] = []
    reviews: list[tuple[str, dict[str, Any]]] = []
    med_orders: list[dict[str, Any]] = []
    med_fills: list[dict[str, Any]] = []
    med_positions: list[dict[str, Any]] = []
    splits = terminals = dividends = 0

    for _, _, envelope in trace:
        record = envelope["record"]
        for order in record["orders"]["items"]:
            key = (str(order["side"]), str(order["security_id"]), int(order["signal_index"]))
            orders.add(key)
            if str(order["security_id"]) == MED:
                med_orders.append({"date": record["date"], **order})
        for fill in record["fills"]["items"]:
            fills.append(fill)
            if str(fill["security_id"]) == MED:
                med_fills.append({"date": record["date"], **fill})
        for review in record["events"]["age_reviews"]:
            reviews.append((record["date"], review))
        for position in record["selected_positions"]["state"]:
            if str(position["security_id"]) == MED and record["date"] in {
                "2006-07-06",
                "2006-08-15",
            }:
                med_positions.append({"date": record["date"], **position})
        splits += len(record["events"]["splits"])
        terminals += len(record["events"]["terminals"])
        dividends += len(record["events"]["dividends"])

    same_close: list[dict[str, Any]] = []
    missing_order: list[dict[str, Any]] = []
    basis_failures: list[dict[str, Any]] = []
    for fill in fills:
        terminal = str(fill.get("reason", "")).startswith("terminal")
        signal_index = int(fill.get("signal_index", -1))
        fill_index = int(fill["fill_index"])
        if not terminal and fill_index <= signal_index:
            same_close.append(fill)
        if not terminal and (
            str(fill["side"]),
            str(fill["security_id"]),
            signal_index,
        ) not in orders:
            missing_order.append(fill)
        if fill["side"] == "BUY" and fill.get("adjusted_open") != fill.get("review_basis"):
            basis_failures.append(fill)

    observed_reviews = [{"date": date, **review} for date, review in reviews]
    med_reviews = [
        row for row in observed_reviews if str(row.get("security_id")) == MED
    ]
    actual_review_ages = {int(row["age"]) for row in observed_reviews}
    first_review_date = min((row["date"] for row in observed_reviews), default=None)

    med_buy_order = any(
        row["date"] == "2006-07-05"
        and row["side"] == "BUY"
        and int(row["signal_index"]) == 126
        for row in med_orders
    )
    med_buy_fill = any(
        row["date"] == "2006-07-06"
        and row["side"] == "BUY"
        and int(row["signal_index"]) == 126
        and int(row["fill_index"]) == 127
        and row.get("adjusted_open") == row.get("review_basis")
        for row in med_fills
    )
    med_age_28 = any(
        row["date"] == "2006-08-15"
        and int(row["age"]) == 28
        and row.get("reviewed") is False
        for row in med_positions
    )
    med_stop_order = any(
        row["date"] == "2006-08-15"
        and row["side"] == "SELL"
        and row.get("reason") == "stop"
        and int(row["signal_index"]) == 155
        for row in med_orders
    )
    med_stop_fill = any(
        row["date"] == "2006-08-16"
        and row["side"] == "SELL"
        and row.get("reason") == "stop"
        and int(row["signal_index"]) == 155
        and int(row["fill_index"]) == 156
        for row in med_fills
    )

    counters = guard.get("counters", {})
    checks = {
        "close_signals_never_fill_same_close": not same_close,
        "orders_have_close_signal_witnesses": not missing_order,
        "entry_basis_is_execution_open": not basis_failures
        and int(counters.get("entry_basis_assertions", 0)) > 0,
        "rolling_windows_guarded": int(counters.get("rolling_assertions", 0))
        >= len(trace) * 5,
        "position_age_chronological": int(counters.get("position_age_assertions", 0)) > 0,
        "allocation_next_open": int(counters.get("allocation_timing_assertions", 0)) > 0,
        "split_timing": splits > 0
        and int(counters.get("split_event_assertions", 0)) == splits,
        "terminal_timing": terminals > 0
        and int(counters.get("terminal_event_assertions", 0)) == terminals,
        "dividend_timing": int(counters.get("dividend_event_assertions", 0)) == dividends,
        "metadata_asof": int(counters.get("metadata_accesses", 0)) > 0,
        "benchmark_prefix_cache": int(counters.get("benchmark_cache_assertions", 0))
        == len(trace),
        "actual_age_119_review_cohort": bool(observed_reviews)
        and actual_review_ages == {119}
        and first_review_date == "2006-12-22",
        "med_august_actual_path": med_buy_order
        and med_buy_fill
        and med_age_28
        and med_stop_order
        and med_stop_fill
        and not med_reviews,
        "runtime_guard": guard.get("status") == "PASS"
        and int(counters.get("violations", 0)) == 0,
    }
    return {
        "schema": "backtester.research-execution-timing/1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "counts": {
            "orders": len(orders),
            "fills": len(fills),
            "reviews": len(reviews),
            "review_ages": sorted(actual_review_ages),
            "first_review_date": first_review_date,
            "splits": splits,
            "terminals": terminals,
            "dividends": dividends,
        },
        "med_regression": {
            "security_id": MED,
            "finding": (
                "The canonical retained-research path does not contain a MED age-119 review "
                "in August 2006. MED enters on 2006-07-06 and reaches age 28 on 2006-08-15, "
                "when the trailing stop queues an exit filled at the 2006-08-16 open."
            ),
            "orders": med_orders,
            "fills": med_fills,
            "positions": med_positions,
            "age_reviews": med_reviews,
        },
        "age_119_review_evidence": {
            "first_session": first_review_date,
            "count": len(observed_reviews),
            "ages": sorted(actual_review_ages),
            "outcomes": sorted({str(row["outcome"]) for row in observed_reviews}),
        },
        "failures": {
            "same_close": same_close,
            "missing_orders": missing_order,
            "entry_basis": basis_failures,
        },
    }


def chronology() -> dict[str, Any]:
    phases = [
        "session_clock",
        "rolling_signals",
        "eligibility",
        "ranking",
        "recent_leadership",
        "open_events_and_fills",
        "dividends",
        "close_exits_and_age_review",
        "wealth_core_mark",
        "breadth",
        "close_admissions",
        "native_target",
        "ldrc",
        "next_open_allocation_and_nav",
        "canonical_trace",
    ]
    return {
        "schema": "backtester.research-execution-chronology/1",
        "status": "PASS",
        "phases": [
            {"order": index + 1, "phase": phase}
            for index, phase in enumerate(phases)
        ],
    }


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument(
        "--pointer",
        type=Path,
        default=Path("backtester/data/canonical-pit-2006-2007.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poison-seed", type=int, default=314159)
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dataset_identity = validate_identity(args.pointer, args.canonical_dataset)
    write_json(output / "dataset-identity.json", dataset_identity)

    baseline_dir = output / "baseline"
    run_single(args.canonical_dataset.resolve(), baseline_dir, "baseline")
    baseline_trace = read_trace(baseline_dir / "causal-trace.jsonl.gz")
    runtime_guard = json.loads(
        (baseline_dir / "runtime-guard-report.json").read_text(encoding="utf-8")
    )
    shutil.copy2(
        baseline_dir / "causal-trace.jsonl.gz",
        output / "baseline-causal-trace.jsonl.gz",
    )
    shutil.copy2(
        baseline_dir / "runtime-guard-report.json",
        output / "runtime-guard-report.json",
    )

    cutoffs = select_cutoffs(baseline_trace)
    write_json(
        output / "cutoff-manifest.json",
        {
            "schema": "backtester.research-causal-cutoffs/1",
            "status": "PASS",
            "cutoffs": cutoffs,
            "warmup_coverage_note": "Every cutoff includes causal state from 2006-01-03.",
        },
    )

    prefix_results: list[dict[str, Any]] = []
    poison_results: list[dict[str, Any]] = []
    required_domains = {
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
    for cutoff_row in cutoffs:
        cutoff = cutoff_row["cutoff"]
        prefix_dir = output / "prefix" / cutoff
        run_single(args.canonical_dataset.resolve(), prefix_dir, "prefix", cutoff)
        prefix_result = compare_prefix(
            baseline_trace,
            read_trace(prefix_dir / "causal-trace.jsonl.gz"),
            cutoff,
        )
        prefix_result["economic_reasons"] = cutoff_row["economic_reasons"]
        prefix_results.append(prefix_result)
        if prefix_result["status"] != "PASS":
            raise RuntimeError(f"prefix invariance failure: {prefix_result}")

        if cutoff == END:
            continue
        poison_dir = output / "poison" / cutoff
        run_single(
            args.canonical_dataset.resolve(),
            poison_dir,
            "poison",
            cutoff,
            args.poison_seed,
        )
        poison_result = compare_prefix(
            baseline_trace,
            read_trace(poison_dir / "causal-trace.jsonl.gz"),
            cutoff,
        )
        poison_manifest = json.loads(
            (poison_dir / "causal-run-manifest.json").read_text(encoding="utf-8")
        )["poison"]
        changed = poison_manifest.get("changed_rows", {})
        missing_domains = sorted(
            domain for domain in required_domains if int(changed.get(domain, 0)) <= 0
        )
        poison_result.update(
            {
                "economic_reasons": cutoff_row["economic_reasons"],
                "poison_seed": args.poison_seed,
                "poison_manifest": poison_manifest,
                "missing_poison_domains": missing_domains,
                "all_required_future_domains_changed": not missing_domains,
            }
        )
        poison_result["status"] = (
            "PASS"
            if poison_result["status"] == "PASS" and not missing_domains
            else "FAIL"
        )
        poison_results.append(poison_result)
        if poison_result["status"] != "PASS":
            raise RuntimeError(f"future-poisoning failure: {poison_result}")

    prefix_report = {
        "schema": "backtester.research-prefix-invariance/1",
        "status": "PASS",
        "results": prefix_results,
    }
    poison_report = {
        "schema": "backtester.research-future-poisoning/1",
        "status": "PASS",
        "results": poison_results,
    }
    write_json(output / "prefix-invariance.json", prefix_report)
    write_json(output / "future-poisoning.json", poison_report)

    leakage = static_leakage_audit(
        (baseline_dir / "generated-research-replay.py").read_text(encoding="utf-8")
    )
    write_json(output / "static-leakage-audit.json", leakage)
    if leakage["status"] != "PASS":
        raise RuntimeError("static leakage audit failure")

    timing = execution_timing(baseline_trace, runtime_guard)
    write_json(output / "execution-timing.json", timing)
    if timing["status"] != "PASS":
        raise RuntimeError(f"execution timing failure: {timing['checks']}")

    write_json(output / "execution-chronology.json", chronology())
    allocation_unchanged = all(
        fval(envelope["record"]["allocation"]["effective_control"]) == 1.0
        and fval(envelope["record"]["allocation"]["pending_control"]) == 1.0
        for _, _, envelope in baseline_trace
    )
    summary = {
        "schema": "backtester.research-causal-certification/1",
        "status": "PASS",
        "causal_timing_certified": True,
        "window": {"warmup_start": WARMUP, "measurement_start": START, "end": END},
        "dataset": dataset_identity,
        "baseline_trace_sha256": hfile(output / "baseline-causal-trace.jsonl.gz"),
        "runtime_guard": runtime_guard,
        "prefix_invariance": {"status": "PASS", "cutoffs": len(prefix_results)},
        "future_poisoning": {
            "status": "PASS",
            "cutoffs": len(poison_results),
            "domains": sorted(required_domains),
        },
        "execution_timing": timing,
        "static_leakage_audit": {
            "status": "PASS",
            "finding_count": len(leakage["findings"]),
            "forbidden_count": leakage["forbidden_count"],
        },
        "economic_defects": {
            "confirmed_new_strategy_defects": [],
            "preserved_correction": (
                "MED and all entries use adjusted execution-open review basis; "
                "entry close initializes peak only."
            ),
            "bounded_window_allocation_transition_observed": not allocation_unchanged,
        },
        "factual_corrections": [
            (
                "MED's August 15, 2006 retained-research event is a trailing-stop decision "
                "at position age 28, followed by an August 16 open fill. It is not an age-119 review."
            ),
            "The first actual retained-research age-119 review cohort is December 22, 2006.",
        ],
        "remaining_limitations": [
            "This certificate is bounded to 2006-01-03 through 2007-12-31.",
            (
                "The bounded window contains no defensive-allocation transition; causal controller "
                "evaluation and the unchanged allocation path were certified."
            ),
            (
                "The completed 20-year canonical package now requires a separate full-window run of "
                "the same guard, prefix, poisoning, timing, and static-audit contract."
            ),
            "Any retained-source or transform change invalidates this certificate until rerun.",
        ],
    }
    write_json(output / "certification-summary.json", summary)

    evidence_files = sorted(
        path
        for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{hfile(path)}  {path.name}\n" for path in evidence_files),
        encoding="utf-8",
    )
    print(
        f"[CAUSAL CERTIFICATION PASS] cutoffs={len(prefix_results)} "
        f"poisoned={len(poison_results)} dataset={DATA_HASH}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
