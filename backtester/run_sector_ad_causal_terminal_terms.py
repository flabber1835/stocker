#!/usr/bin/env python3
"""Research-side A/D launcher with causal terminal terms and running CAGR checkpoints.

A is the current-main/current-Sharadar-metadata control.
D is the current strategy under the retained best-effort causal/PIT metadata
semantics: category removed, exchange inert, strict-prior SEC CIK issuer-family
authority with permanent-security fallback, and strict-prior SEC SIC -> FF12
sector grouping with singleton unknown peers.

The strategy implementation remains the exact pinned ``main`` checkout. This
launcher changes research-side historical inputs only.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from typing import Sequence

import pandas as pd


def _option_path(flag: str, default: str) -> Path:
    args = sys.argv[1:]
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return Path(args[index + 1])
        prefix = flag + "="
        if value.startswith(prefix):
            return Path(value[len(prefix):])
    return Path(default)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


LAB_ROOT = _option_path("--lab-root", os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
MAIN_ROOT = _option_path("--main-root", os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
OUTPUT = _option_path("--output", "backtester-results/sector-ad").resolve()
PROGRESS_INTERVAL = int(os.environ.get("BACKTESTER_PROGRESS_INTERVAL_SESSIONS", "63"))
if PROGRESS_INTERVAL <= 0:
    raise RuntimeError("BACKTESTER_PROGRESS_INTERVAL_SESSIONS must be positive")

sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(MAIN_ROOT / "shared"))
sys.path.insert(0, str(MAIN_ROOT))

from backtester.causal_terminal_terms import (  # noqa: E402
    SCHEMA as TERMINAL_TERMS_SCHEMA,
    load_frozen_terminal_terms,
    merge_terminal_events,
)
from stock_strategy_shared.wealth_core.feed import SecurityMeta  # noqa: E402
from stock_strategy_shared.wealth_core.terminal import (  # noqa: E402
    TerminalKind,
    TerminalTerms,
)
import sentinel.core.production as production  # noqa: E402

BASE_RUNNER = LAB_ROOT / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
spec = importlib.util.spec_from_file_location("sector_ad_base_runner", BASE_RUNNER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base runner from {BASE_RUNNER}")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.EXPERIMENT_ID = "2026-08-27-sector-ad"

TERMS_PATH = LAB_ROOT / "backtester" / "data" / "causal-terminal-terms-v1.json"
TERMS_CHECKSUM_PATH = LAB_ROOT / "backtester" / "data" / "causal-terminal-terms-v1.SHA256"
BOUNDARY_SESSION = "2001-06-04"

_session_axis: Sequence[str] | None = None
_exact_by_session: dict[str, tuple[object, ...]] | None = None
_terms_digest: str | None = None
_boundary_witness: dict | None = None
_current_session: str | None = None
_account_refs: dict[str, object] = {}
_progress_sessions = 0

_real_build_sfp_levels = runner.build_sfp_levels
_real_build_terminal_events = runner.build_terminal_events
_real_wealth_equities = runner.wealth_equities
_real_overlay_step = runner.OverlayAccount.step
_real_published_session = production.PublishedSession


def _capture_session_axis(*args, **kwargs):
    global _session_axis
    result = _real_build_sfp_levels(*args, **kwargs)
    _session_axis = tuple(result[0])
    return result


def _minimal_meta(payload: dict) -> dict[str, SecurityMeta]:
    out: dict[str, SecurityMeta] = {}
    for record in payload.get("records") or []:
        sid = str(record["security_id"])
        out[sid] = SecurityMeta(
            security_id=sid, ticker=str(record["ticker"]),
            permaticker=sid, related_tickers=())
        delivered_sid = record.get("delivered_security_id")
        delivered_ticker = record.get("delivered_ticker")
        if delivered_sid and delivered_ticker:
            delivered_sid = str(delivered_sid)
            out[delivered_sid] = SecurityMeta(
                security_id=delivered_sid, ticker=str(delivered_ticker),
                permaticker=delivered_sid, related_tickers=())
    return out


def _load_exact_terms(resolver) -> dict[str, tuple[object, ...]]:
    global _exact_by_session, _terms_digest
    if _exact_by_session is not None:
        return _exact_by_session
    if _session_axis is None:
        raise RuntimeError("replay session axis was not established before terminal loading")

    payload = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    phase1 = runner.load_phase1_manifest(LAB_ROOT / "PIT input data" / "MANIFEST.csv")
    for record in payload.get("records") or []:
        witness = record.get("price_witness")
        if not witness:
            continue
        witness_session = str(witness["session"])
        expected_source_hash = runner.source_hash_for_year(
            phase1, int(witness_session[:4]))
        if str(witness.get("source_sep_sha256")) != expected_source_hash:
            raise RuntimeError(
                f"terminal price witness for {record.get('security_id')} is not bound to the frozen SEP source")

    _exact_by_session, _terms_digest = load_frozen_terminal_terms(
        TERMS_PATH, TERMS_CHECKSUM_PATH,
        sessions=_session_axis,
        resolve_identity=resolver.resolve,
        meta=_minimal_meta(payload),
        TerminalTerms=TerminalTerms,
        TerminalKind=TerminalKind,
    )
    print(f"[RUN] frozen causal terminal terms sha256={_terms_digest}", flush=True)
    return _exact_by_session


def _terminal_events_with_exact_terms(session: str, rows, priced_tickers, resolver, main):
    vendor_events = _real_build_terminal_events(
        session, rows, priced_tickers, resolver, main)
    exact = _load_exact_terms(resolver).get(str(session), ())
    return merge_terminal_events(str(session), vendor_events, exact)


def _wealth_equities_with_boundary_witness(state):
    global _boundary_witness, _current_session
    _current_session = str(state.last_processed_session)
    core_open, core_close = _real_wealth_equities(state)
    if _current_session == BOUNDARY_SESSION:
        wealth = ((state.last_evidence or {}).get("wealth_core") or {})
        unresolved = tuple(map(str, wealth.get("open_unresolved_security_ids") or ()))
        if core_open is None or unresolved:
            raise RuntimeError(
                f"causal terminal repair failed at {BOUNDARY_SESSION}: "
                f"resolved_open_equity={core_open!r} unresolved={unresolved!r}")
        _boundary_witness = {
            "session": BOUNDARY_SESSION,
            "resolved_open_equity": float(core_open),
            "open_unresolved_security_ids": [],
        }
        print(
            f"[PASS] {BOUNDARY_SESSION} Wealth Core open resolved exactly: {float(core_open):.6f}",
            flush=True)
    return core_open, core_close


def _strict_prior(model, ticker: str, session: str):
    dates = model.cik_dates.get(str(ticker), ())
    values = model.cik_values.get(str(ticker), ())
    i = bisect.bisect_left(dates, session) - 1
    return values[i] if i >= 0 else None


def _cik_ticker_candidates(model) -> Mapping[str, tuple[str, ...]]:
    cached = getattr(model, "_ad_cik_ticker_candidates", None)
    if cached is not None:
        return cached
    grouped: dict[str, set[str]] = defaultdict(set)
    for ticker, values in model.cik_values.items():
        for cik in values:
            grouped[str(cik)].add(str(ticker))
    result = {cik: tuple(sorted(tickers)) for cik, tickers in grouped.items()}
    setattr(model, "_ad_cik_ticker_candidates", result)
    return result


class _PITMetaMap(Mapping):
    """Session-causal metadata map for D."""

    def __init__(self, sectors):
        self.base = sectors.meta
        self.model = sectors.model
        self.session = str(sectors.session)
        self.sid_to_ticker = dict(sectors.sid_to_ticker)
        self.candidates = _cik_ticker_candidates(self.model)
        self.cache: dict[str, object] = {}

    def __getitem__(self, key):
        sid = str(key)
        if sid in self.cache:
            return self.cache[sid]
        original = self.base[sid]
        ticker = str(self.sid_to_ticker.get(sid) or original.ticker)
        cik = _strict_prior(self.model, ticker, self.session)
        related: tuple[str, ...] = ()
        if cik is not None:
            related = tuple(
                candidate for candidate in self.candidates.get(str(cik), ())
                if candidate != ticker
                and _strict_prior(self.model, candidate, self.session) == cik
            )
        value = replace(
            original,
            ticker=ticker,
            category=None,
            related_tickers=related,
            exchange=None,
            exchange_authoritative=False,
        )
        self.cache[sid] = value
        return value

    def __iter__(self):
        return iter(self.base)

    def __len__(self):
        return len(self.base)

    def get(self, key, default=None):
        return self[str(key)] if str(key) in self.base else default


def _published_session_ad(*args, **kwargs):
    sectors = kwargs.get("sectors")
    if isinstance(sectors, runner.FF12SectorMap):
        kwargs["meta"] = _PITMetaMap(sectors)
    return _real_published_session(*args, **kwargs)


def _running_cagr(nav: float, session: str) -> float:
    start = date.fromisoformat(str(runner.CHAIN_START))
    end = date.fromisoformat(str(session))
    elapsed_days = (end - start).days
    if elapsed_days <= 0 or nav <= 0:
        return float("nan")
    return float(nav ** (365.2425 / elapsed_days) - 1.0)


def _overlay_step_with_progress(self, *args, **kwargs):
    global _progress_sessions
    nav = _real_overlay_step(self, *args, **kwargs)
    _account_refs[str(self.name)] = self
    if str(self.name) == "B":
        _progress_sessions += 1
        session = str(_current_session or "")
        final = bool(session and session == str(runner.END_SESSION))
        if _progress_sessions % PROGRESS_INTERVAL == 0 or final:
            a = _account_refs.get("A")
            if a is None:
                raise RuntimeError("A account missing at A/D progress checkpoint")
            a_nav = float(a.nav)
            d_nav = float(self.nav)
            a_cagr = _running_cagr(a_nav, session)
            d_cagr = _running_cagr(d_nav, session)
            print(
                f"[PROGRESS] session={session} sessions={_progress_sessions} "
                f"from={runner.CHAIN_START} "
                f"A_multiple={a_nav:.10f} A_cagr={a_cagr:.10%} "
                f"D_multiple={d_nav:.10f} D_cagr={d_cagr:.10%}",
                flush=True)
    return nav


def _runner_print(*args, **kwargs):
    if args and isinstance(args[0], str):
        text = args[0]
        text = text.replace("A/B/C", "A/D").replace("A/B", "A/D")
        text = re.sub(r"\bB=", "D=", text)
        args = (text, *args[1:])
    print(*args, **kwargs)


runner.build_sfp_levels = _capture_session_axis
runner.build_terminal_events = _terminal_events_with_exact_terms
runner.wealth_equities = _wealth_equities_with_boundary_witness
runner.OverlayAccount.step = _overlay_step_with_progress
runner.print = _runner_print
production.PublishedSession = _published_session_ad

_bounded_end = os.environ.get("BACKTESTER_CAUSAL_END_SESSION")
if _bounded_end:
    runner.END_SESSION = str(_bounded_end)
    runner.MEASUREMENT_WINDOWS = {}


def _postprocess_ad_bundle() -> None:
    daily_path = OUTPUT / "daily.csv.gz"
    metrics_path = OUTPUT / "metrics.csv"
    summary_path = OUTPUT / "summary.json"
    for path in (daily_path, metrics_path, summary_path):
        if not path.exists():
            raise RuntimeError(f"expected replay output is missing: {path}")

    daily = pd.read_csv(daily_path, compression="gzip")
    rename = {column: "D_" + column[2:] for column in daily.columns if column.startswith("B_")}
    daily.rename(columns=rename, inplace=True)
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    metrics = pd.read_csv(metrics_path)
    if "variant" in metrics.columns:
        metrics.loc[metrics["variant"].astype(str).eq("B"), "variant"] = "D"
    metrics.to_csv(metrics_path, index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for window in (summary.get("metrics") or {}).values():
        if isinstance(window, dict) and "B" in window:
            window["D"] = window.pop("B")
    for key in ("transitions", "transition_cost_sum"):
        block = summary.get(key)
        if isinstance(block, dict) and "B" in block:
            block["D"] = block.pop("B")
    summary["variant_definition"] = {
        "A": "current-main current Sharadar metadata control; historical metadata causality not claimed",
        "D": (
            "current strategy with causal/PIT metadata: category removed; exchange inert; "
            "strict-prior SEC CIK issuer family with permanent-security fallback; strict-prior "
            "SEC SIC -> FF12 sector grouping; missing SIC is a singleton unknown peer"
        ),
    }
    summary["progress_interval_sessions"] = PROGRESS_INTERVAL
    summary["progress_cagr_definition"] = (
        "cumulative NAV multiple from chain_start annualized by elapsed calendar days using 365.2425 days/year"
    )
    summary["d_pit_semantics"] = {
        "category": "removed",
        "exchange": "inert/non-authoritative",
        "issuer_family": "strict-prior SEC CIK; permanent-security fallback",
        "sector": "strict-prior SEC SIC -> frozen FF12",
        "missing_sector": "singleton unknown peer",
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _postprocess_provenance() -> None:
    if _terms_digest is None or _exact_by_session is None:
        raise RuntimeError("causal terminal terms were never loaded by the replay")
    if str(runner.END_SESSION) >= BOUNDARY_SESSION and _boundary_witness is None:
        raise RuntimeError(
            f"replay reached {runner.END_SESSION} but never proved the {BOUNDARY_SESSION} open boundary")
    summary_path = OUTPUT / "summary.json"
    manifest_path = OUTPUT / "manifest.json"
    sums_path = OUTPUT / "SHA256SUMS.txt"
    daily_path = OUTPUT / "daily.csv.gz"
    metrics_path = OUTPUT / "metrics.csv"

    events = []
    for session in sorted(_exact_by_session):
        for terms in _exact_by_session[session]:
            events.append({
                "session": str(terms.session),
                "security_id": str(terms.security_id),
                "kind": terms.kind.value,
            })

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["causal_terminal_terms"] = {
        "schema": TERMINAL_TERMS_SCHEMA,
        "sha256": _terms_digest,
        "events": events,
        "production_type": "stock_strategy_shared.wealth_core.terminal.TerminalTerms",
        "original_failure_boundary": _boundary_witness,
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiment"] = runner.EXPERIMENT_ID
    inputs = manifest.setdefault("input_files", {})
    for path in (TERMS_PATH, TERMS_CHECKSUM_PATH):
        inputs[str(path.relative_to(LAB_ROOT))] = {
            "sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest["input_files"] = dict(sorted(inputs.items()))
    for path in (daily_path, metrics_path, summary_path):
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8")


def main() -> int:
    print(
        f"[RUN] A/D cumulative CAGR checkpoint interval={PROGRESS_INTERVAL} sessions",
        flush=True)
    rc = int(runner.main())
    if rc != 0:
        return rc
    _postprocess_ad_bundle()
    _postprocess_provenance()
    print("[PASS] A/D PIT metadata and causal terminal provenance recorded", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
