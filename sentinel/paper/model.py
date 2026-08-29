"""Paper lifecycle exceptions and machine-readable result models."""

from __future__ import annotations

from dataclasses import dataclass

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

from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    ExecutionBroker,
    MalformedBrokerEvidence,
)

from sentinel.execution.guarded import (
    AutomationExecutionGrant,
    BrokerAuthorityRefused,
    BrokerOperation,
    GuardedExecutionBroker,
    ManualExecutionGrant,
    PaperPreparationGrant,
)

from sentinel.execution.plan import ExecutionPlan

from sentinel.execution.states import RuntimeState

class PaperActivationRefused(BrokerAuthorityRefused):
    """A preparation or execution authority check failed."""

class PaperRetryableRefused(PaperActivationRefused):
    """Temporary readiness or settlement evidence is not yet usable."""

class PreOpenShareUnitAuthorityUnavailable(PaperActivationRefused):
    """The exact next-open units needed for safe transport are unavailable."""

@dataclass(frozen=True)
class PaperAccountInspection:
    """One complete, read-only view of the named inherited paper account."""

    endpoint: str
    expected_account: str
    account: BrokerAccountSnapshot
    observation: BrokerObservation
    binding: Optional[binding_mod.AccountBinding]

    @property
    def approval_blockers(self) -> tuple[str, ...]:
        """Well-formed facts that make migration approval unsafe.

        These remain visible rather than raising: inspection is the place an
        operator needs to learn that the account is blocked or unsettled.
        Malformed evidence and identity uncertainty are refused before this
        object exists.
        """
        account = self.account
        blockers: list[str] = []
        if account.status.upper() != "ACTIVE":
            blockers.append(f"account_status:{account.status}")
        blockers.extend(
            name for name in (
                "trading_blocked", "account_blocked",
                "trade_suspended_by_user")
            if getattr(account, name))
        if account.multiplier != Decimal(1):
            blockers.append(f"cash_only_multiplier:{account.multiplier}")
        if account.equity <= 0:
            blockers.append(f"nonpositive_equity:{account.equity}")
        if account.cash < 0:
            blockers.append(f"negative_cash:{account.cash}")
        if account.buying_power < 0:
            blockers.append(f"negative_buying_power:{account.buying_power}")
        if abs(account.buying_power - account.cash) > Decimal("1.00"):
            relation = ("unsettled_buying_power" if account.buying_power
                        < account.cash else "margin_buying_power")
            blockers.append(
                f"{relation}:{account.buying_power}:cash:{account.cash}")
        if self.binding is not None:
            blockers.append(
                f"account_already_bound:{self.binding.ownership_state}")
        return tuple(blockers)

    def to_dict(self) -> dict:
        account = self.account
        positions = sorted(
            self.observation.positions,
            key=lambda position: (
                position.instrument.security_id,
                position.instrument.symbol,
                position.instrument.broker_id or ""))
        working_orders = sorted(
            (order for order in self.observation.orders if order.is_working),
            key=lambda order: (
                order.broker_order_id,
                order.client_key or ""))
        return {
            "inspection_only": True,
            "broker_mutations_permitted": False,
            "approval_ready": not self.approval_blockers,
            "approval_blockers": list(self.approval_blockers),
            "endpoint": self.endpoint,
            "expected_account": self.expected_account,
            "account": {
                "broker": account.identity.broker,
                "account_id": account.identity.account_id,
                "status": account.status,
                "trading_blocked": account.trading_blocked,
                "account_blocked": account.account_blocked,
                "trade_suspended_by_user": account.trade_suspended_by_user,
                "multiplier": str(account.multiplier),
                "equity": str(account.equity),
                "cash": str(account.cash),
                "buying_power": str(account.buying_power),
            },
            "binding_state": (
                self.binding.ownership_state if self.binding else "UNBOUND"),
            "binding_matches_account": (
                True if self.binding is not None else None),
            "binding": self.binding.to_dict() if self.binding else None,
            "observation_complete": True,
            "observed_at": self.observation.observed_at.isoformat(),
            "positions": [
                {
                    "security_id": position.instrument.security_id,
                    "symbol": position.instrument.symbol,
                    "broker_instrument_id": position.instrument.broker_id,
                    "quantity": str(position.quantity),
                }
                for position in positions
            ],
            "working_open_orders": [
                {
                    "broker_order_id": order.broker_order_id,
                    "client_key": order.client_key,
                    "security_id": order.instrument.security_id,
                    "symbol": order.instrument.symbol,
                    "broker_instrument_id": order.instrument.broker_id,
                    "side": order.side.value,
                    "state": order.state.value,
                    "quantity": str(order.quantity),
                    "filled_quantity": str(order.filled_quantity),
                    "remaining_quantity": str(order.remaining),
                    "submitted_at": (
                        order.submitted_at.isoformat()
                        if order.submitted_at is not None else None),
                }
                for order in working_orders
            ],
        }

@dataclass(frozen=True)
class PreparationResult:
    plan: ExecutionPlan
    sessions_replayed: int
    warmup_sessions: int
    state_fingerprint: str
    publication_version: int
    frontier: str
    reconciliation: object
    superseded_plans: int = 0

    def to_dict(self) -> dict:
        return {
            "dry_run": True,
            "broker_mutations_permitted": False,
            "sessions_replayed": self.sessions_replayed,
            "warmup_sessions": self.warmup_sessions,
            "frontier": self.frontier,
            "publication_version": self.publication_version,
            "state_fingerprint": self.state_fingerprint,
            "superseded_plans": self.superseded_plans,
            "plan": self.plan.to_dict(),
            "reconciliation": self.reconciliation.to_dict(),
        }

@dataclass(frozen=True)
class ExecutionResult:
    plan: ExecutionPlan
    preflight: object
    session: object

    @property
    def needs_attention(self) -> bool:
        terminal_bad = any(
            command.state.name in {"UNKNOWN", "REJECTED", "CANCELLED"}
            for command in self.session.submitted)
        return (self.session.runtime_state is not RuntimeState.RUNNING
                or bool(self.session.refused) or bool(self.session.deferred)
                or terminal_bad)

    def to_dict(self) -> dict:
        return {"paper_submission_authorized": not self.needs_attention,
                "operator_attention_required": self.needs_attention,
                "plan": self.plan.to_dict(),
                "preflight": self.preflight.to_dict(),
                "execution": self.session.to_dict()}
