#!/usr/bin/env python3
"""Certified LD-RC comparison with a full-stack causal PIT D track.

A keeps the existing current/non-PIT Sharadar metadata baseline. D sends the
available causal PIT authorities through Wealth Core and Sentinel/LD-RC, allows
the two books to diverge naturally, and measures each account from its own Wealth
Core equity path. The exact requested current-main strategy implementation stays
frozen for both tracks.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
import importlib.util
import json
import math
import os
from pathlib import Path
import re

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


def _production_runner_print(*args, **kwargs):
    """Keep legacy internal account names out of Production run logs."""
    if args and isinstance(args[0], str):
        text = args[0]
        if "window_years" in text and "variant" in text and "\n" in text:
            # The runner prints its pre-finalization internal table. The public
            # Production/SPY table is printed after names and hashes are final.
            return None
        if text == "[RUN] fresh chronological A/B/C replay; no prerecorded decisions":
            text = "[RUN] fresh chronological Production replay; no prerecorded decisions"
        elif text == "[PASS] fresh A/B replay completed":
            text = "[PASS] fresh Production replay completed"
        else:
            checkpoint = re.fullmatch(
                r"(\[RUN\] .+ sessions=[^ ]+) A=[^ ]+ B=([^ ]+)", text
            )
            if checkpoint is not None:
                text = f"{checkpoint.group(1)} Production={checkpoint.group(2)}"
        args = (text, *args[1:])
    print(*args, **kwargs)


base.runner.print = _production_runner_print


def _production_layer_print(*args, **kwargs):
    """Translate messages emitted by the inherited comparison layer."""
    if args and isinstance(args[0], str):
        text = args[0]
        if text.startswith("[RUN] A/D cumulative CAGR checkpoint interval="):
            text = text.replace(
                "[RUN] A/D cumulative CAGR",
                "[RUN] Production cumulative CAGR",
                1,
            )
        elif text == "[PASS] A/D PIT-equivalent replay and causal terminal provenance recorded":
            text = "[PASS] Production replay and causal terminal provenance recorded"
        elif text.startswith("[PROGRESS]") and " D_multiple=" in text:
            match = re.match(
                r"(\[PROGRESS\] session=[^ ]+ sessions=[^ ]+ from=[^ ]+).*"
                r" D_multiple=([^ ]+) D_cagr=([^ ]+)",
                text,
            )
            if match is not None:
                text = (
                    f"{match.group(1)} role=Production "
                    f"multiple={match.group(2)} cumulative_cagr={match.group(3)}"
                )
        args = (text, *args[1:])
    print(*args, **kwargs)


base.print = _production_layer_print


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
_production_dataset_hash: str | None = None
_production_measurement_start: str | None = None
_real_advance_state = production.advance_state
_real_raw_overlay_step = base._real_overlay_step

UNRESOLVED_OPEN_TRANSITION_MARKER = (
    "allocation transition coincides with unresolved Wealth Core open"
)
PRODUCTION_FAILURE_SCHEMA = "backtester.production-failure-context/1"


def _jsonable(value):
    """Return a deterministic, strict-JSON representation of runtime evidence."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        sequence = sorted(value, key=str) if isinstance(value, (set, frozenset)) else value
        return [_jsonable(item) for item in sequence]
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return str(value)


def _matching_held_episodes(state, unresolved: list[str]) -> list[dict]:
    """Bind every unresolved security to its held episode and source lots."""
    unresolved_set = set(unresolved)
    wealth_state = dict(getattr(state, "wealth_core", None) or {})
    feed = dict(getattr(state, "feed", None) or {})
    series_by_sid = dict(feed.get("series") or {})
    last_known = dict(getattr(state, "last_known", None) or {})
    rows: list[dict] = []
    episodes = dict(wealth_state.get("episodes") or {})
    for slot_id, raw_episode in sorted(episodes.items(), key=lambda pair: str(pair[0])):
        episode = dict(raw_episode or {})
        security_id = str(episode.get("security_id") or "")
        if security_id not in unresolved_set:
            continue
        source = dict(series_by_sid.get(security_id) or {})
        rows.append({
            "slot_id": str(slot_id),
            "security_id": security_id,
            "ticker": str(episode.get("ticker") or source.get("ticker") or ""),
            "episode": _jsonable(episode),
            "source_lots": _jsonable(episode.get("source_lots") or []),
            "feed_source_identity": _jsonable({
                key: source.get(key)
                for key in ("security_id", "ticker", "issuer_id", "split_factor")
            }),
            "last_known_mark": _jsonable(last_known.get(security_id)),
        })
    return rows


