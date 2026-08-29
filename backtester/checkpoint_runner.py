#!/usr/bin/env python3
"""Exact checkpoint/resume execution for the frozen chronological research replay.

The module reuses the experiment module's data loaders and economic helpers while
persisting only canonical production state plus the small overlay-account state
and deterministic output prefix. On resume the raw Sharadar stream is normalized
again from the beginning so normalization/reconciliation state and feed-anchor
bookkeeping are reconstructed from frozen source data, then production execution
continues strictly after the checkpointed session.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
from collections import defaultdict
from pathlib import Path
import sys
from typing import Mapping, Optional

import pandas as pd


SCHEMA = "backtester.replay-checkpoint/1"
FULL_END_SESSION = "2026-07-31"


def _canonical_json(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _hash_value(value) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _account_to_dict(account) -> dict:
    return {
        "name": str(account.name),
        "nav": float(account.nav),
        "effective": float(account.effective),
        "pending": float(account.pending),
        "initialized": bool(account.initialized),
        "transition_cost": float(account.transition_cost),
        "transitions": int(account.transitions),
    }


def _account_from_dict(cls, raw: Mapping):
    expected = {
        "name", "nav", "effective", "pending", "initialized",
        "transition_cost", "transitions",
    }
    if set(raw) != expected:
        raise RuntimeError(
            f"checkpoint overlay account fields differ: {sorted(set(raw) ^ expected)}")
    account = cls(str(raw["name"]))
    account.nav = float(raw["nav"])
    account.effective = float(raw["effective"])
    account.pending = float(raw["pending"])
    account.initialized = bool(raw["initialized"])
    account.transition_cost = float(raw["transition_cost"])
    account.transitions = int(raw["transitions"])
    if (not math.isfinite(account.nav) or account.nav <= 0
            or not 0 <= account.effective <= 1
            or not 0 <= account.pending <= 1
            or not math.isfinite(account.transition_cost)
            or account.transition_cost < 0
            or account.transitions < 0):
        raise RuntimeError(f"invalid checkpoint overlay account {account.name}")
    return account


def _checkpoint_extra_identity(runner) -> dict:
    hook = getattr(runner, "CHECKPOINT_EXTRA_IDENTITY", None)
    if hook is None:
        return {}
    value = hook() if callable(hook) else hook
    if not isinstance(value, Mapping):
        raise RuntimeError("CHECKPOINT_EXTRA_IDENTITY must be a mapping/callable mapping")
    json.dumps(value, sort_keys=True, allow_nan=False)
    return dict(value)


def _checkpoint_static_inputs(observed_inputs: Mapping[str, Mapping]) -> dict:
    # MANIFEST.csv is itself the authority for every SEP source hash. Per-year
    # SEP files are independently re-hashed by raw_sep_rows as resume fast-forward
    # reaches them, so the checkpoint binds the immutable manifests and all other
    # non-SEP frozen inputs here.
    return {
        str(name): dict(value)
        for name, value in sorted(observed_inputs.items())
        if not (str(name).startswith("sharadar/SHARADAR_SEP_")
                and str(name).endswith(".gz"))
    }


def _write_checkpoint(
    path: Path,
    *,
    runner,
    sessions,
    checkpoint_session: str,
    expected_pointer: int,
    state_a,
    state_b,
    accounts,
    prior_core_close: Optional[float],
    daily_rows: list[dict],
    observed_inputs: Mapping[str, Mapping],
    strategy_identity: Mapping,
) -> str:
    if expected_pointer <= 0 or sessions[expected_pointer - 1] != checkpoint_session:
        raise RuntimeError("checkpoint session/pointer mismatch")
    state_a_dict = state_a.to_dict()
    state_b_dict = state_b.to_dict()
    prefix_hash = _hash_value(daily_rows)
    payload = {
        "experiment": str(runner.EXPERIMENT_ID),
        "main_sha": str(runner.EXPECTED_MAIN_SHA),
        "backtester_sha": str(os.environ.get("BACKTESTER_BRANCH_SHA") or ""),
        "chain_start": str(runner.CHAIN_START),
        "configured_end_session": str(runner.END_SESSION),
        "checkpoint_session": str(checkpoint_session),
        "next_session": (
            str(sessions[expected_pointer])
            if expected_pointer < len(sessions) else None
        ),
        "expected_pointer": int(expected_pointer),
        "state_a": state_a_dict,
        "state_b": state_b_dict,
        "state_hash_a": str(state_a.state_hash),
        "state_hash_b": str(state_b.state_hash),
        "accounts": {
            name: _account_to_dict(account)
            for name, account in sorted(accounts.items())
        },
        "prior_core_close": (
            None if prior_core_close is None else float(prior_core_close)
        ),
        "daily_rows": list(daily_rows),
        "daily_prefix_sha256": prefix_hash,
        "static_input_files": _checkpoint_static_inputs(observed_inputs),
        "strategy_identity": dict(strategy_identity),
        "extra_identity": _checkpoint_extra_identity(runner),
    }
    envelope = {
        "schema": SCHEMA,
        "payload_sha256": _hash_value(payload),
        "payload": payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(envelope, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".SHA256").write_text(
        f"{digest}  {path.name}\n", encoding="utf-8")
    return digest


def _load_checkpoint(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise RuntimeError(f"unsupported replay checkpoint schema: {raw.get('schema')!r}")
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("replay checkpoint payload is missing")
    expected = str(raw.get("payload_sha256") or "")
    observed = _hash_value(payload)
    if expected != observed:
        raise RuntimeError(
            f"replay checkpoint payload hash mismatch: {observed} != {expected}")
    sidecar = path.with_name(path.name + ".SHA256")
    if sidecar.exists():
        row = sidecar.read_text(encoding="utf-8").strip().split()
        if len(row) != 2 or row[1].lstrip("*") != path.name:
            raise RuntimeError("malformed replay checkpoint SHA256 sidecar")
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if row[0] != file_digest:
            raise RuntimeError("replay checkpoint file SHA256 mismatch")
    return payload


def _validate_resume_contract(
    payload: Mapping,
    *,
    runner,
    sessions,
    observed_inputs,
    strategy_identity,
) -> None:
    checks = {
        "experiment": str(runner.EXPERIMENT_ID),
        "main_sha": str(runner.EXPECTED_MAIN_SHA),
        "backtester_sha": str(os.environ.get("BACKTESTER_BRANCH_SHA") or ""),
        "chain_start": str(runner.CHAIN_START),
        "configured_end_session": str(runner.END_SESSION),
    }
    for key, expected in checks.items():
        if str(payload.get(key) or "") != expected:
            raise RuntimeError(
                f"checkpoint {key} mismatch: {payload.get(key)!r} != {expected!r}")
    if dict(payload.get("strategy_identity") or {}) != dict(strategy_identity):
        raise RuntimeError("checkpoint strategy identity differs from current frozen strategy")
    if dict(payload.get("extra_identity") or {}) != _checkpoint_extra_identity(runner):
        raise RuntimeError("checkpoint terminal/split identity differs from current frozen inputs")
    if dict(payload.get("static_input_files") or {}) != _checkpoint_static_inputs(observed_inputs):
        raise RuntimeError("checkpoint static frozen-input hashes differ from current inputs")
    pointer = int(payload.get("expected_pointer", -1))
    session = str(payload.get("checkpoint_session") or "")
    if pointer <= 0 or pointer > len(sessions) or sessions[pointer - 1] != session:
        raise RuntimeError("checkpoint session pointer is invalid for current session axis")
    expected_next = str(sessions[pointer]) if pointer < len(sessions) else None
    if payload.get("next_session") != expected_next:
        raise RuntimeError("checkpoint next-session witness differs from current session axis")
    rows = payload.get("daily_rows")
    if not isinstance(rows, list) or len(rows) != pointer:
        raise RuntimeError("checkpoint daily prefix length differs from session pointer")
    if not rows or str(rows[-1].get("date")) != session:
        raise RuntimeError("checkpoint daily prefix does not end at checkpoint session")
    if str(payload.get("daily_prefix_sha256") or "") != _hash_value(rows):
        raise RuntimeError("checkpoint daily output prefix hash mismatch")


def _update_raw_bookkeeping(
    bars,
    *,
    idx: int,
    prior_split_factor,
    seen_count,
    prior_signal_close,
    latest_ticker_by_sid,
    positive,
) -> None:
    for bar in bars:
        sid = str(bar.security_id)
        current_factor = float(prior_split_factor.get(sid, 1.0)) * float(bar.split_ratio)
        if positive(bar.raw_close):
            signal_close = float(bar.raw_close) * current_factor
            prior_signal_close[sid] = (idx, signal_close)
        prior_split_factor[sid] = current_factor
        seen_count[sid] += 1
        latest_ticker_by_sid[sid] = str(bar.ticker)


def run(runner) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-root", type=Path, default=Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")))
    ap.add_argument("--main-root", type=Path, default=Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")))
    ap.add_argument("--output", type=Path, default=Path("backtester-results/sector-abc"))
    ap.add_argument("--resume-checkpoint", type=Path)
    ap.add_argument("--checkpoint-out", type=Path)
    ap.add_argument("--stop-after-session")
    args = ap.parse_args()
    if args.stop_after_session and args.checkpoint_out is None:
        raise RuntimeError("--stop-after-session requires --checkpoint-out")
    if args.stop_after_session and not (
            str(runner.CHAIN_START) <= str(args.stop_after_session) < str(runner.END_SESSION)):
        raise RuntimeError("checkpoint stop session must be inside replay and before configured end")

    lab = args.lab_root.resolve()
    main_root = args.main_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    from sentinel.breadth import classifier as breadth
    import sentinel.core.production as production
    from sentinel.controller.concordance_parent import load as load_concordance_parent
    from sentinel.controller.machine import Controller
    from sentinel.core.decision import runtime_strategy_identity
    from sentinel.core.production import PublishedSession, SessionState
    from sentinel.feed.actions_map import dividends_from_actions, split_ratios_from_actions
    from sentinel.feed.domains import (
        NormalisationReport, assert_identity_domain, assert_raw_price_domain,
        normalise_sep_rows,
    )
    from sentinel.feed.universe import parse_related_tickers
    from sentinel.core.terminal import ActionSide, TERMINAL_ACTION_SIDES, terminal_from_action
    from stock_strategy_shared.terminal_coalescing import TerminalCandidate, coalesce_terminal_terms
    from stock_strategy_shared.split_reconciliation import SPLIT_UNRESOLVED
    from stock_strategy_shared.wealth_core.feed import SecurityMeta

    imported = Path(production.__file__).resolve()
    if main_root not in imported.parents:
        raise RuntimeError(f"production module did not load from exact main checkout: {imported}")
    actual_main_sha = os.environ.get("BACKTESTER_MAIN_SHA", "")
    if actual_main_sha != runner.EXPECTED_MAIN_SHA:
        raise RuntimeError(
            f"main SHA mismatch: expected {runner.EXPECTED_MAIN_SHA}, got {actual_main_sha}")

    main_api = {
        "PublishedSession": PublishedSession,
        "SessionState": SessionState,
        "SecurityMeta": SecurityMeta,
        "parse_related_tickers": parse_related_tickers,
        "split_ratios_from_actions": split_ratios_from_actions,
        "dividends_from_actions": dividends_from_actions,
        "ActionSide": ActionSide,
        "TERMINAL_ACTION_SIDES": TERMINAL_ACTION_SIDES,
        "terminal_from_action": terminal_from_action,
        "TerminalCandidate": TerminalCandidate,
        "coalesce_terminal_terms": coalesce_terminal_terms,
        "FeedAnchor": production.FeedAnchor,
    }

    runner.print(f"[RUN] experiment={runner.EXPERIMENT_ID}", flush=True)
    runner.print(f"[RUN] exact main={runner.EXPECTED_MAIN_SHA}", flush=True)
    runner.print("[RUN] checkpoint-capable fresh chronological A/B replay; no prerecorded decisions", flush=True)

    observed_inputs: dict[str, dict] = {}
    phase1_manifest_path = lab / "PIT input data" / "MANIFEST.csv"
    phase1_manifest = runner.load_phase1_manifest(phase1_manifest_path)
    observed_inputs["PIT input data/MANIFEST.csv"] = {
        "sha256": runner.sha256_file(phase1_manifest_path),
        "bytes": phase1_manifest_path.stat().st_size,
    }

    actions_path = lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
    action_manifest = phase1_manifest.get(actions_path.name)
    if action_manifest is None or runner.sha256_file(actions_path) != action_manifest["sha256"]:
        raise RuntimeError("PIT ACTIONS hash does not match Phase-1 manifest")
    observed_inputs["PIT input data/ACTIONS_PIT_ONLY.csv.gz"] = {
        "sha256": action_manifest["sha256"], "bytes": actions_path.stat().st_size}

    sfp_path = lab / "PIT input data" / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
    price_manifest_path = lab / "PIT input data" / "PRICE_RECONSTRUCTION_MANIFEST.csv"
    with price_manifest_path.open("r", encoding="utf-8", newline="") as f:
        price_manifest = {row["file"]: row for row in csv.DictReader(f)}
    sfp_manifest = price_manifest.get(sfp_path.name)
    if sfp_manifest is None or runner.sha256_file(sfp_path) != sfp_manifest["sha256"]:
        raise RuntimeError("SFP factor hash does not match price manifest")
    observed_inputs["PIT input data/PRICE_RECONSTRUCTION_MANIFEST.csv"] = {
        "sha256": runner.sha256_file(price_manifest_path), "bytes": price_manifest_path.stat().st_size}
    observed_inputs["PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"] = {
        "sha256": sfp_manifest["sha256"], "bytes": sfp_path.stat().st_size}

    tickers_path = lab / "sharadar" / "SHARADAR_TICKERS.zip"
    observed_inputs["sharadar/SHARADAR_TICKERS.zip"] = {
        "sha256": runner.sha256_file(tickers_path), "bytes": tickers_path.stat().st_size}

    evidence_root = lab / "research" / "sentinel-fastgate" / "pit-evidence"
    generated = evidence_root / "generated"
    issuer_sums = runner.parse_checksum_file(generated / "SHA256SUMS.txt")
    sic_sums = runner.parse_checksum_file(generated / "SEC_SIC_SHA256SUMS.txt")
    cik_path = generated / "sec_cik_change_events.csv.gz"
    sic_path = generated / "sec_sic_submissions.csv.gz"
    for path, expected in (
        (cik_path, issuer_sums.get(cik_path.name)),
        (sic_path, sic_sums.get(sic_path.name)),
    ):
        if expected is None or runner.sha256_file(path) != expected:
            raise RuntimeError(f"PIT evidence hash mismatch: {path.name}")
        observed_inputs[str(path.relative_to(lab))] = {
            "sha256": expected, "bytes": path.stat().st_size}
    ff12_path = evidence_root / "ff12_sic_definition.txt"
    observed_inputs[str(ff12_path.relative_to(lab))] = {
        "sha256": runner.sha256_file(ff12_path), "bytes": ff12_path.stat().st_size}

    sessions, spy_level, spy_return, bil_factors = runner.build_sfp_levels(sfp_path)
    action_rows, authoritative_splits, action_maps = runner.load_actions(actions_path, sessions, main_api)
    dividends = action_maps["dividends"]
    terminal_by_session = action_maps["terminal"]
    meta, a_sectors, resolver, sid_to_ticker = runner.load_current_metadata(tickers_path, main_api)
    ff12 = runner.PITFF12(cik_path, sic_path, sid_to_ticker)
    controller_config = load_concordance_parent()
    strategy_identity = runtime_strategy_identity(controller_config, concordance=True)

    resume_payload = None
    if args.resume_checkpoint is not None:
        resume_payload = _load_checkpoint(args.resume_checkpoint.resolve())
        _validate_resume_contract(
            resume_payload,
            runner=runner,
            sessions=sessions,
            observed_inputs=observed_inputs,
            strategy_identity=strategy_identity,
        )
        state_a = SessionState.from_dict(resume_payload["state_a"])
        state_b = SessionState.from_dict(resume_payload["state_b"])
        if state_a.state_hash != str(resume_payload["state_hash_a"]):
            raise RuntimeError("checkpoint A production-state hash failed after restore")
        if state_b.state_hash != str(resume_payload["state_hash_b"]):
            raise RuntimeError("checkpoint B production-state hash failed after restore")
        runner.state_wc_parity(state_a, state_b, str(resume_payload["checkpoint_session"]))
        accounts = {
            name: _account_from_dict(runner.OverlayAccount, raw)
            for name, raw in sorted((resume_payload.get("accounts") or {}).items())
        }
        if set(accounts) != {"A", "B"}:
            raise RuntimeError("checkpoint does not contain exactly A/B overlay accounts")
        prior_core_close = resume_payload.get("prior_core_close")
        prior_core_close = None if prior_core_close is None else float(prior_core_close)
        daily_rows = list(resume_payload["daily_rows"])
        resume_pointer = int(resume_payload["expected_pointer"])
        hook = getattr(runner, "CHECKPOINT_ON_RESUME", None)
        if callable(hook):
            hook(resume_payload, accounts)
        runner.print(
            f"[CHECKPOINT] restored session={resume_payload['checkpoint_session']} "
            f"next={resume_payload['next_session']} sessions={resume_pointer}",
            flush=True,
        )
    else:
        state_a = SessionState.fresh(
            starting_cash=runner.STARTING_CASH, controller=Controller(controller_config),
            strategy_identity=strategy_identity)
        state_b = SessionState.fresh(
            starting_cash=runner.STARTING_CASH, controller=Controller(controller_config),
            strategy_identity=strategy_identity)
        accounts = {name: runner.OverlayAccount(name) for name in ("A", "B")}
        prior_core_close = None
        daily_rows = []
        resume_pointer = 0

    prior_split_factor: dict[str, float] = defaultdict(lambda: 1.0)
    seen_count: dict[str, int] = defaultdict(int)
    prior_signal_close: dict[str, tuple[int, float]] = {}
    latest_ticker_by_sid: dict[str, str] = {}
    normalization = NormalisationReport()

    def resolve_identity(ticker, session):
        return resolver.resolve(str(ticker), str(session))

    raw_stream = runner.raw_sep_rows(
        lab / "sharadar", phase1_manifest, runner.END_SESSION, observed_inputs)
    normalized = normalise_sep_rows(
        raw_stream, resolve_identity=resolve_identity,
        dividends=dividends, authoritative_splits=authoritative_splits,
        report=normalization)

    expected_pointer = 0
    resumed_execution_started = resume_pointer == 0
    original_session_breadth = production.session_breadth
    try:
        for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
            if session < runner.CHAIN_START:
                continue
            if session > runner.END_SESSION:
                break
            while expected_pointer < len(sessions) and sessions[expected_pointer] < session:
                raise RuntimeError(
                    f"normalized SEP omitted XNYS/SPY session {sessions[expected_pointer]}")
            if expected_pointer >= len(sessions) or sessions[expected_pointer] != session:
                raise RuntimeError(f"normalized SEP session {session} is outside SPY session axis")
            idx = expected_pointer
            expected_pointer += 1
            bars = [row.vendor for row in group_iter]
            if not bars:
                raise RuntimeError(f"no normalized bars for {session}")

            if idx < resume_pointer:
                _update_raw_bookkeeping(
                    bars,
                    idx=idx,
                    prior_split_factor=prior_split_factor,
                    seen_count=seen_count,
                    prior_signal_close=prior_signal_close,
                    latest_ticker_by_sid=latest_ticker_by_sid,
                    positive=runner.positive,
                )
                if idx + 1 == resume_pointer:
                    if session != str(resume_payload["checkpoint_session"]):
                        raise RuntimeError("resume fast-forward ended on wrong session")
                    resumed_execution_started = True
                    runner.print(
                        f"[CHECKPOINT] deterministic input fast-forward complete at {session}",
                        flush=True,
                    )
                continue

            if not resumed_execution_started:
                raise RuntimeError("resume execution started before checkpoint fast-forward completed")

            priced_tickers = {bar.ticker.upper() for bar in bars}
            terminals = runner.build_terminal_events(
                session, terminal_by_session.get(session, ()), priced_tickers,
                resolver, main_api)
            anchors_a = runner.build_anchor_map(
                state_a, bars, meta, prior_split_factor, seen_count, main_api)
            anchors_b = runner.build_anchor_map(
                state_b, bars, meta, prior_split_factor, seen_count, main_api)
            if anchors_a != anchors_b:
                raise RuntimeError(f"A/B feed-anchor sets diverged at {session}")

            tail_start = max(0, idx - 20)
            spy_sessions = sessions[tail_start:idx+1]
            spy_closes = [spy_level[s] for s in spy_sessions]
            common = dict(
                session=session, data_version=1, bars=bars, meta=meta,
                spy_closeadj=spy_closes, spy_sessions=spy_sessions,
                spy_expected_sessions=spy_sessions, terminal_events=terminals,
                feed_anchors=anchors_a,
            )
            pub_a = PublishedSession(sectors=a_sectors, **common)
            causal_ticker_by_sid = dict(latest_ticker_by_sid)
            causal_ticker_by_sid.update(
                {str(bar.security_id): str(bar.ticker) for bar in bars})
            pub_b = PublishedSession(
                sectors=runner.FF12SectorMap(
                    ff12, session, causal_ticker_by_sid, meta), **common)
            state_a = production.advance_state(
                state_a, pub_a, controller_config=controller_config,
                strategy_identity=strategy_identity)
            state_b = production.advance_state(
                state_b, pub_b, controller_config=controller_config,
                strategy_identity=strategy_identity)
            runner.state_wc_parity(state_a, state_b, session)
            core_open, core_close = runner.wealth_equities(state_a)
            bil_gap, bil_intraday = bil_factors.get(session, (1.0, 1.0))
            navs = {}
            targets = {
                "A": runner.target_allocation(state_a),
                "B": runner.target_allocation(state_b),
            }
            for name, account in accounts.items():
                navs[name] = account.step(
                    core_open, core_close, prior_core_close,
                    bil_gap, bil_intraday, targets[name])

            ev_a = state_a.last_evidence or {}
            ev_b = state_b.last_evidence or {}
            ob_a = ev_a.get("observation") or {}
            ob_b = ev_b.get("observation") or {}
            daily_rows.append({
                "date": session,
                "A_nav": navs["A"], "B_nav": navs["B"],
                "SPY_level": spy_level[session],
                "wealth_core_equity": core_close,
                "A_allocation": targets["A"], "B_allocation": targets["B"],
                "A_native": (state_a.last_decision or {}).get("native_target_core_exposure"),
                "B_native": (state_b.last_decision or {}).get("native_target_core_exposure"),
                "A_damaged": ob_a.get("damaged_breadth"),
                "B_damaged": ob_b.get("damaged_breadth"),
                "green": ob_a.get("green_breadth"),
            })

            _update_raw_bookkeeping(
                bars,
                idx=idx,
                prior_split_factor=prior_split_factor,
                seen_count=seen_count,
                prior_signal_close=prior_signal_close,
                latest_ticker_by_sid=latest_ticker_by_sid,
                positive=runner.positive,
            )
            prior_core_close = core_close

            if idx % 252 == 0 or session == runner.END_SESSION:
                runner.print(
                    f"[RUN] {session} sessions={idx+1:,} "
                    f"A={accounts['A'].nav:.6f} B={accounts['B'].nav:.6f}", flush=True)

            if args.stop_after_session and session == str(args.stop_after_session):
                digest = _write_checkpoint(
                    args.checkpoint_out.resolve(),
                    runner=runner,
                    sessions=sessions,
                    checkpoint_session=session,
                    expected_pointer=expected_pointer,
                    state_a=state_a,
                    state_b=state_b,
                    accounts=accounts,
                    prior_core_close=prior_core_close,
                    daily_rows=daily_rows,
                    observed_inputs=observed_inputs,
                    strategy_identity=strategy_identity,
                )
                runner.print(
                    f"[CHECKPOINT] wrote {args.checkpoint_out} sha256={digest} "
                    f"session={session} next={sessions[expected_pointer]}",
                    flush=True,
                )
                return 0
    finally:
        production.session_breadth = original_session_breadth

    if expected_pointer != len(sessions):
        raise RuntimeError(
            f"replay ended before SPY session axis: processed={expected_pointer} expected={len(sessions)}")

    assert_raw_price_domain(normalization)
    bad_identity = []
    for session in sessions:
        coverage = assert_identity_domain(normalization, session)
        if coverage is not None and coverage < 1.0:
            bad_identity.append((session, coverage))
    unresolved_splits = [
        {"ticker": key[0], "session": key[1], **value}
        for key, value in normalization.split_dispositions.items()
        if value.get("disposition") == SPLIT_UNRESOLVED
    ]
    ignore_split_audit = (
        os.environ.get("BACKTESTER_EQUIV_IGNORE_FINAL_SPLIT_AUDIT") == "1"
        and str(runner.END_SESSION) < FULL_END_SESSION
    )
    if unresolved_splits and not ignore_split_audit:
        raise RuntimeError(
            f"current-main split reconciliation left {len(unresolved_splits)} unresolved event(s): "
            f"{unresolved_splits[:5]}")
    if unresolved_splits and ignore_split_audit:
        runner.print(
            f"[EQUIV] bounded final split audit ignored for {len(unresolved_splits)} event(s); "
            "session economics unchanged",
            flush=True,
        )

    daily = pd.DataFrame(daily_rows)
    if daily.empty or daily.iloc[-1]["date"] != runner.END_SESSION:
        raise RuntimeError("fresh replay did not reach requested end session")
    metrics_rows = []
    summary_metrics = {}
    for years, start in sorted(runner.MEASUREMENT_WINDOWS.items()):
        summary_metrics[str(years)] = {}
        for label, column in (("A", "A_nav"), ("B", "B_nav"), ("SPY", "SPY_level")):
            block = runner.metric_block(daily, column, start, years)
            summary_metrics[str(years)][label] = block
            metrics_rows.append({
                "window_years": years, "variant": label,
                "start": block["start"], "end": block["end"],
                "sessions": block["sessions"],
                "cagr": block["cagr"], "sharpe": block["sharpe"],
                "max_drawdown": block["max_drawdown"],
                "ending_multiple": block["ending_multiple"],
            })

    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0})
    pd.DataFrame(metrics_rows).to_csv(metrics_path, index=False)

    summary = {
        "experiment": runner.EXPERIMENT_ID,
        "status": "PASS",
        "main_sha": runner.EXPECTED_MAIN_SHA,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "chain_start": runner.CHAIN_START,
        "end_session": runner.END_SESSION,
        "fresh_chronological_replay": True,
        "prerecorded_decision_inputs": False,
        "wealth_core_parity": True,
        "variant_definition": {
            "A": "current-main current Sharadar sector grouping; historical metadata causality not claimed",
            "B": "A with sector contagion grouping replaced only by strict-prior SEC SIC -> FF12",
        },
        "overlay_accounting": {
            "decision_timing": "close decision -> following session open",
            "one_way_allocation_change_cost": runner.OVERLAY_ONE_WAY_COST,
            "defensive_asset": "BIL when complete frozen factors exist; cash before BIL inception",
        },
        "metrics": summary_metrics,
        "transitions": {name: account.transitions for name, account in accounts.items()},
        "transition_cost_sum": {name: account.transition_cost for name, account in accounts.items()},
        "normalization": {
            "rows": normalization.rows,
            "bars": normalization.bars,
            "dropped_no_identity": normalization.dropped_no_identity,
            "dropped_no_raw_close": normalization.dropped_no_raw_close,
            "raw_close_coverage": normalization.raw_close_coverage,
            "splits_detected": normalization.splits_detected,
            "identity_partial_sessions": [
                {"session": s, "coverage": c} for s, c in bad_identity],
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": "backtester.experiment-manifest/1",
        "experiment": runner.EXPERIMENT_ID,
        "main_sha": runner.EXPECTED_MAIN_SHA,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "production_module": str(imported),
        "production_module_sha256": runner.sha256_file(imported),
        "strategy_identity": strategy_identity,
        "input_files": dict(sorted(observed_inputs.items())),
        "outputs": {},
    }
    for path in (daily_path, metrics_path, summary_path):
        manifest["outputs"][path.name] = {
            "sha256": runner.sha256_file(path), "bytes": path.stat().st_size}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums = output / "SHA256SUMS.txt"
    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums.write_text(
        "".join(f"{runner.sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8")

    runner.print("[PASS] checkpoint-capable fresh A/B replay completed", flush=True)
    runner.print(pd.DataFrame(metrics_rows).to_string(index=False), flush=True)
    return 0
