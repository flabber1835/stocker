#!/usr/bin/env python3
"""Strict-PIT production certification on the agreed 20-year window."""
from __future__ import annotations

import builtins
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

# Current Production owns the pure Wealth Core plan call in core.kernel.  The
# retained strict-PIT wrapper predates that ownership split and instruments the
# historical core.production.plan_session seam to collect audit-only boundary
# evidence.  Bridge the old seam to the exact current kernel function without
# copying or changing economics: the kernel calls this dynamic proxy, whose
# target is replaced by the strict wrapper with an evidence-only decorator that
# delegates to the original exact function.
import sentinel.core.kernel as _strategy_kernel
import sentinel.core.production as _strategy_production

_exact_plan_session = _strategy_kernel.plan_session
_existing_plan_session = getattr(_strategy_production, "plan_session", None)
if _existing_plan_session is not None and _existing_plan_session is not _exact_plan_session:
    raise RuntimeError(
        "current Production unexpectedly exposes a different plan_session seam"
    )
_strategy_production.plan_session = _exact_plan_session


def _current_plan_session_proxy(*args, **kwargs):
    return _strategy_production.plan_session(*args, **kwargs)


_strategy_kernel.plan_session = _current_plan_session_proxy

import backtester.run_production_strict_pit_certification as strict
from backtester import causal_split_overrides as split_overrides

if _strategy_kernel.plan_session is not _current_plan_session_proxy:
    raise RuntimeError("strict-PIT kernel plan-session compatibility proxy was displaced")
if _strategy_production.plan_session is _exact_plan_session:
    raise RuntimeError("strict-PIT plan-session boundary evidence wrapper did not install")
if strict._real_plan_session is not _exact_plan_session:
    raise RuntimeError("strict-PIT plan-session wrapper did not bind the exact kernel function")

WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
FULL_END_SESSION = "2026-07-31"
END_SESSION = os.environ.get("CERTIFICATION_END_SESSION", FULL_END_SESSION)
EXPECTED_MAIN_SHA = "c851386fa4dddcf2e2533af3a1d313c38220b7f2"
DIVIDEND_SETTLEMENT_LAG_SESSIONS = 15
MAX_TRAILING_VOLUME_PARTICIPATION = 0.10
MIN_TRAILING_VOLUME_SESSIONS = 20
CERTIFICATION_CAPITAL_ENV = "PRODUCTION_CERTIFICATION_CAPITAL_USD"
_capacity_binding = None
_capacity_orders_checked = 0

strict.corrected.prod.EXPECTED_MAIN_SHA = EXPECTED_MAIN_SHA
strict.corrected.prod.base.runner.EXPECTED_MAIN_SHA = EXPECTED_MAIN_SHA
strict.corrected.WARMUP_START = WARMUP_START
strict.corrected.MEASUREMENT_START = MEASUREMENT_START
strict.corrected.runner.CHAIN_START = WARMUP_START
strict.corrected.runner.END_SESSION = END_SESSION
strict.corrected.runner.EXPERIMENT_ID = "2026-08-30-strict-pit-20y-production"
strict.runner.CHAIN_START = WARMUP_START
strict.runner.END_SESSION = END_SESSION
strict.MEASUREMENT_START = MEASUREMENT_START


class FinancialGradeGuardError(RuntimeError):
    """The replay reached an observation that cannot be financially certified."""


