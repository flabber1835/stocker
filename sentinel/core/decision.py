"""Pure production adapter from the canonical shadow to an execution plan.

Wealth Core owns the share target and the controller owns only its exposure.
This module joins those two durable decisions to a read-only broker observation;
it does not read a broker, persist a plan, or submit an order.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping

import stock_strategy_shared.wealth_core as wealth_core_package
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.state import PortfolioState

from sentinel import identity
from sentinel.binding import AccountMismatch, AccountNotBound
from sentinel.core.production import SessionState
from sentinel.execution.commands import committed_quantity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.projection import Projection, desired_basket, project
from sentinel.feed import calendar


DEFENSIVE_SECURITY_ID = "SENTINEL:BIL"


@dataclass(frozen=True)
class ShadowTarget:
    """Canonical Wealth Core shares after its queued next-open operations."""

    shares: Mapping[str, Decimal]
    tickers: Mapping[str, str]


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


def runtime_strategy_identity(controller_config) -> dict[str, str]:
    """Name the controller rule and the Wealth Core bytes actually imported."""

    package_file = getattr(wealth_core_package, "__file__", None)
    package_root = Path(package_file).resolve().parent if package_file else None
    source = identity.source_hash(package_root)
    source_digest = source.get("hash")
    if not source_digest or not source.get("files"):
        raise RuntimeError(
            "the imported Wealth Core source cannot be fingerprinted; refusing "
            "to create an incomplete production strategy identity")
    return {
        "strategy": str(controller_config.strategy_id),
        "controller_rule_sha256": str(controller_config.digest),
        "wealth_core_source_sha256": str(source_digest),
    }


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
    immutable next-open intention.  Broker positions are deliberately absent.
    """

    canonical = _canonical_state(state)
    portfolio = PortfolioState.from_dict(canonical.wealth_core)
    shares: dict[str, Decimal] = {}
    tickers: dict[str, str] = {}

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
        elif pending.operation is Operation.CLOSE_POSITION:
            signed = -quantity
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
        tickers=dict(sorted(tickers.items())))


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


def _shadow_weights(canonical: SessionState, target: ShadowTarget,
                    current_marks: Mapping[str, Decimal]) -> dict[str, Decimal]:
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

    stale_marks = {
        str(security_id): _decimal(value, label=f"stale mark for {security_id}")
        for security_id, value in canonical.last_known.items()
    }
    weights: dict[str, Decimal] = {}
    for security_id, quantity in target.shares.items():
        current = current_marks.get(security_id)
        stale = stale_marks.get(security_id)
        mark = (current if _positive_finite(current)
                else stale if _positive_finite(stale) else None)
        # Keep a zero-weight member when no current or canonical stale mark
        # exists.  Projection will name it unpriced and the preservation step
        # below prevents unavailable evidence becoming a liquidation order.
        weights[security_id] = (
            quantity * mark / equity if mark is not None else Decimal(0))
    return weights


def _preserve_unpriced(projection: Projection, target: ShadowTarget,
                       observation, defensive_weight: Decimal,
                       defensive_security: str | None) -> Projection:
    positions = observation.positions_by_security()
    quantities = dict(projection.quantities)
    defensive_quantity = projection.defensive_quantity

    wanted = set(target.shares)
    if defensive_security is not None and defensive_weight > 0:
        wanted.add(defensive_security)
    for security_id in sorted(set(projection.unpriced) & wanted):
        held = positions.get(security_id, Decimal(0))
        held = _decimal(held, label=f"held quantity for {security_id}")
        committed = committed_quantity(
            observation.working_orders_for(security_id))
        preserved = held + committed
        if not preserved.is_finite() or preserved < 0:
            raise ValueError(
                f"unpriced {security_id!r} has invalid held plus committed "
                f"quantity {preserved}")
        if security_id == defensive_security:
            defensive_quantity = preserved
        elif preserved > 0:
            quantities[security_id] = preserved
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

    exposure = _decimal(
        canonical.last_decision.get("target_core_exposure"),
        label="controller target_core_exposure")
    if not exposure.is_finite():
        raise ValueError("controller target_core_exposure is not finite")
    defensive_weight = Decimal(1) - exposure
    nav = _decimal(account_snapshot.equity, label="broker account equity")
    current_marks = _current_marks(marks)
    target = shadow_target(canonical)
    weights = _shadow_weights(canonical, target, current_marks)

    sized = project(
        shadow_weights=weights, exposure=exposure, nav=nav,
        marks=current_marks, defensive_security=defensive_security,
        defensive_weight=defensive_weight)
    sized = _preserve_unpriced(
        sized, target, observation, defensive_weight, defensive_security)
    basket = desired_basket(sized)

    target_tickers = {str(security_id): str(ticker)
                      for security_id, ticker in tickers.items()}
    target_tickers.update(target.tickers)
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
        account_cash=_decimal(
            account_snapshot.cash, label="broker account cash"),
        cash_residual=sized.cash_residual,
        unpriced_securities=tuple(sorted(sized.unpriced)),
        defensive_security=defensive_security,
    )
    plan = replace(plan, plan_id=f"sentinel-{plan.fingerprint()}")
    return ProductionDecision(
        plan=plan, projection=sized, target_tickers=target_tickers)


__all__ = [
    "DEFENSIVE_SECURITY_ID", "DecisionResult", "ProductionDecision",
    "ShadowTarget", "build_execution_plan", "publication_fingerprint",
    "runtime_strategy_identity", "shadow_target",
]
