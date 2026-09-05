#!/usr/bin/env python3
"""Frozen Research Champion replay with exact Production economics and PIT path closure telemetry.

This run is intentionally NOT a final PIT certificate. It produces the 5/10/15/20-year
Champion metrics on the canonical package while retaining every security/session boundary
needed to close the strategy-specific PIT corpus. Once that worklist is resolved, the same
frozen profile can be rerun through the formal certification gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester import run_research_champion_terminal_pit_20y as fixed

PROFILE = fixed.champion.PROFILE
PROFILE_SHA256 = fixed.champion.PROFILE_SHA256
EXPECTED_PROFILE_SHA256 = "1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26"
RUNTIME_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
STATUS = "PIT_NOT_CERTIFIED_PENDING_STRATEGY_PATH_CLOSURE"
MEASUREMENT_START = "2006-07-31"
END_SESSION = "2026-07-31"


def _once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install_exact_production_economics_and_path_audit(text: str) -> str:
    """Undo certification-only economic overlays and add read-only closure telemetry."""
    text = _once(
        text,
        "from collections import defaultdict\n",
        "from collections import defaultdict\nfrom backtester import research_champion_pit_closure as _closure\n",
        "closure audit import",
    )

    init_anchor = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    text = _once(
        text,
        init_anchor,
        init_anchor + "\n    _PATH=_closure.PathAudit(OUT)\n",
        "closure audit initialization",
    )

    # The 10% prior-20 ADV participation cap was added only by the research
    # certification overlay. It is absent from the pinned Production adapter and
    # therefore must not change frozen Champion economics.
    exit_guard = """                    if _research_capacity_guard(s.qty,_capacity_volumes.get(int(s.tid),()),security_id=str(sid[int(s.tid)]),session=ds,defer_excess=True) is None:
                        continue
"""
    entry_guard = """                    if _research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:
                        continue
"""
    text = _once(text, exit_guard, "", "remove non-Production exit capacity guard")
    text = _once(text, entry_guard, "", "remove non-Production entry capacity guard")

    # Restore the pinned Production/default Wealth Core dividend convention.
    text = _once(
        text,
        "book.receivables.append((gday+15,q*rawdiv))",
        "book.receivables.append((gday+1,q*rawdiv))",
        "restore one-session dividend settlement",
    )

    # Production carries the last trustworthy mark for book valuation and blocks
    # new admissions while equity is unresolved. The retained engine already has
    # exactly that behavior; remove the certification-only hard abort.
    strict_nav_abort = """            eq,unresolved=book.equity(clraw)
            if unresolved and date>=START:
                raise RuntimeError(f'financial-grade NAV unresolved on {ds}')
"""
    text = _once(
        text,
        strict_nav_abort,
        "            eq,unresolved=book.equity(clraw)\n",
        "restore Production unresolved-mark behavior",
    )

    # The pinned Production recent-leadership witness assigns zero contribution
    # when a selected name lacks the next close. Preserve exact authenticated
    # terminal consideration when available, otherwise use that frozen witness
    # convention and log the unresolved item for PIT closure.
    text = _once(
        text,
        "_lead_ret,_lead_source=_lead_return(",
        "_lead_ret,_lead_source=_closure.production_leadership_return(_lead_return,audit=_PATH,",
        "restore Production missing-leadership convention",
    )
    text = _once(
        text,
        "_lead_terminal_counts[_lead_source]+=1",
        "_lead_terminal_counts[_lead_source]=_lead_terminal_counts.get(_lead_source,0)+1",
        "leadership source counter",
    )

    # Correct the generated evidence labels so they describe the economics that
    # actually ran rather than the superseded certification overlay.
    text = _once(
        text,
        "'financial_grade_dividend_lag_sessions':15,",
        "'financial_grade_dividend_lag_sessions':1,",
        "dividend evidence label",
    )
    text = _once(
        text,
        "'financial_grade_requires_resolved_nav':True,",
        "'financial_grade_requires_resolved_nav':False,",
        "nav evidence label",
    )
    text = _once(
        text,
        "'financial_grade_missing_leadership_return_policy':'FAIL_CLOSED',",
        "'financial_grade_missing_leadership_return_policy':'PRODUCTION_ZERO_CONTRIBUTION_WITH_EXACT_TERMINAL_WHEN_AVAILABLE',",
        "leadership evidence label",
    )

    # Item 1 + 2 from the agreed closure plan:
    # 1) retain every security reaching an economically relevant Champion boundary;
    # 2) retain the conservative pre-classification candidate envelope, including
    #    every unknown security type that could alter rank geometry.
    path_anchor = "            shadow_dates.append(date); shadow_eq.append(eq); damaged_hist.append(dam_b)\n"
    path_observe = """            _PATH.observe_session(
                session=ds,tids=tids,sid=sid,tick=tick,metadata_fn=_metadata,
                base_elig=_base_elig,elig=elig,pool=pool,durable=durable,recsel=recsel,
                book=book,terminal_events=_lead_events)