def _positive(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _configured_certification_capital():
    raw = os.environ.get(CERTIFICATION_CAPITAL_ENV, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise FinancialGradeGuardError(
            f"{CERTIFICATION_CAPITAL_ENV} must be a positive finite USD amount"
        ) from exc
    if not math.isfinite(value) or value <= 0.0:
        raise FinancialGradeGuardError(
            f"{CERTIFICATION_CAPITAL_ENV} must be a positive finite USD amount"
        )
    return value


def _configure_replay_capital():
    target = _configured_certification_capital()
    if target is None:
        return None
    modules = (
        strict.runner,
        strict.corrected.runner,
        strict.corrected.prod.base.runner,
    )
    changed = 0
    for module in modules:
        if hasattr(module, "STARTING_CASH"):
            setattr(module, "STARTING_CASH", target)
            changed += 1
    if not changed:
        raise FinancialGradeGuardError(
            "declared certification capital could not be bound to replay STARTING_CASH"
        )
    print(
        f"[CAPACITY CONTRACT] mode=enforced certification_capital_usd={target:.2f} "
        f"limit={MAX_TRAILING_VOLUME_PARTICIPATION:.2%}",
        flush=True,
    )
    return target


def _replay_starting_cash() -> float:
    value = getattr(strict.runner, "STARTING_CASH", None)
    if not _positive(value):
        raise FinancialGradeGuardError(
            f"replay STARTING_CASH is invalid for capacity evidence: {value!r}"
        )
    return float(value)


def _capacity_ceiling_usd(participation: float) -> float:
    if not _positive(participation):
        raise FinancialGradeGuardError(
            f"invalid volume participation for capacity evidence: {participation!r}"
        )
    return (
        _replay_starting_cash()
        * MAX_TRAILING_VOLUME_PARTICIPATION
        / float(participation)
    )


def _corrected_contract_print(*args, **kwargs):
    if args and args[0] == (
        "[RUN] corrected production replay: 1997 full-machine warm-up + causal historical cash"
    ):
        args = (
            f"[RUN] corrected production replay: warmup={WARMUP_START} "
            f"measurement={MEASUREMENT_START} + causal historical cash",
            *args[1:],
        )
    return builtins.print(*args, **kwargs)


strict.corrected.print = _corrected_contract_print
_original_measurement_factor_builder = strict.corrected._original_sfp_builder


def _measurement_anchored_factor_builder(path):
    saved = strict.runner.CHAIN_START
    strict.runner.CHAIN_START = MEASUREMENT_START
    try:
        return _original_measurement_factor_builder(path)
    finally:
        strict.runner.CHAIN_START = saved


strict.corrected._original_sfp_builder = _measurement_anchored_factor_builder
_original_terminal_loader = strict.base.load_frozen_terminal_terms


def _causal_identity_terminal_loader(*args, **kwargs):
    kwargs["identity_binding"] = "resolved"
    return _original_terminal_loader(*args, **kwargs)


strict.base.load_frozen_terminal_terms = _causal_identity_terminal_loader
if strict.base.BOUNDARY_SESSION < WARMUP_START:
    strict.base.BOUNDARY_SESSION = "9999-12-31"
if END_SESSION != FULL_END_SESSION:
    strict.runner.MEASUREMENT_WINDOWS = {1: MEASUREMENT_START}


def _option_path(flag: str, default: Path) -> Path:
    args = list(sys.argv[1:])
    for i, value in enumerate(args):
        if value == flag:
            if i + 1 >= len(args):
                raise RuntimeError(f"{flag} requires a path")
            return Path(args[i + 1])
        prefix = flag + "="
        if value.startswith(prefix):
            return Path(value[len(prefix):])
    return default


def _bind_verified_main_identity() -> tuple[Path, str]:
    main_root = _option_path("--main-root", PINNED_MAIN_ROOT).resolve()
    if not main_root.is_dir():
        raise RuntimeError(f"pinned production checkout is missing: {main_root}")
    completed = subprocess.run(
        ["git", "-C", str(main_root), "rev-parse", "HEAD"],
        check=False, capture_output=True, text=True,
    )
    actual = completed.stdout.strip()
    if completed.returncode != 0 or not actual:
        detail = completed.stderr.strip() or "git returned no SHA"
        raise RuntimeError(f"cannot verify pinned production checkout {main_root}: {detail}")
    if actual != EXPECTED_MAIN_SHA:
        raise RuntimeError(
            f"production checkout mismatch: expected {EXPECTED_MAIN_SHA}, got {actual}"
        )
    inherited = os.environ.get("BACKTESTER_MAIN_SHA", "").strip()
    if inherited and inherited != actual:
        raise RuntimeError(
            f"conflicting BACKTESTER_MAIN_SHA: checkout={actual} environment={inherited}"
        )
    os.environ["BACKTESTER_MAIN_SHA"] = actual
    return main_root, actual


def _active_split_adjudications() -> dict[tuple[str, str], dict]:
    data_path = ROOT / "backtester" / "data" / "causal-split-overrides-v1.json"
    checksum_path = ROOT / "backtester" / "data" / "causal-split-overrides-v1.SHA256"
    expected = split_overrides._expected_digest(checksum_path, data_path)
    observed = split_overrides.sha256_file(data_path)
    if observed != expected:
        raise split_overrides.FrozenSplitOverrideError(
            f"split override checksum mismatch: {observed} != {expected}"
        )
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if payload.get("schema") != split_overrides.SCHEMA:
        raise split_overrides.FrozenSplitOverrideError("unexpected split override schema")
    records = list(payload.get("records") or [])
    sidecars, _witnesses = split_overrides._load_sidecar_records(data_path)
    records.extend(sidecars)
    active: dict[tuple[str, str], dict] = {}
    for raw in records:
        ticker = str(raw.get("ticker") or "").strip()
        session = str(raw.get("effective_session") or "").strip()
        if not ticker or not session or session < WARMUP_START or session > END_SESSION:
            continue
        known_by = str(raw.get("known_by") or "").strip()
        sources = raw.get("sources")
        if not known_by or known_by > session:
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} uses future-known evidence"
            )
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(x, str) or not x.startswith("https://") for x in sources)):
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} lacks auditable HTTPS sources"
            )
        try:
            multiplier = float(raw["multiplier"])
            expected_vendor = float(raw["expected_vendor_stated"])
            expected_derived = float(raw["expected_sep_derived"])
        except (KeyError, TypeError, ValueError) as exc:
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} has invalid numeric fields"
            ) from exc
        if any(not math.isfinite(x) or x <= 0 for x in (multiplier, expected_vendor, expected_derived)):
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} has non-positive/non-finite economics"
            )
        key = (ticker, session)
        if key in active:
            raise split_overrides.FrozenSplitOverrideError(
                f"duplicate split override for {ticker} {session}"
            )
        active[key] = dict(raw)
    return active


