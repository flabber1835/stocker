"""Read-only paper broker/account inspection and identity evidence."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from typing import Mapping, Optional

from sentinel import (
    binding as binding_mod,
    dual_plan_authority,
    identity as system_identity,
    informational_paper_mirror,
    schema,
    trial,
    trial_close,
    trial_fills,
)

from sentinel.config import DEFAULT_BASE_URL, assert_paper_url

from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution.certification import require_certified

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
    PaperAccountInspection,
)

DEFENSIVE_SYMBOL = "BIL"

def _require_certified_paper_broker(broker: ExecutionBroker) -> None:
    """Accept only adapter identities whose behavior is certified.

    Production receives :class:`AlpacaExecutionBroker`; tests receive the
    deterministic simulator. Treating every unknown implementation as the
    simulator would let an unlisted transport borrow a certification it never
    earned merely by choosing a different class name.
    """
    from sentinel.guarded_administration import (
        GuardedAdministrativeExecutionBroker)

    if isinstance(broker, GuardedAdministrativeExecutionBroker):
        # This one explicit read-only wrapper validated its concrete adapter at
        # construction and exposes only a certification recheck, never its
        # transport object. Arbitrary duck-typed wrappers remain refused.
        broker.require_certified_adapter()
        return

    certification_name = broker.certification_name
    if certification_name in {"alpaca", "simulator"}:
        require_certified(certification_name)
        return
    raise PaperActivationRefused(
        f"unsupported execution broker {type(broker).__name__}; the paper "
        "activation path accepts only the certified Alpaca adapter (or the "
        "deterministic simulator in tests)")

def _inspection_account_or_refuse(
        snapshot: BrokerAccountSnapshot, expected_account: str) -> None:
    """Validate the inspection payload without turning status into authority.

    A blocked or inactive account is useful inspection evidence and is printed
    for the operator. Missing, non-typed, or non-finite fields are not evidence
    at all and therefore refuse the checkpoint.
    """
    if not expected_account:
        raise PaperActivationRefused(
            "paper-account inspection requires the exact expected account id")
    identity = snapshot.identity
    if not identity.broker or not identity.account_id:
        raise PaperActivationRefused(
            "paper-account inspection received a malformed account identity")
    if identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {identity.account_id}, expected "
            f"{expected_account}")
    values = {
        "equity": snapshot.equity,
        "cash": snapshot.cash,
        "buying_power": snapshot.buying_power,
        "multiplier": snapshot.multiplier,
    }
    malformed_values = [
        name for name, value in values.items()
        if not isinstance(value, Decimal) or not value.is_finite()]
    if malformed_values:
        raise PaperActivationRefused(
            "paper-account inspection received malformed Decimal fields: "
            + ", ".join(malformed_values))
    if not isinstance(snapshot.status, str) or not snapshot.status.strip():
        raise PaperActivationRefused(
            "paper-account inspection received a missing account status")
    flags = (
        "trading_blocked", "account_blocked", "trade_suspended_by_user")
    malformed_flags = [
        name for name in flags if type(getattr(snapshot, name)) is not bool]
    if malformed_flags:
        raise PaperActivationRefused(
            "paper-account inspection received non-boolean block flags: "
            + ", ".join(malformed_flags))

async def inspect_paper_account(*, conn, broker: ExecutionBroker,
                                base_url: str,
                                expected_account: str
                                ) -> PaperAccountInspection:
    """Read the exact inherited book without acquiring mutation authority."""
    assert_paper_url(base_url)
    _require_certified_paper_broker(broker)

    account = await broker.account_snapshot()
    _inspection_account_or_refuse(account, expected_account)
    observation = await broker.observe()
    observation.require_complete("paper-account inspection")
    if observation.observed_at.tzinfo is None:
        raise PaperActivationRefused(
            "paper-account inspection received a naive observation timestamp")

    # Inspection is deliberately available before the Sentinel behavior schema
    # has ever been installed.  Asking PostgreSQL whether the relation exists
    # is a read; calling ``schema.ensure_schema`` here would turn the mandatory
    # pre-migration checkpoint into a hidden state-changing bootstrap command.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass('public.sentinel_account_binding')")
        binding_relation = cur.fetchone()[0]
    binding = (binding_mod.load(conn)
               if binding_relation is not None else None)
    if binding is not None:
        if not binding.is_owned:
            raise PaperActivationRefused(
                f"canonical binding has unsupported ownership state "
                f"{binding.ownership_state!r}")
        if not binding.identity.matches_account(account.identity):
            raise PaperActivationRefused(
                f"canonical binding names {binding.broker}/"
                f"{binding.broker_account_id}, but the broker reports "
                f"{account.identity.broker}/{account.identity.account_id}")

    return PaperAccountInspection(
        endpoint=base_url, expected_account=expected_account,
        account=account, observation=observation, binding=binding)

def _account_evidence_is_quiescent(
        conn, *, deployment, observation: BrokerObservation) -> bool:
    """Only a settled book can bind a later account snapshot to this read."""
    if observation is None or not observation.is_complete:
        return False
    if any(order.is_working for order in observation.orders):
        return False
    return not journal.in_flight_commands(conn, deployment)

def _account_or_refuse(snapshot: BrokerAccountSnapshot, binding,
                       expected_account: Optional[str]) -> None:
    if not binding.identity.matches_account(snapshot.identity):
        raise PaperActivationRefused(
            f"broker identity {snapshot.identity.broker}/"
            f"{snapshot.identity.account_id} does not match binding "
            f"{binding.broker}/{binding.broker_account_id}")
    if expected_account and snapshot.identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {snapshot.identity.account_id}, "
            f"expected {expected_account}")
    if (not snapshot.equity.is_finite() or snapshot.equity <= 0
            or not snapshot.cash.is_finite() or snapshot.cash < 0
            or snapshot.buying_power is None
            or not snapshot.buying_power.is_finite()
            or snapshot.buying_power < 0
            or snapshot.multiplier is None
            or not snapshot.multiplier.is_finite()):
        raise PaperActivationRefused(
            f"account sizing facts are unusable: equity={snapshot.equity}, "
            f"cash={snapshot.cash}, buying_power={snapshot.buying_power}, "
            f"multiplier={snapshot.multiplier}")
    if snapshot.multiplier != Decimal(1):
        raise PaperActivationRefused(
            f"paper account multiplier is {snapshot.multiplier}, not 1. "
            "Sentinel requires a cash-only paper account and will not rely on "
            "margin to make a DAY market order affordable")
    if snapshot.status.upper() != "ACTIVE":
        raise PaperRetryableRefused(
            f"paper account status is {snapshot.status!r}, not ACTIVE")
    blocked = [
        name for name in (
            "trading_blocked", "account_blocked", "trade_suspended_by_user")
        if getattr(snapshot, name)
    ]
    if blocked:
        raise PaperRetryableRefused(
            "paper account is not available for submission: "
            + ", ".join(blocked))
    if abs(snapshot.buying_power - snapshot.cash) > Decimal("1.00"):
        error = (PaperRetryableRefused
                 if snapshot.buying_power < snapshot.cash
                 else PaperActivationRefused)
        raise error(
            f"paper account buying power {snapshot.buying_power} does not "
            f"match cash {snapshot.cash}. Lower buying power is unsettled; "
            "higher buying power exposes margin. Increases wait for cash-only "
            "settlement")

def _recovery_account_identity_or_refuse(
        snapshot: BrokerAccountSnapshot, binding,
        expected_account: str) -> None:
    """Prove identity without applying submission-time account economics."""
    if not binding.identity.matches_account(snapshot.identity):
        raise PaperActivationRefused(
            f"broker identity {snapshot.identity.broker}/"
            f"{snapshot.identity.account_id} does not match binding "
            f"{binding.broker}/{binding.broker_account_id}")
    if snapshot.identity.account_id != expected_account:
        raise PaperActivationRefused(
            f"connected to paper account {snapshot.identity.account_id}, "
            f"expected {expected_account}")

def build_security_resolver(conn, session: str):
    """Point-in-time broker symbol -> permanent execution identity."""
    from sentinel.feed.universe import load_resolver
    resolver = load_resolver(conn)

    def resolve(symbol: str, as_of: str | None = None):
        if str(symbol).upper() == DEFENSIVE_SYMBOL:
            return DEFENSIVE_SECURITY_ID
        return resolver.resolve(str(symbol), as_of or session)

    return resolve