"""
    text = _once(
        text,
        path_anchor,
        path_observe + path_anchor,
        "strategy path and candidate envelope telemetry",
    )

    forbidden = (
        "_research_capacity_guard(s.qty,",
        "_research_capacity_guard(s.pending_shares,",
        "gday+15,q*rawdiv",
        "financial-grade NAV unresolved",
    )
    present = [needle for needle in forbidden if needle in text]
    if present:
        raise RuntimeError(f"corrected Champion source still contains forbidden economics: {present}")
    required = (
        "book.receivables.append((gday+1,q*rawdiv))",
        "_closure.PathAudit(OUT)",
        "_PATH.observe_session(",
        "_closure.production_leadership_return(",
        "if ready and not unresolved and book.cash>0:",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"corrected Champion source missing required economics/telemetry: {missing}")

    compile(text, "<research-champion-pit-closure>", "exec")
    return text


def build_source(output: Path) -> str:
    if PROFILE_SHA256 != EXPECTED_PROFILE_SHA256:
        raise RuntimeError("frozen Champion profile identity changed")
    source = fixed._terminal_aware_source("fullpit", output)
    return install_exact_production_economics_and_path_audit(source)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _finalize_candidate_coverage(output: Path, summary: dict) -> tuple[dict, dict]:
    coverage = dict(summary.get("strict_candidate_security_type_coverage") or {})
    unknown = dict(summary.get("strict_candidate_security_type_unknown_breakdown") or {})
    if not coverage:
        raise RuntimeError("candidate/session coverage evidence missing")
    total = int(coverage.get("base_candidates", 0))
    known = int(coverage.get("known_classifications", 0))
    unknown_count = int(coverage.get("unknown_classifications", 0))
    coverage.update(
        known_fraction=(known / total if total else 1.0),
        complete=(unknown_count == 0),
        measurement_start=MEASUREMENT_START,
        end_session=END_SESSION,
    )
    _write_json(output / "candidate_session_coverage.json", coverage)
    _write_json(output / "candidate_session_unknown_breakdown.json", unknown)
    return coverage, unknown


def _window_metrics(metrics: pd.DataFrame) -> list[dict]:
    rows = []
    for row in metrics.to_dict(orient="records"):
        window = str(row.get("window_years"))
        if window not in {"5", "10", "15", "20", "max"}:
            continue
        rows.append(row)
    available = {str(row.get("window_years")) for row in rows}
    missing = {"5", "10", "15", "20"} - available
    if missing:
        raise RuntimeError(f"postprocess did not emit required backtest windows: {sorted(missing)}")
    return rows


def _report(output: Path, metrics: pd.DataFrame, manifest: dict) -> None:
    rows = _window_metrics(metrics)
    lines = [
        "# Research Champion — corrected economics / PIT closure replay",
        "",
        f"Status: **{STATUS}**",
        f"Profile: `{PROFILE}`",
        f"Profile SHA-256: `{PROFILE_SHA256}`",
        "",
        "This is the frozen Champion replay with the non-Production capacity overlay removed, "
        "Production's one-session dividend settlement restored, Production's unresolved-mark "
        "admission block restored, and strategy-path/candidate-envelope evidence retained.",
        "",
        "## 5 / 10 / 15 / 20-year metrics",
        "",
        "| Window | Series | CAGR | Max drawdown | Ending multiple |",
        "|---:|---|---:|---:|---:|",
    ]

    def f(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")

    for row in rows:
        lines.append(
            f"| {row.get('window_years')} | {row.get('variant')} | "
            f"{f(row.get('cagr')):.2%} | {f(row.get('max_drawdown')):.2%} | "
            f"{f(row.get('ending_multiple')):.3f}x |"
        )
    counts = manifest.get("counts") or {}
    lines += [
        "",
        "## PIT closure worklist",
        "",
        f"- Securities touching base candidate boundary: {int(counts.get('securities_touching_base_candidate', 0)):,}",
        f"- Unknown-type potential displacers: {int(counts.get('unknown_type_potential_displacers', 0)):,}",
        f"- Eligible ranking inputs: {int(counts.get('eligible_ranking_inputs', 0)):,}",
        f"- Durable-ranked securities: {int(counts.get('durable_ranked', 0)):,}",
        f"- Recent-leadership securities: {int(counts.get('recent_leadership', 0)):,}",
        f"- Pending-order securities: {int(counts.get('pending', 0)):,}",
        f"- Held securities: {int(counts.get('held', 0)):,}",
        f"- Incomplete terminal securities touching path: {int(counts.get('incomplete_terminal', 0)):,}",
        "",
        "The candidate envelope is deliberately conservative: every row that passed "
        "price/volume/history/signal prerequisites before security-type classification is "
        "retained. Unknown types are treated as potential displacers until resolved.",
        "",
        "Formal PIT certification remains closed until the strategy-path worklist is resolved "
        "and the exact Champion causality/execution proof passes.",
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(output: Path) -> int:
    if os.environ.get("PIT_OFFICIAL_BACKTEST", "0") not in ("", "0"):
        raise RuntimeError("closure discovery replay must not present itself as an official certificate")
    dataset = os.environ.get("CANONICAL_PIT_DATASET")
    if not dataset:
        raise RuntimeError("authenticated canonical PIT dataset is required")

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = build_source(output)
    generated = output / "generated-replay.py"
    generated.write_text(source, encoding="utf-8")
    generated_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()

    dataset_manifest = json.loads((Path(dataset) / "manifest.json").read_text(encoding="utf-8"))
    identity = {
        "schema": "backtester.research-champion-pit-closure-replay/1",
        "status": STATUS,
        "certification_status": "NOT_CERTIFIED",
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA256,
        "runtime_main_sha": RUNTIME_MAIN_SHA,
        "source_sha": os.environ.get("GITHUB_SHA"),
        "generated_source_sha256": generated_sha,
        "canonical_dataset_hash": dataset_manifest.get("dataset_hash"),
        "measurement_window": dataset_manifest.get("window"),
        "economics_contract": {
            "initial_cash": 100_000_000.0,
            "slots": 25,
            "entry_weight": 0.04,
            "transaction_cost_fraction": 0.001,
            "capacity_participation_cap": None,
            "execution": "next positive-volume raw open",
            "dividend_settlement_lag_sessions": 1,
            "unresolved_held_mark": "carry last trustworthy raw mark and block new admissions while unresolved",
            "missing_recent_leadership_close": "zero contribution, matching pinned Production witness",
            "terminal": "authenticated exact terms when complete; existing Production C1 lifecycle otherwise",
        },
    }
    _write_json(output / "pit-closure-replay-identity.json", identity)

    env = dict(os.environ, RESEARCH_REPLAY_MODE="fullpit")
    print(
        f"[CHAMPION PIT CLOSURE] profile={PROFILE} profile_sha256={PROFILE_SHA256} "
        "capacity_cap=NONE dividend_lag=1",
        flush=True,
    )
    rc = subprocess.run([sys.executable, str(generated)], env=env).returncode
    if rc:
        _write_json(output / "run-status.json", {**identity, "completion_status": "FAILED", "exit_code": rc})
        return rc

    fixed.champion.strict20.old.postprocess("fullpit", output)

    daily = pd.read_csv(output / "daily.csv.gz", compression="gzip")
    if str(daily["date"].iloc[-1]) != END_SESSION:
        raise RuntimeError("Champion replay did not reach the full end session")
    nav_gap = (daily["research_nav"].astype(float) - daily["A_nav"].astype(float)).abs().max()
    alloc_gap = (daily["research_allocation"].astype(float) - daily["A_allocation"].astype(float)).abs().max()
    if not (float(nav_gap) <= 1e-12 and float(alloc_gap) <= 1e-12):
        raise RuntimeError(f"Champion promotion parity failed nav_gap={nav_gap} alloc_gap={alloc_gap}")

    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    coverage, unknown = _finalize_candidate_coverage(output, summary)

    manifest_path = output / "strategy-path-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generated_source_sha256"] = generated_sha
    manifest["canonical_dataset_hash"] = dataset_manifest.get("dataset_hash")
    manifest["source_sha"] = os.environ.get("GITHUB_SHA")
    manifest["economics_contract"] = identity["economics_contract"]
    manifest["certification_status"] = "NOT_CERTIFIED"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    metrics_path = output / "metrics.csv"
    metrics = pd.read_csv(metrics_path)
    _window_metrics(metrics)
    metrics["certification_status"] = "NOT_CERTIFIED"
    metrics["profile"] = PROFILE
    metrics.to_csv(metrics_path, index=False)

    daily["certification_status"] = "NOT_CERTIFIED"
    daily["profile"] = PROFILE
    daily.to_csv(
        output / "daily.csv.gz",
        index=False,
        compression={"method": "gzip", "mtime": 0},
    )

    summary.update(identity)
    summary.update(
        completion_status="COMPLETED",
        mode="champion_pit_path_closure",
        promotion_nav_gap=float(nav_gap),
        promotion_allocation_gap=float(alloc_gap),
        candidate_session_security_type_coverage=coverage,
        candidate_session_security_type_unknown_breakdown=unknown,
        strategy_path_closure_manifest=manifest,
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_json(output / "run-status.json", {**identity, "completion_status": "COMPLETED"})

    _report(output, metrics, manifest)

    evidence_files = [
        output / "daily.csv.gz",
        metrics_path,
        summary_path,
        output / "REPORT.md",
        output / "candidate_session_coverage.json",
        output / "candidate_session_unknown_breakdown.json",
        output / "strategy-path-session-ledger.jsonl.gz",
        output / "strategy-path-events.jsonl.gz",
        output / "strategy-path-worklist.csv",
        output / "candidate-envelope-worklist.csv",
        manifest_path,
        output / "pit-closure-replay-identity.json",
        output / "run-status.json",
        generated,
    ]
    session_hash = output / "canonical_input_session_hashes.csv"
    if session_hash.exists():
        evidence_files.append(session_hash)
    sums = output / "SHA256SUMS.txt"
    sums.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in evidence_files),
        encoding="utf-8",
    )

    print(
        f"[PIT CLOSURE WORKLIST] required={manifest.get('counts',{}).get('required_for_strategy_certificate',0)} "
        f"unknown_displacers={manifest.get('counts',{}).get('unknown_type_potential_displacers',0)}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("champion-pit-closure-results"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        source = build_source(args.output)
        print(
            f"[SELFTEST PASS] profile={PROFILE} profile_sha256={PROFILE_SHA256} "
            f"generated_sha256={hashlib.sha256(source.encode()).hexdigest()}",
            flush=True,
        )
        return 0
    return run(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