def _install_split_adjudications() -> None:
    active = _active_split_adjudications()
    if not active:
        print("[SPLIT ADJUDICATION] active=0", flush=True)
        return
    import stock_strategy_shared.split_reconciliation as canonical_split
    split_overrides.install_primary_split_adjudication(canonical_split, active)
    print(
        "[SPLIT ADJUDICATION] active=" + str(len(active)) + " keys="
        + ",".join(f"{t}:{s}" for t, s in sorted(active)), flush=True,
    )


def _pending(prior):
    if hasattr(prior, "pending"):
        return list(getattr(prior, "pending") or ())
    return list(_mapping(prior).get("pending") or ())


def _feed(prior) -> Mapping:
    if hasattr(prior, "feed"):
        return _mapping(getattr(prior, "feed"))
    return _mapping(_mapping(prior).get("feed"))


def _order_value(order, key, default=None):
    if isinstance(order, Mapping):
        return order.get(key, default)
    return getattr(order, key, default)


def _capacity_guard(prior, published) -> None:
    global _capacity_binding, _capacity_orders_checked
    bars = {
        str(getattr(bar, "security_id")): bar
        for bar in (getattr(published, "bars", None) or ())
    }
    series_by_security = _mapping(_feed(prior).get("series"))
    for order in _pending(prior):
        sid = str(_order_value(order, "security_id", "") or "")
        if not sid:
            continue
        bar = bars.get(sid)
        if bar is None:
            continue
        if not bool(getattr(bar, "tradeable", False)) or not _positive(
            getattr(bar, "raw_open", None)
        ):
            continue
        shares = _order_value(order, "shares", 0)
        if not _positive(shares):
            continue
        series = _mapping(series_by_security.get(sid))
        prior_volumes = [
            float(value)
            for value in list(series.get("volumes") or ())[-MIN_TRAILING_VOLUME_SESSIONS:]
            if _positive(value)
        ]
        if len(prior_volumes) < MIN_TRAILING_VOLUME_SESSIONS:
            raise FinancialGradeGuardError(
                f"capacity authority incomplete for executable order {sid}: "
                f"have {len(prior_volumes)} prior volume sessions, require "
                f"{MIN_TRAILING_VOLUME_SESSIONS}"
            )
        average_volume = sum(prior_volumes) / len(prior_volumes)
        participation = float(shares) / average_volume
        capacity_usd = _capacity_ceiling_usd(participation)
        _capacity_orders_checked += 1
        is_new_binding = (
            _capacity_binding is None
            or capacity_usd < float(_capacity_binding["capacity_usd"])
        )
        if is_new_binding:
            _capacity_binding = {
                "session": str(getattr(published, "session", "?")),
                "security_id": sid,
                "shares": float(shares),
                "average_volume": average_volume,
                "participation": participation,
                "capacity_usd": capacity_usd,
            }
        if participation > MAX_TRAILING_VOLUME_PARTICIPATION + 1e-15:
            target = _configured_certification_capital()
            if target is not None:
                raise FinancialGradeGuardError(
                    f"capacity ceiling exceeded on {getattr(published, 'session', '?')} "
                    f"{sid}: certification_capital_usd={target:.2f} "
                    f"participation={participation:.4%} > "
                    f"{MAX_TRAILING_VOLUME_PARTICIPATION:.2%}"
                )
            if is_new_binding:
                print(
                    f"[CAPACITY EVIDENCE] session={getattr(published, 'session', '?')} "
                    f"sid={sid} nominal_participation={participation:.4%} "
                    f"limit={MAX_TRAILING_VOLUME_PARTICIPATION:.2%} "
                    f"linearized_initial_capital_ceiling_usd={capacity_usd:.2f} "
                    "mode=scale_neutral action=continue",
                    flush=True,
                )


