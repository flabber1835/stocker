"""Pure production adapter from the canonical shadow to an execution plan.

Wealth Core owns the share target and the controller owns only its exposure.
This module joins those two durable decisions to a read-only broker observation;
it does not read a broker, persist a plan, or submit an order.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Mapping

import stock_strategy_shared.wealth_core as wealth_core_package
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.state import PortfolioState

from sentinel import identity
from sentinel.authority import RolloutMode, RolloutState
from sentinel.binding import AccountMismatch, AccountNotBound
from sentinel.controller.concordance import (
    IDENTITY_OVERLAY_FIELD, is_concordance_identity)
from sentinel.core.production import SessionState
from sentinel.execution.commands import committed_quantity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.projection import Projection, desired_basket, project
from sentinel.feed import calendar


DEFENSIVE_SECURITY_ID = "SENTINEL:BIL"
DATA_SEMANTICS_IDENTITY_SCHEMA = "sentinel-sharadar-book-semantics/v1"
_DATA_SEMANTICS_MODULES = (
    "sentinel.breadth.classifier",
    "sentinel.breadth.returns",
    "sentinel.controller.concordance",
    "sentinel.controller.concordance_parent",
    "sentinel.controller.frozen_rule",
    "sentinel.controller.ldrc",
    "sentinel.controller.machine",
    "sentinel.controller.recent_leadership",
    "sentinel.core.bootstrap",
    "sentinel.core.catchup",
    "sentinel.core.decision",
    "sentinel.core.loader",
    "sentinel.core.production",
    "sentinel.core.terminal",
    "sentinel.execution.plan",
    "sentinel.execution.projection",
    "sentinel.execution.reconcile",
    "sentinel.execution.target_reprojection",
    "sentinel.feed.action_source",
    "sentinel.feed.actions",
    "sentinel.feed.actions_map",
    "sentinel.feed.anomalies",
    "sentinel.feed.calendar",
    "sentinel.feed.domains",
    "sentinel.feed.ingest",
    "sentinel.feed.ingest_impl",
    "sentinel.feed.maintenance",
    "sentinel.feed.publication",
    "sentinel.feed.repair",
    "sentinel.feed.recovery",
    "sentinel.feed.renormalize",
    "sentinel.feed.reseed",
    "sentinel.feed.sep_reconciliation",
    "sentinel.feed.sharadar",
    "sentinel.feed.snapshot_export",
    "sentinel.feed.snapshot_source",
    "sentinel.feed.staging",
    "sentinel.feed.store",
    "sentinel.feed.universe",
    "sentinel.feed.universe_projection",
    "sentinel.paper",
    "sentinel.regime.spy",
    "sentinel.shadow_observation",
    "sentinel.shadow_runtime",
    "stock_strategy_shared.split_reconciliation",
    "stock_strategy_shared.terminal_coalescing",
    "stock_strategy_shared.wealth_core.sharadar_domains",
)


@dataclass(frozen=True)
class ShadowTarget:
    """Canonical Wealth Core shares and the intent lineage that produced them.

    The aggregate is sufficient at the decision close, but it is not sufficient
    across an overnight corporate action.  Held shares and pending closes keep
    fractional split entitlements; a pending open is still a whole-share entry
    and Wealth Core cancels it if the transformed quantity is fractional.  Keep
    those components bound to the canonical state so execution cannot flatten
    away the distinction and resurrect a cancelled entry.
    """

    shares: Mapping[str, Decimal]
    tickers: Mapping[str, str]
    held_shares: Mapping[str, Decimal] = field(default_factory=dict)
    pending_open_shares: Mapping[str, tuple[Decimal, ...]] = field(
        default_factory=dict)
    pending_close_shares: Mapping[str, tuple[Decimal, ...]] = field(
        default_factory=dict)


@dataclass(frozen=True)
class ProductionDecision:
    """The immutable plan and the evidence needed to inspect its sizing."""

    plan: ExecutionPlan
    projection: Projection
    target_tickers: Mapping[str, str]


# A descriptive alias for callers that do not need to name the environment.
DecisionResult = ProductionDecision


def _canonical_hash(value) -> str:
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def data_semantics_source_identity() -> dict[str, object]:
    """Hash every reviewed source boundary that turns Sharadar into a book.

    A corpus version names the published rows, not the decoder that assigned
    their economic domains. Keep this bundle deliberately explicit so a
    split-orientation, effective-date, price-domain, overlay, terminal, or
    loader change makes persisted path-dependent state stale instead of
    silently advancing it under new semantics.
    """
    files = []
    for module_name in _DATA_SEMANTICS_MODULES:
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        if not module_file:
            raise RuntimeError(
                f"data-semantics module {module_name} has no source path")
        path = Path(module_file).resolve()
        if not path.is_file():
            raise RuntimeError(
                f"data-semantics source {module_name} is not a file: {path}")
        files.append({
            "module": module_name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    payload = {
        "schema": DATA_SEMANTICS_IDENTITY_SCHEMA,
        "files": files,
    }
    return {**payload, "sha256": _canonical_hash(payload)}


def _as_mapping(value, *, label: str) -> Mapping:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        if isinstance(raw, Mapping):
            return raw
    raise TypeError(f"{label} must be a mapping or expose to_dict()")


def _decimal(value, *, label: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not a Decimal-compatible value") from exc
    return converted


def _positive_finite(value) -> bool:
    return (isinstance(value, Decimal) and value.is_finite()
            and value > Decimal(0))


def publication_fingerprint(publication) -> str:
    """Hash the complete pinned publication record, including its evidence."""

    return _canonical_hash(_as_mapping(publication, label="publication"))


def runtime_strategy_identity(
        controller_config, *, concordance: bool = False
        ) -> dict[str, str]:
    """Name every source that can change the durable allocation path."""

    package_file = getattr(wealth_core_package, "__file__", None)
    package_root = Path(package_file).resolve().parent if package_file else None
    source = identity.source_hash(package_root)
    source_digest = source.get("hash")
    if not source_digest or not source.get("files"):
        raise RuntimeError(
            "the imported Wealth Core source cannot be fingerprinted; refusing "
            "to create an incomplete production strategy identity")
    result = {
        "strategy": str(controller_config.strategy_id),
        "controller_rule_sha256": str(controller_config.digest),
        "wealth_core_source_sha256": str(source_digest),
        "data_semantics_source_sha256": str(
            data_semantics_source_identity()["sha256"]),
    }
    if not concordance:
        return result
    from sentinel.controller import ldrc as ldrc_module
    from sentinel.controller import recent_leadership as leadership_module
    from sentinel.controller.concordance_parent import (
        STRATEGY_ID as CONCORDANCE_PARENT_STRATEGY_ID)
    if controller_config.strategy_id != CONCORDANCE_PARENT_STRATEGY_ID:
        raise ValueError(
            "Concordance identity requires the hardened 30pp parent")
    def module_sha(module) -> str:
        module_file = Path(module.__file__).resolve()
        return hashlib.sha256(module_file.read_bytes()).hexdigest()
    result.update({
        IDENTITY_OVERLAY_FIELD: ldrc_module.STRATEGY_ID,
        "allocation_overlay_version": str(ldrc_module.STRATEGY_VERSION),
        "allocation_overlay_source_sha256": module_sha(ldrc_module),
        "recent_leadership_source_sha256": module_sha(leadership_module),
    })
    return result


def _canonical_state(state: SessionState | Mapping) -> SessionState:
    if isinstance(state, SessionState):
        return SessionState.from_dict(state.to_dict())
    return SessionState.from_dict(state)


def _record_ticker(tickers: dict[str, str], security_id: str,
                   ticker: str) -> None:
    security_id = str(security_id)
    ticker = str(ticker)
    prior = tickers.get(security_id)
    if prior is not None and prior != ticker:
        raise ValueError(
            f"security {security_id!r} has conflicting canonical tickers "
            f"{prior!r} and {ticker!r}")
    tickers[security_id] = ticker


def shadow_target(state: SessionState | Mapping) -> ShadowTarget:
    """Aggregate filled episodes and signed canonical pending operations.

    A queued close is subtracted because it is already part of Wealth Core's
    immutable next-open intention. Broker positions are deliberately absent.
    """

    canonical = _canonical_state(state)
    portfolio = PortfolioState.from_dict(canonical.wealth_core)
    shares: dict[str, Decimal] = {}
    tickers: dict[str, str] = {}
    held_shares: dict[str, Decimal] = {}
    pending_opens: dict[str, list[Decimal]] = {}
    pending_closes: dict[str, list[Decimal]] = {}

    for slot_id in sorted(portfolio.episodes):
        episode = portfolio.episodes[slot_id]
        security_id = str(episode.security_id)
        quantity = _decimal(
            episode.current_shares,
            label=f"episode {slot_id} current_shares")
        if not quantity.is_finite() or quantity < 0:
            raise ValueError(
                f"episode {slot_id} has invalid long-only shares {quantity}")
        shares[security_id] = shares.get(security_id, Decimal(0)) + quantity
        held_shares[security_id] = (
            held_shares.get(security_id, Decimal(0)) + quantity)
        _record_ticker(tickers, security_id, episode.ticker)

    for raw in canonical.pending:
        pending = PendingOrder.from_dict(dict(raw))
        security_id = str(pending.security_id)
        quantity = _decimal(
            pending.shares,
            label=f"pending {pending.operation.value} shares for {security_id}")
        if not quantity.is_finite() or quantity < 0:
            raise ValueError(
                f"pending operation for {security_id!r} has invalid shares "
                f"{quantity}")
        if pending.operation is Operation.OPEN_SLOT_POSITION:
            signed = quantity
            pending_opens.setdefault(security_id, []).append(quantity)
        elif pending.operation is Operation.CLOSE_POSITION:
            signed = -quantity
            pending_closes.setdefault(security_id, []).append(quantity)
        else:
            raise ValueError(
                f"pending operation {pending.operation.value!r} is not a "
                "share-level open or close")
        shares[security_id] = shares.get(security_id, Decimal(0)) + signed
        _record_ticker(tickers, security_id, pending.ticker)

    negative = {security_id: quantity
                for security_id, quantity in shares.items()
                if quantity < 0}
    if negative:
        raise ValueError(
            f"canonical pending operations over-close the shadow: {negative}")

    return ShadowTarget(
        shares={security_id: quantity
                for security_id, quantity in sorted(shares.items())
                if quantity > 0},
        tickers=dict(sorted(tickers.items())),
        held_shares=dict(sorted(held_shares.items())),
        pending_open_shares={
            security_id: tuple(quantities)
            for security_id, quantities in sorted(pending_opens.items())},
        pending_close_shares={
            security_id: tuple(quantities)
            for security_id, quantities in sorted(pending_closes.items())})


def _publication_version(publication) -> int:
    if isinstance(publication, Mapping):
        value = publication.get("version")
    else:
        value = getattr(publication, "version", None)
    if value is None:
        raise ValueError("publication has no version")
    return int(value)


def _current_marks(marks: Mapping) -> dict[str, Decimal]:
    converted: dict[str, Decimal] = {}
    for security_id, value in marks.items():
        if value is None:
            continue
        converted[str(security_id)] = _decimal(
            value, label=f"mark for {security_id}")
    return converted


def _shadow_equity(canonical: SessionState) -> Decimal:
    evidence = canonical.last_evidence or {}
    wealth_evidence = evidence.get("wealth_core") or {}
    if "estimated_equity" not in wealth_evidence:
        raise ValueError(
            "canonical state has no Wealth Core estimated_equity evidence")
    equity = _decimal(
        wealth_evidence["estimated_equity"],
        label="Wealth Core estimated_equity")
    if not _positive_finite(equity):
        raise ValueError(
            f"Wealth Core estimated_equity must be positive and finite, got "
            f"{equity}")
    return equity


def _canonical_stale_marks(canonical: SessionState) -> dict[str, Decimal]:
    return {
        str(security_id): _decimal(
            value, label=f"stale mark for {security_id}")
        for security_id, value in canonical.last_known.items()
    }


def _decision_mark(security_id: str, current_marks: Mapping[str, Decimal],
                   stale_marks: Mapping[str, Decimal]) -> Decimal | None:
    current = current_marks.get(security_id)
    stale = stale_marks.get(security_id)
    return (current if _positive_finite(current)
            else stale if _positive_finite(stale) else None)


def _shadow_weights(canonical: SessionState, target: ShadowTarget,
                    current_marks: Mapping[str, Decimal]) -> dict[str, Decimal]:
    equity = _shadow_equity(canonical)
    stale_marks = _canonical_stale_marks(canonical)
    weights: dict[str, Decimal] = {}
    for security_id, quantity in target.shares.items():
        mark = _decision_mark(security_id, current_marks, stale_marks)
        # Keep a zero-weight member when no current or canonical stale mark
        # exists. Projection names it unpriced; the share-space cap below can
        # still authorize a reduction without inventing a price.
        weights[security_id] = (
            quantity * mark / equity if mark is not None else Decimal(0))
    return weights


def _decision_close_nav(
        canonical: SessionState, account_snapshot, observation,
        current_marks: Mapping[str, Decimal],
        ) -> tuple[Decimal, tuple[str, ...]]:
    """Value as much of the live broker book as close evidence permits.

    Broker-reported equity is a later mark-to-market fact. Mixing it with
    decision-session close weights turns after-hours price movement into a new
    economic decision. Cash is not price-valued, so current broker cash is
    combined with observed positions valued at the pinned decision mark or the
    same canonical stale fallback Wealth Core itself carries.

    A held name with no usable close-domain mark is NAMED and omitted from this
    valuation rather than substituted with broker M2M. That makes this NAV a
    conservative known-value basis in the long-only book. The unpriced-share
    logic below may still reduce such a name, but cannot use missing evidence to
    increase it. This is the required asymmetry: a missing mark may block an
    increase, never a required trim.
    """

    cash = _decimal(account_snapshot.cash, label="broker account cash")
    if not cash.is_finite():
        raise ValueError(f"broker account cash must be finite, got {cash}")
    stale_marks = _canonical_stale_marks(canonical)
    nav = cash
    unpriced: list[str] = []
    for security_id, quantity in observation.positions_by_security().items():
        quantity = _decimal(
            quantity, label=f"held quantity for {security_id}")
        if not quantity.is_finite():
            raise ValueError(
                f"held quantity for {security_id!r} must be finite, got "
                f"{quantity}")
        mark = _decision_mark(security_id, current_marks, stale_marks)
        if mark is None:
            unpriced.append(security_id)
            continue
        nav += quantity * mark
    if not nav.is_finite() or nav < 0:
        raise ValueError(
            f"known decision-close-valued broker NAV must be non-negative and "
            f"finite, got {nav}")
    return nav, tuple(sorted(unpriced))


def _cap_unpriced_increases(
        projection: Projection, target: ShadowTarget, observation,
        *, shadow_equity: Decimal, nav: Decimal, exposure: Decimal,
        defensive_weight: Decimal, defensive_security: str | None,
        lot: Decimal = Decimal(1)) -> Projection:
    """Missing price evidence may block an increase, never a required Core trim.

    A Core share target does not need its own price once both book NAVs are in
    the same decision-close domain: the mark cancels algebraically. Therefore an
    unpriced Core name can be capped at its exposure-scaled shadow quantity in
    SHARE space. `min(current committed book, target)` prevents the missing mark
    from authorizing a buy while still allowing partial or full de-risking.
    """

    positions = observation.positions_by_security()
    quantities = dict(projection.quantities)
    defensive_quantity = projection.defensive_quantity

    wanted = set(target.shares)
    if defensive_security is not None and defensive_weight > 0:
        wanted.add(defensive_security)
    for security_id in sorted(set(projection.unpriced) & wanted):
        held = _decimal(
            positions.get(security_id, Decimal(0)),
            label=f"held quantity for {security_id}")
        committed = committed_quantity(
            observation.working_orders_for(security_id))
        current = held + committed
        if not current.is_finite() or current < 0:
            raise ValueError(
                f"unpriced {security_id!r} has invalid held plus committed "
                f"quantity {current}")

        if security_id == defensive_security:
            # A defensive target is defined in notional, so without its own
            # price a partial share target cannot be derived safely. Preserve
            # the already-committed amount; a zero defensive weight is handled
            # by `project` directly and therefore still liquidates fully.
            defensive_quantity = current
            continue

        scaled = (
            target.shares[security_id] * exposure * nav / shadow_equity / lot
        ).to_integral_value(rounding=ROUND_DOWN) * lot
        desired = min(current, scaled)
        if desired > 0:
            quantities[security_id] = desired
        else:
            quantities.pop(security_id, None)

    return replace(
        projection, quantities=dict(sorted(quantities.items())),
        defensive_quantity=defensive_quantity)


def build_execution_plan(
        state: SessionState | Mapping, binding, publication, account_snapshot,
        observation, marks: Mapping, tickers: Mapping,
        decision_session: date, effective_session: date, *,
        defensive_security: str | None = DEFENSIVE_SECURITY_ID,
        rollout_state: RolloutState | None = None,
        ) -> ProductionDecision:
    """Convert the durable current shadow/controller decision into one plan."""

    if binding is None or not bool(getattr(binding, "is_owned", False)):
        raise AccountNotBound(
            "a production plan requires an established SENTINEL_OWNED binding")
    observed_identity = getattr(account_snapshot, "identity", None)
    if not binding.identity.matches_account(observed_identity):
        raise AccountMismatch(
            "the typed broker account snapshot does not match the durable "
            "Sentinel account binding")
    observation.require_complete("production plan preparation")

    canonical = _canonical_state(state)
    if canonical.last_processed_session != decision_session.isoformat():
        raise ValueError(
            "decision_session does not match canonical last_processed_session")
    expected_effective = date.fromisoformat(
        calendar.next_session(decision_session))
    if effective_session != expected_effective:
        raise ValueError(
            f"effective_session must be the next XNYS session "
            f"{expected_effective}, got {effective_session}")
    if canonical.data_version != _publication_version(publication):
        raise ValueError(
            "canonical state data_version does not match the pinned publication")
    if not canonical.last_decision:
        raise ValueError("canonical state has no controller decision")
    if canonical.last_decision.get("session") != decision_session.isoformat():
        raise ValueError(
            "controller transition session does not match decision_session")

    controller_exposure = _decimal(
        canonical.last_decision.get("target_core_exposure"),
        label="controller target_core_exposure")
    if (not controller_exposure.is_finite()
            or not Decimal(0) <= controller_exposure <= Decimal(1)):
        raise ValueError("controller target_core_exposure is not finite")
    rollout = rollout_state or RolloutState(
        mode=RolloutMode.PINNED_1_00, version=1)
    if (is_concordance_identity(canonical.strategy_identity)
            and rollout.mode is RolloutMode.PINNED_1_00):
        raise ValueError(
            "PINNED_1_00 cannot override a Concordance allocation; "
            "use a separately certified CONTROLLER rollout")
    exposure = (Decimal(1) if rollout.mode is RolloutMode.PINNED_1_00
                else controller_exposure)
    defensive_weight = Decimal(1) - exposure
    current_marks = _current_marks(marks)
    target = shadow_target(canonical)
    shadow_equity = _shadow_equity(canonical)
    nav, nav_unpriced = _decision_close_nav(
        canonical, account_snapshot, observation, current_marks)
    weights = _shadow_weights(canonical, target, current_marks)

    sized = project(
        shadow_weights=weights, exposure=exposure, nav=nav,
        marks=current_marks, defensive_security=defensive_security,
        defensive_weight=defensive_weight)
    if nav_unpriced:
        sized = replace(
            sized,
            unpriced=tuple(sorted(set(sized.unpriced) | set(nav_unpriced))))
    sized = _cap_unpriced_increases(
        sized, target, observation, shadow_equity=shadow_equity, nav=nav,
        exposure=exposure, defensive_weight=defensive_weight,
        defensive_security=defensive_security)
    basket = desired_basket(sized)
    # A working order is economic state even when the position has not appeared
    # yet and the fresh target no longer contains the name. Give it an explicit
    # zero target so exact-delta reconciliation cannot omit it from the universe.
    for order in observation.orders:
        if order.is_working:
            basket.setdefault(order.instrument.security_id, Decimal(0))

    target_tickers = {str(security_id): str(ticker)
                      for security_id, ticker in tickers.items()}
    target_tickers.update(target.tickers)
    for order in observation.orders:
        if order.is_working:
            target_tickers.setdefault(
                order.instrument.security_id, order.instrument.symbol)
    if defensive_security is not None:
        target_tickers.setdefault(
            defensive_security,
            "BIL" if defensive_security == DEFENSIVE_SECURITY_ID
            else defensive_security)
    target_tickers = {
        security_id: target_tickers[security_id]
        for security_id in sorted(set(basket) | set(target.shares))
        if security_id in target_tickers
    }

    account_cash = _decimal(
        account_snapshot.cash, label="broker account cash")
    plan = ExecutionPlan(
        plan_id="pending",
        decision_session=decision_session,
        effective_session=effective_session,
        target_exposure=exposure,
        target_basket=dict(sorted(basket.items())),
        data_version=canonical.data_version,
        shadow_snapshot_hash=canonical.state_hash,
        sentinel_transition_hash=_canonical_hash(canonical.last_decision),
        strategy_fingerprint=_canonical_hash(canonical.strategy_identity),
        deployment_id=str(binding.deployment_id),
        broker=str(binding.broker),
        broker_account_id=str(binding.broker_account_id),
        takeover_epoch=int(binding.takeover_epoch),
        publication_fingerprint=publication_fingerprint(publication),
        account_nav=nav,
        account_cash=account_cash,
        cash_residual=sized.cash_residual,
        unpriced_securities=tuple(sorted(sized.unpriced)),
        defensive_security=defensive_security,
        rollout_mode=rollout.mode.value,
        rollout_version=rollout.version,
        rollout_certificate_sha256=rollout.certificate_sha256,
    )
    plan = replace(plan, plan_id=f"sentinel-{plan.fingerprint()}")
    return ProductionDecision(
        plan=plan, projection=sized, target_tickers=target_tickers)


__all__ = [
    "DATA_SEMANTICS_IDENTITY_SCHEMA", "DEFENSIVE_SECURITY_ID",
    "DecisionResult", "ProductionDecision",
    "ShadowTarget", "build_execution_plan", "publication_fingerprint",
    "data_semantics_source_identity", "runtime_strategy_identity",
    "shadow_target",
]