def _production_failure_payload(
    state,
    account,
    *,
    core_open,
    core_close,
    prior_core_close,
    bil_gap,
    bil_intraday,
    next_target,
) -> dict:
    """Build the stable evidence record for the fail-closed accounting guard."""
    session = str(getattr(state, "last_processed_session", None) or "")
    evidence = dict(getattr(state, "last_evidence", None) or {})
    wealth_evidence = dict(evidence.get("wealth_core") or {})
    unresolved = sorted({
        str(value)
        for value in (wealth_evidence.get("open_unresolved_security_ids") or [])
    })
    wealth_state = dict(getattr(state, "wealth_core", None) or {})
    pending_orders = [
        row for row in (getattr(state, "pending", None) or [])
        if str((row or {}).get("security_id") or "") in set(unresolved)
    ]
    return _jsonable({
        "schema": PRODUCTION_FAILURE_SCHEMA,
        "status": "FAIL_CLOSED",
        "failure": {
            "code": "UNRESOLVED_OPEN_ALLOCATION_TRANSITION",
            "message": (
                "Production allocation transition requires an exact Wealth Core open, "
                "but at least one held security has no causally resolved open"
            ),
        },
        "session": session,
        "account": {
            "role": "Production",
            "initialized": bool(getattr(account, "initialized", False)),
            "nav_before_session": float(getattr(account, "nav")),
            "effective_exposure_before_open": float(getattr(account, "effective")),
            "pending_exposure_for_this_open": float(getattr(account, "pending")),
            "next_target_exposure": float(next_target),
            "transition_required": (
                abs(float(getattr(account, "pending")) - float(getattr(account, "effective")))
                > 1e-15
            ),
            "transitions_before_session": int(getattr(account, "transitions", 0)),
            "transition_cost_before_session": float(
                getattr(account, "transition_cost", 0.0)
            ),
        },
        "core_values": {
            "prior_close_equity": prior_core_close,
            "resolved_open_equity": core_open,
            "estimated_close_equity": core_close,
            "defensive_gap_factor": bil_gap,
            "defensive_intraday_factor": bil_intraday,
        },
        "open_unresolved_security_ids": unresolved,
        "held_episodes": _matching_held_episodes(state, unresolved),
        "pending_orders_for_unresolved_securities": pending_orders,
        "terminal_state": {
            key: wealth_state.get(key) or {}
            for key in (
                "unresolved_terminals",
                "terminal_pending_sessions",
                "terminal_pending_terms",
                "terminal_carry_audit",
                "sessions_since_valid_mark",
                "last_valid_mark_session",
            )
        },
        "wealth_core_evidence": wealth_evidence,
        "decision": getattr(state, "last_decision", None),
        "source_identities": {
            "production_main_sha": EXPECTED_MAIN_SHA,
            "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
            "experiment": str(base.runner.EXPERIMENT_ID),
            "canonical_pit_dataset_hash": _production_dataset_hash,
            "strategy_identity": getattr(state, "strategy_identity", None),
            "wealth_core_hashes": wealth_evidence.get("hashes") or {},
        },
    })


def _write_production_failure_context(payload: dict) -> Path:
    raw = os.environ.get("PRODUCTION_FAILURE_CONTEXT_PATH", "").strip()
    path = Path(raw).resolve() if raw else base.OUTPUT / "production_failure_context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


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
    if len(values) < 6:
        raise RuntimeError("unexpected OverlayAccount.step call shape")
    values[0] = core_open
    values[1] = core_close
    values[2] = _pit_prior_core_close
    try:
        nav = _real_raw_overlay_step(self, *values, **kwargs)
    except RuntimeError as exc:
        if UNRESOLVED_OPEN_TRANSITION_MARKER not in str(exc):
            raise
        payload = _production_failure_payload(
            _latest_pit_state,
            self,
            core_open=core_open,
            core_close=core_close,
            prior_core_close=_pit_prior_core_close,
            bil_gap=values[3],
            bil_intraday=values[4],
            next_target=values[5],
        )
        # Losing the diagnostic is itself a hard failure. Re-raise that write
        # error while suppressing the inherited account label in its context.
        try:
            context_path = _write_production_failure_context(payload)
        except Exception as write_error:
            raise write_error from None
        unresolved = ",".join(payload["open_unresolved_security_ids"]) or "unknown"
        raise RuntimeError(
            "Production allocation transition coincides with an unresolved "
            f"Wealth Core open at {payload['session']}; "
            f"unresolved_security_ids={unresolved}; "
            f"failure_context={context_path}"
        ) from None
    _pit_prior_core_close = core_close
    return nav


# The base launcher's progress wrapper calls this module global. Rebinding it
# gives D its own Wealth Core return stream while preserving the certified
# OverlayAccount implementation and next-open timing.
base._real_overlay_step = _raw_overlay_step_fullstack

_year_end_sessions: set[str] = set()
_real_build_sfp_levels = base.runner.build_sfp_levels
_real_progress_overlay_step = base.runner.OverlayAccount.step