def _print_capacity_summary() -> None:
    target = _configured_certification_capital()
    mode = "enforced" if target is not None else "scale_neutral_evidence"
    if _capacity_binding is None:
        print(
            f"[CAPACITY SUMMARY] mode={mode} orders_checked={_capacity_orders_checked} "
            "binding=none",
            flush=True,
        )
        return
    print(
        f"[CAPACITY SUMMARY] mode={mode} orders_checked={_capacity_orders_checked} "
        f"binding_session={_capacity_binding['session']} "
        f"sid={_capacity_binding['security_id']} "
        f"nominal_participation={float(_capacity_binding['participation']):.4%} "
        f"limit={MAX_TRAILING_VOLUME_PARTICIPATION:.2%} "
        f"linearized_initial_capital_ceiling_usd={float(_capacity_binding['capacity_usd']):.2f}",
        flush=True,
    )


def _resolved_nav_guard(result, session: str) -> None:
    evidence = _mapping(getattr(result, "last_evidence", None))
    wealth = _mapping(evidence.get("wealth_core"))
    if not wealth:
        raise FinancialGradeGuardError(
            f"production session {session} emitted no Wealth Core valuation evidence"
        )
    if bool(wealth.get("blocked")) or not _positive(wealth.get("resolved_equity")):
        raise FinancialGradeGuardError(
            f"financial-grade NAV unresolved on {session}: "
            f"blocked={wealth.get('blocked')} resolved_equity={wealth.get('resolved_equity')!r}"
        )


