#!/usr/bin/env python3
"""Certified LD-RC comparison with a full-stack causal PIT D track.

A keeps the existing current/non-PIT Sharadar metadata baseline. D sends the
available causal PIT authorities through Wealth Core and Sentinel/LD-RC, allows
the two books to diverge naturally, and measures each account from its own Wealth
Core equity path. The exact requested current-main strategy implementation stays
frozen for both tracks.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

EXPECTED_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
LAB_ROOT = Path(__file__).resolve().parents[1]
BASE_LAUNCHER = LAB_ROOT / "backtester" / "run_sector_ad_causal_terminal_terms_v2.py"

spec = importlib.util.spec_from_file_location("ldrc_ad_base", BASE_LAUNCHER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base launcher from {BASE_LAUNCHER}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

# Bind both tracks to the exact current-main strategy implementation.
base.runner.EXPECTED_MAIN_SHA = EXPECTED_MAIN_SHA
base.runner.EXPERIMENT_ID = "2026-08-29-ldrc-nonpit-vs-fullstack-pit-certified"

# The old A/D harness was an isolation experiment and explicitly required Wealth
# Core parity. This certified experiment permits causal divergence.
base.runner.state_wc_parity = lambda *_args, **_kwargs: None

from stock_strategy_shared.wealth_core.feed import SecurityMeta  # noqa: E402
import sentinel.core.production as production  # noqa: E402


@dataclass(frozen=True)
class _PitSecurityMeta(SecurityMeta):
    """SecurityMeta with strict-prior SEC issuer authority."""

    pit_issuer_id: str = ""
    pit_issuer_source: str = ""

    def issuer_key(self) -> tuple[str | None, str | None]:
        return self.pit_issuer_id, self.pit_issuer_source


_pit_metadata_observations = 0
_pit_sec_cik_observations = 0
_latest_pit_state = None
_pit_prior_core_close: float | None = None
_pit_core_by_session: dict[str, tuple[float | None, float]] = {}
_real_advance_state = production.advance_state
_real_raw_overlay_step = base._real_overlay_step


def _strict_prior_cik(sectors, sid: str, meta: SecurityMeta, session: str) -> tuple[str, str]:
    ticker = str(sectors.sid_to_ticker.get(str(sid), meta.ticker) or meta.ticker)
    model = sectors.model
    cik = model._strict_prior(
        model.cik_dates.get(ticker, ()), model.cik_values.get(ticker, ()), session)
    if cik is None:
        # A unique security-level key is causal and fail-safe: it does not infer a
        # present-day related-ticker relationship before SEC evidence exists.
        return f"SEC_UNKNOWN:{sid}", "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON"
    return f"SEC_CIK:{cik}", "SEC_CIK_STRICT_PRIOR"


def _pit_meta_map(pub) -> dict[str, _PitSecurityMeta]:
    global _pit_metadata_observations, _pit_sec_cik_observations
    result: dict[str, _PitSecurityMeta] = {}
    for sid, meta in pub.meta.items():
        issuer_id, source = _strict_prior_cik(pub.sectors, str(sid), meta, str(pub.session))
        _pit_metadata_observations += 1
        if source == "SEC_CIK_STRICT_PRIOR":
            _pit_sec_cik_observations += 1
        result[str(sid)] = _PitSecurityMeta(
            security_id=meta.security_id,
            ticker=meta.ticker,
            category=meta.category,
            permaticker=meta.permaticker,
            # Eliminate present-day relatedtickers from the historical issuer path.
            related_tickers=(),
            first_session=meta.first_session,
            last_session=meta.last_session,
            exchange=meta.exchange,
            exchange_authoritative=meta.exchange_authoritative,
            pit_issuer_id=issuer_id,
            pit_issuer_source=source,
        )
    return result


def _pit_pub(pub):
    if not isinstance(pub.sectors, base.runner.FF12SectorMap):
        return pub
    pit_meta = _pit_meta_map(pub)
    pit_anchors = {}
    for sid, anchor in pub.feed_anchors.items():
        meta = pit_meta.get(str(sid))
        if meta is None:
            raise RuntimeError(f"PIT feed anchor {sid} has no session metadata")
        issuer_id, _source = meta.issuer_key()
        pit_anchors[sid] = replace(anchor, issuer_id=issuer_id)
    return replace(pub, meta=pit_meta, feed_anchors=pit_anchors)


def _advance_state_fullstack(state, pub, *args, **kwargs):
    global _latest_pit_state
    is_pit = isinstance(pub.sectors, base.runner.FF12SectorMap)
    effective_pub = _pit_pub(pub) if is_pit else pub
    result = _real_advance_state(state, effective_pub, *args, **kwargs)
    if is_pit:
        _latest_pit_state = result
    return result


production.advance_state = _advance_state_fullstack


def _raw_overlay_step_fullstack(self, *args, **kwargs):
    global _pit_prior_core_close
    if str(self.name) != "B":
        return _real_raw_overlay_step(self, *args, **kwargs)
    if _latest_pit_state is None:
        raise RuntimeError("D PIT Wealth Core state missing before account step")
    core_open, core_close = base.runner.wealth_equities(_latest_pit_state)
    session = str(_latest_pit_state.last_processed_session)
    _pit_core_by_session[session] = (core_open, core_close)
    values = list(args)
    if len(values) < 3:
        raise RuntimeError("unexpected OverlayAccount.step call shape")
    values[0] = core_open
    values[1] = core_close
    values[2] = _pit_prior_core_close
    nav = _real_raw_overlay_step(self, *values, **kwargs)
    _pit_prior_core_close = core_close
    return nav


# The base launcher's progress wrapper calls this module global. Rebinding it
# gives D its own Wealth Core return stream while preserving the certified
# OverlayAccount implementation and next-open timing.
base._real_overlay_step = _raw_overlay_step_fullstack

_year_end_sessions: set[str] = set()
_real_build_sfp_levels = base.runner.build_sfp_levels
_real_progress_overlay_step = base.runner.OverlayAccount.step


def _build_sfp_levels_with_year_ends(*args, **kwargs):
    result = _real_build_sfp_levels(*args, **kwargs)
    sessions = list(result[0])
    _year_end_sessions.clear()
    for i, session in enumerate(sessions):
        if i + 1 < len(sessions) and sessions[i + 1][:4] != session[:4]:
            _year_end_sessions.add(str(session))
    return result


def _overlay_step_with_calendar_year_cagr(self, *args, **kwargs):
    nav = _real_progress_overlay_step(self, *args, **kwargs)
    if str(self.name) == "B":
        session = str(base._current_session or "")
        if session in _year_end_sessions:
            a = base._account_refs.get("A")
            if a is None:
                raise RuntimeError("A account missing at calendar-year CAGR checkpoint")
            print(
                f"[YEAR-END] year={session[:4]} session={session} "
                f"A_nonpit_multiple={float(a.nav):.10f} "
                f"A_nonpit_cagr={base._running_cagr(float(a.nav), session):.10%} "
                f"D_fullpit_multiple={float(self.nav):.10f} "
                f"D_fullpit_cagr={base._running_cagr(float(self.nav), session):.10%}",
                flush=True,
            )
    return nav


base.runner.build_sfp_levels = _build_sfp_levels_with_year_ends
base.runner.OverlayAccount.step = _overlay_step_with_calendar_year_cagr


def _max_metric_block(frame: pd.DataFrame, column: str) -> dict:
    x = frame[["date", column]].dropna().copy()
    if x.empty or str(x.iloc[-1]["date"]) != str(base.runner.END_SESSION):
        raise RuntimeError(f"{column} has incomplete maximum-history measurement window")
    values = x[column].astype(float).to_numpy()
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise RuntimeError(f"{column} invalid maximum-history measurement values")
    start = str(x.iloc[0]["date"])
    end = str(x.iloc[-1]["date"])
    elapsed_years = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.2425
    if elapsed_years <= 0:
        raise RuntimeError("maximum-history elapsed years is non-positive")
    normalized = values / values[0]
    rets = normalized[1:] / normalized[:-1] - 1.0
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    peak = np.maximum.accumulate(normalized)
    max_dd = float(np.min(normalized / peak - 1.0))
    cagr = float(normalized[-1] ** (1.0 / elapsed_years) - 1.0)
    return {
        "start": start,
        "end": end,
        "sessions": int(len(x)),
        "elapsed_years": float(elapsed_years),
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "ending_multiple": float(normalized[-1]),
    }


def _write_final_comparison() -> None:
    output = base.OUTPUT
    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"

    daily = pd.read_csv(daily_path, compression="gzip")
    required = {"date", "A_nav", "D_nav", "SPY_level", "wealth_core_equity"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"daily output missing required comparison columns: {sorted(missing)}")
    d_core = []
    for session in daily["date"].astype(str):
        pair = _pit_core_by_session.get(session)
        if pair is None:
            raise RuntimeError(f"missing D Wealth Core equity capture for {session}")
        d_core.append(float(pair[1]))
    daily["A_wealth_core_equity"] = daily["wealth_core_equity"].astype(float)
    daily["D_wealth_core_equity"] = d_core
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    max_blocks = {
        "A": _max_metric_block(daily, "A_nav"),
        "D": _max_metric_block(daily, "D_nav"),
        "SPY": _max_metric_block(daily, "SPY_level"),
    }

    metrics = pd.read_csv(metrics_path, dtype={"window_years": str})
    metrics = metrics[metrics["window_years"].astype(str) != "max"].copy()
    max_rows = []
    for label, block in max_blocks.items():
        max_rows.append({
            "window_years": "max",
            "variant": label,
            "start": block["start"],
            "end": block["end"],
            "sessions": block["sessions"],
            "cagr": block["cagr"],
            "sharpe": block["sharpe"],
            "max_drawdown": block["max_drawdown"],
            "ending_multiple": block["ending_multiple"],
        })
    metrics = pd.concat([metrics, pd.DataFrame(max_rows)], ignore_index=True)
    metrics.to_csv(metrics_path, index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["wealth_core_parity"] = False
    summary["full_stack_pit"] = True
    summary["wealth_core_pit_enabled"] = True
    summary.setdefault("metrics", {})["max"] = max_blocks
    coverage = (
        float(_pit_sec_cik_observations) / float(_pit_metadata_observations)
        if _pit_metadata_observations else 0.0
    )
    summary["pit_authority"] = {
        "prices_and_corporate_actions": "frozen PIT reconstruction already used by the certified replay",
        "wealth_core_issuer_family": "strict-prior SEC CIK; unknown-before-evidence becomes security singleton",
        "sentinel_sector": "strict-prior SEC CIK -> SEC SIC -> frozen FF12",
        "present_day_relatedtickers_in_D": False,
        "sec_cik_metadata_observations": int(_pit_sec_cik_observations),
        "total_metadata_observations": int(_pit_metadata_observations),
        "sec_cik_observation_coverage": coverage,
        "residual_non_pit_fields": ["Sharadar category", "Sharadar exchange"],
        "residual_note": "No retained historical authority for these two fields is present in this frozen laboratory bundle; they remain explicit certification caveats.",
    }
    summary["comparison_contract"] = {
        "A": "LD-RC with existing current/non-PIT Sharadar metadata baseline",
        "D": "full-stack causal PIT path using every retained PIT authority in the frozen laboratory bundle; Wealth Core and LD-RC may diverge",
        "wealth_core": f"exact current main {EXPECTED_MAIN_SHA}; independent A/D states and independent account equity paths",
        "measurement_windows": ["5", "10", "15", "20", "max"],
        "spy": "same frozen PIT-reconstructed SPY total-return factor series used for both comparison columns",
    }
    summary["calendar_year_cagr_checkpoints"] = sorted(_year_end_sessions)
    summary["calendar_year_cagr_definition"] = (
        "cumulative full LD-RC account NAV from replay inception annualized through each completed calendar-year final trading session"
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["experiment"] = base.runner.EXPERIMENT_ID
    manifest["current_main_sha"] = EXPECTED_MAIN_SHA
    manifest["full_stack_pit"] = True
    outputs = manifest.setdefault("outputs", {})
    for path in (daily_path, metrics_path, summary_path):
        outputs[path.name] = {"sha256": base._sha256(path), "bytes": path.stat().st_size}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    print("[FINAL METRICS] 5/10/15/20/max trailing windows", flush=True)
    print(metrics.to_csv(index=False), flush=True)


def main() -> int:
    print(f"[RUN] certified full-stack PIT comparison current-main={EXPECTED_MAIN_SHA}", flush=True)
    print("[RUN] D Wealth Core divergence enabled; D account uses independent Wealth Core equity", flush=True)
    rc = int(base.main())
    if rc != 0:
        return rc
    _write_final_comparison()
    print("[PASS] certified non-PIT/full-stack-PIT LD-RC comparison bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