def _calendar_checkpoint_sessions(
    sessions,
    measurement_start: str,
    end_session: str | None = None,
) -> set[str]:
    """Select quarter ends plus the requested end from a canonical session axis."""
    axis = [
        str(value) for value in sessions
        if str(value) >= str(measurement_start)
        and (end_session is None or str(value) <= str(end_session))
    ]
    if any(current >= following for current, following in zip(axis, axis[1:])):
        raise RuntimeError("reporting session axis must be strictly increasing")
    result: set[str] = set()
    for index, session in enumerate(axis):
        current_quarter = (int(session[:4]), (int(session[5:7]) - 1) // 3)
        if index + 1 == len(axis):
            result.add(session)
            continue
        following = axis[index + 1]
        following_quarter = (
            int(following[:4]), (int(following[5:7]) - 1) // 3
        )
        if following_quarter != current_quarter:
            result.add(session)
    return result


def _increment_production_progress(progress_owner) -> int:
    value = int(getattr(progress_owner, "_progress_sessions", 0)) + 1
    progress_owner._progress_sessions = value
    return value


def _measurement_cagr(nav: float, measurement_start: str, session: str) -> float:
    elapsed = (
        date.fromisoformat(str(session)) - date.fromisoformat(str(measurement_start))
    ).days / 365.2425
    if elapsed <= 0:
        return 0.0
    if not math.isfinite(float(nav)) or float(nav) <= 0:
        raise RuntimeError("Production NAV must be positive and finite for CAGR")
    return float(nav) ** (1.0 / elapsed) - 1.0


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
            print(
                f"[YEAR-END] year={session[:4]} session={session} "
                f"role=Production multiple={float(self.nav):.10f} "
                f"cumulative_cagr={base._running_cagr(float(self.nav), session):.10%}",
                flush=True,
            )
    return nav


base.runner.build_sfp_levels = _build_sfp_levels_with_year_ends
base.runner.OverlayAccount.step = _overlay_step_with_calendar_year_cagr


def _max_metric_block(
    frame: pd.DataFrame,
    column: str,
    measurement_start: str | None = None,
) -> dict:
    x = frame[["date", column]].dropna().copy()
    if measurement_start is not None:
        x = x[x["date"].astype(str) >= str(measurement_start)].copy()
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


def _public_production_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """Remove the mechanical control and give the certified path its real name."""
    result = daily.copy()
    rename = {}
    for column in result.columns:
        if not column.startswith("D_"):
            continue
        public = "Production_" + column[2:]
        if public in result.columns:
            left = result[column]
            right = result[public]
            if not left.equals(right):
                raise RuntimeError(
                    f"conflicting internal/public Production daily columns: {column}, {public}"
                )
        else:
            rename[column] = public
    if rename:
        result.rename(columns=rename, inplace=True)
    result.drop(
        columns=[
            column for column in result.columns
            if column.startswith(("A_", "B_", "D_"))
            or column in {"wealth_core_equity", "green"}
        ],
        inplace=True,
        errors="ignore",
    )
    required = {"date", "Production_nav", "SPY_level"}
    missing = required.difference(result.columns)
    if missing:
        raise RuntimeError(
            f"public Production daily output missing columns: {sorted(missing)}"
        )
    ordered = ["date"]
    ordered.extend(sorted(
        column for column in result.columns if column.startswith("Production_")
    ))
    ordered.extend(
        column for column in result.columns
        if column not in ordered
    )
    return result[ordered]


def _public_production_metrics(
    metrics: pd.DataFrame,
    max_blocks: Mapping[str, Mapping],
) -> pd.DataFrame:
    """Expose only the certified Production account and its SPY benchmark."""
    result = metrics.copy()
    if "variant" not in result.columns:
        raise RuntimeError("metrics output has no variant column")
    result["variant"] = result["variant"].astype(str).replace({
        "B": "Production",
        "D": "Production",
    })
    result = result[result["variant"].isin(("Production", "SPY"))].copy()
    result = result[result["window_years"].astype(str) != "max"].copy()
    max_rows = []
    for label in ("Production", "SPY"):
        block = dict(max_blocks[label])
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
    return pd.concat([result, pd.DataFrame(max_rows)], ignore_index=True)


def _public_metric_summary(raw_metrics, max_blocks: Mapping[str, Mapping]) -> dict:
    result: dict[str, dict] = {}
    for window, raw_block in sorted(
        dict(raw_metrics or {}).items(), key=lambda pair: str(pair[0])
    ):
        if str(window) == "max" or not isinstance(raw_block, Mapping):
            continue
        production = raw_block.get("Production")
        if production is None:
            production = raw_block.get("D", raw_block.get("B"))
        block = {}
        if production is not None:
            block["Production"] = production
        if raw_block.get("SPY") is not None:
            block["SPY"] = raw_block["SPY"]
        if block:
            result[str(window)] = _jsonable(block)
    result["max"] = _jsonable({
        "Production": max_blocks["Production"],
        "SPY": max_blocks["SPY"],
    })
    return result


def _write_final_comparison() -> None:
    output = base.OUTPUT
    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"

    daily = pd.read_csv(daily_path, compression="gzip")
    public_reporting_ready = (
        _production_measurement_start is None
        or (
            not daily.empty
            and str(daily.iloc[0]["date"]) >= str(_production_measurement_start)
        )
    )
    production_nav_column = (
        "Production_nav" if "Production_nav" in daily.columns else "D_nav"
    )
    required = {"date", production_nav_column, "SPY_level"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"daily output missing required Production columns: {sorted(missing)}")
    d_core = []
    for session in daily["date"].astype(str):
        pair = _pit_core_by_session.get(session)
        if pair is None:
            raise RuntimeError(f"missing Production Wealth Core equity capture for {session}")
        d_core.append(float(pair[1]))
    daily["Production_wealth_core_equity"] = d_core
    daily = _public_production_daily(daily)
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    max_blocks = {
        "Production": _max_metric_block(
            daily, "Production_nav", _production_measurement_start
        ),
        "SPY": _max_metric_block(
            daily, "SPY_level", _production_measurement_start
        ),
    }

    metrics = pd.read_csv(metrics_path, dtype={"window_years": str})
    metrics = _public_production_metrics(metrics, max_blocks)
    metrics.to_csv(metrics_path, index=False)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["wealth_core_parity"] = False
    summary["full_stack_pit"] = True
    summary["wealth_core_pit_enabled"] = True
    summary["metrics"] = _public_metric_summary(summary.get("metrics"), max_blocks)
    for key in ("transitions", "transition_cost_sum"):
        raw = dict(summary.get(key) or {})
        production_value = raw.get("Production", raw.get("D", raw.get("B")))
        summary[key] = (
            {"Production": production_value}
            if production_value is not None else {}
        )
    coverage = (
        float(_pit_sec_cik_observations) / float(_pit_metadata_observations)
        if _pit_metadata_observations else 0.0
    )
    summary["pit_authority"] = {
        "prices_and_corporate_actions": "frozen PIT reconstruction already used by the certified replay",
        "wealth_core_issuer_family": "strict-prior SEC CIK; unknown-before-evidence becomes security singleton",
        "sentinel_sector": "strict-prior SEC CIK -> SEC SIC -> frozen FF12",
        "present_day_relatedtickers_in_production": False,
        "sec_cik_metadata_observations": int(_pit_sec_cik_observations),
        "total_metadata_observations": int(_pit_metadata_observations),
        "sec_cik_observation_coverage": coverage,
        "residual_non_pit_fields": ["Sharadar category", "Sharadar exchange"],
        "residual_note": "No retained historical authority for these two fields is present in this frozen laboratory bundle; they remain explicit certification caveats.",
    }
    summary["variant_definition"] = {
        "Production": (
            "certified full-stack causal PIT production strategy using the exact pinned "
            "production implementation"
        ),
        "SPY": "frozen PIT-reconstructed SPY total-return benchmark",
    }
    summary.pop("d_pit_semantics", None)
    summary["production_pit_semantics"] = {
        "identity_and_listing": "historical price-tape security episodes",
        "issuer_family": "strict-prior SEC CIK; causal security singleton before evidence",
        "sector": "strict-prior SEC CIK -> SEC SIC -> frozen FF12",
        "missing_sector": "singleton unknown peer",
        "wealth_core_path": "independent Production Wealth Core state and account equity",
    }
    summary["comparison_contract"] = {
        "Production": "full-stack causal PIT production path using every retained PIT authority in the frozen laboratory bundle",
        "wealth_core": f"exact current main {EXPECTED_MAIN_SHA}; independent Production account equity path",
        "measurement_windows": ["5", "10", "15", "20", "max"],
        "SPY": "frozen PIT-reconstructed SPY total-return factor series",
    }
    summary["calendar_year_cagr_checkpoints"] = sorted(_year_end_sessions)
    summary["calendar_year_cagr_definition"] = (
        "cumulative Production NAV from replay inception annualized through each completed calendar-year final trading session"
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

    if public_reporting_ready:
        print(
            "[FINAL METRICS] Production and SPY; 5/10/15/20/max trailing windows",
            flush=True,
        )
        print(metrics.to_csv(index=False), flush=True)


def main() -> int:
    print(f"[RUN] certified full-stack PIT Production current-main={EXPECTED_MAIN_SHA}", flush=True)
    print("[RUN] Production account uses its own Wealth Core equity", flush=True)
    rc = int(base.main())
    if rc != 0:
        return rc
    _write_final_comparison()
    print("[PASS] certified Production bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