def _install_financial_guards() -> None:
    import sentinel.controller.concordance as concordance
    import sentinel.core.production as strategy_production
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig

    if getattr(strategy_production, "_financial_grade_guards_installed", False):
        return
    original_equal_weight = concordance.equal_weight_next_close_return

    def strict_equal_weight(selected_security_ids, previous_close, current_close):
        missing = [
            str(security_id) for security_id in tuple(selected_security_ids)
            if not (_positive(previous_close.get(security_id))
                    and _positive(current_close.get(security_id)))
        ]
        if missing:
            raise FinancialGradeGuardError(
                "recent-leadership next-close return is unresolved for: "
                + ", ".join(sorted(missing))
            )
        return original_equal_weight(selected_security_ids, previous_close, current_close)

    concordance.equal_weight_next_close_return = strict_equal_weight
    original_advance_state = strategy_production.advance_state
    financial_config = WealthCoreConfig(
        dividend_settlement_lag_sessions=DIVIDEND_SETTLEMENT_LAG_SESSIONS
    )

    def guarded_advance_state(prior, published, *args, **kwargs):
        _capacity_guard(prior, published)
        configured = kwargs.get("wealth_config")
        if configured is None:
            kwargs["wealth_config"] = financial_config
        elif getattr(configured, "dividend_settlement_lag_sessions", None) != DIVIDEND_SETTLEMENT_LAG_SESSIONS:
            raise FinancialGradeGuardError(
                "production replay requested a dividend cash lag inconsistent "
                f"with financial certification: "
                f"{getattr(configured, 'dividend_settlement_lag_sessions', None)} "
                f"!= {DIVIDEND_SETTLEMENT_LAG_SESSIONS}"
            )
        result = original_advance_state(prior, published, *args, **kwargs)
        _resolved_nav_guard(result, str(getattr(published, "session", "?")))
        return result

    strategy_production.advance_state = guarded_advance_state
    strategy_production._financial_grade_guards_installed = True
    capacity_mode = (
        "enforced"
        if _configured_certification_capital() is not None
        else "scale_neutral_evidence"
    )
    print(
        "[FINANCIAL GRADE] resolved_nav=required "
        "missing_leadership_return=fail_closed "
        f"dividend_lag_sessions={DIVIDEND_SETTLEMENT_LAG_SESSIONS} "
        f"max_prior20_volume_participation={MAX_TRAILING_VOLUME_PARTICIPATION:.2%} "
        f"capacity_mode={capacity_mode}",
        flush=True,
    )


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        print(
            f"[SELFTEST PASS] production 20y entrypoint root={ROOT} "
            f"backtester_import={Path(strict.__file__).resolve()}", flush=True,
        )
        return 0
    main_root, main_sha = _bind_verified_main_identity()
    certification_capital = _configure_replay_capital()
    if "--self-test-source-identity" in sys.argv[1:]:
        _install_financial_guards()
        import sentinel.core.production as strategy_production
        if not getattr(strategy_production, "_financial_grade_guards_installed", False):
            raise RuntimeError("financial-grade production guards did not install")
        if certification_capital is not None and not math.isclose(
            _replay_starting_cash(), certification_capital, rel_tol=0.0, abs_tol=0.01
        ):
            raise RuntimeError("certification capital did not bind replay STARTING_CASH")
        print(
            f"[SELFTEST PASS] production source identity root={main_root} sha={main_sha} "
            f"dividend_lag={DIVIDEND_SETTLEMENT_LAG_SESSIONS} "
            f"capacity={MAX_TRAILING_VOLUME_PARTICIPATION:.2%} "
            f"capacity_mode={'enforced' if certification_capital is not None else 'scale_neutral_evidence'}",
            flush=True,
        )
        return 0
    print(
        f"[SOURCE IDENTITY PASS] production_root={main_root} sha={main_sha}", flush=True,
    )
    print(
        f"[CONTRACT] role=production warmup={WARMUP_START} "
        f"measurement={MEASUREMENT_START} end={END_SESSION}", flush=True,
    )
    if certification_capital is None:
        print(
            f"[CAPACITY CONTRACT] mode=scale_neutral_evidence "
            f"replay_starting_cash_usd={_replay_starting_cash():.2f} "
            f"limit={MAX_TRAILING_VOLUME_PARTICIPATION:.2%}",
            flush=True,
        )
    _install_split_adjudications()
    _install_financial_guards()
    result = int(strict.main())
    _print_capacity_summary()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
