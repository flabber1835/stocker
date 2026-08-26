"""Immutable one-way sizing authority for the informational PAPER mirror.

The certified shadow record supplies strategy intent. A complete, bound Alpaca
snapshot supplies only the account scale used by ``build_execution_plan``. This
module commits every economic sizing input and re-runs that canonical adapter
before a plan may cross the dual-run execution membrane. Current broker state is
deliberately not substituted for the retained sizing snapshot: fills and cash
activity are expected to move it after the plan was made.

A first PAPER plan after a causal shadow gap is stricter. While production
preparation explicitly enables the re-genesis sizing scope, the exact broker
observation used to build the immutable plan must already be flat and settled.
That check executes before plan adoption under PAPER's existing behavioral
writer lock. Therefore predecessor-strategy positions can never become an input
to a new segment's immutable sizing authority and cannot be rehabilitated later
merely by flattening the broker account.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from sentinel.core.decision import build_execution_plan
from sentinel.core.production import SessionState
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Completeness,
    Side,
)
from sentinel.execution.states import CommandState, IN_FLIGHT


SCHEMA = "sentinel.dual-plan-sizing-authority/1"
CURSOR_PREFIX = "dual-plan-sizing-authority:v1:"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REGENESIS_FLAT_SIZING_REQUIRED = ContextVar(
    "sentinel_dual_regenesis_flat_sizing_required", default=False)


class DualPlanAuthorityRefused(RuntimeError):
    """The retained sizing inputs are absent, mutable, or do not re-derive."""


@contextmanager
def regenesis_flat_sizing_scope(required: bool):
    """Task-local requirement for the first immutable post-gap PAPER sizing."""
    token = _REGENESIS_FLAT_SIZING_REQUIRED.set(bool(required))
    try:
        yield
    finally:
        _REGENESIS_FLAT_SIZING_REQUIRED.reset(token)


def regenesis_flat_sizing_required() -> bool:
    return bool(_REGENESIS_FLAT_SIZING_REQUIRED.get())


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DualPlanAuthorityRefused(
            "dual sizing authority is not canonical JSON") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _mapping(value: Any, *, where: str) -> dict:
    if isinstance(value, Mapping):
        return dict(value)
    method = getattr(value, "to_dict", None)
    if callable(method):
        result = method()
        if isinstance(result, Mapping):
            return dict(result)
    raise DualPlanAuthorityRefused(f"{where} is not a canonical mapping")


def _text(value: Any, *, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DualPlanAuthorityRefused(f"{where} must be a non-empty string")
    return value


def _decimal(value: Any, *, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - normalize the typed boundary
        raise DualPlanAuthorityRefused(f"{where} is not a Decimal") from exc
    if not result.is_finite():
        raise DualPlanAuthorityRefused(f"{where} must be finite")
    return result


def _timestamp(value: Any, *, where: str) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DualPlanAuthorityRefused(
            f"{where} is not an ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise DualPlanAuthorityRefused(f"{where} must be timezone-aware")
    return result


def _identity(value: BrokerAccountIdentity | None) -> dict | None:
    if value is None:
        return None
    return {"broker": str(value.broker), "account_id": str(value.account_id)}


def _instrument(value: BrokerInstrument) -> dict:
    return {
        "security_id": str(value.security_id),
        "symbol": str(value.symbol),
        "broker_id": None if value.broker_id is None else str(value.broker_id),
    }


def _account_payload(account: BrokerAccountSnapshot) -> dict:
    return {
        "identity": _identity(account.identity),
        "equity": str(account.equity),
        "cash": str(account.cash),
        "buying_power": (
            None if account.buying_power is None else str(account.buying_power)),
        "multiplier": (
            None if account.multiplier is None else str(account.multiplier)),
        "status": str(account.status),
        "trading_blocked": bool(account.trading_blocked),
        "account_blocked": bool(account.account_blocked),
        "trade_suspended_by_user": bool(account.trade_suspended_by_user),
    }


def _observation_payload(observation: BrokerObservation) -> dict:
    observation.require_complete("dual sizing authority")
    return {
        "observed_at": observation.observed_at.isoformat(),
        "started_at": (
            None if observation.started_at is None
            else observation.started_at.isoformat()),
        "terminal_recovery_through": (
            None if observation.terminal_recovery_through is None
            else observation.terminal_recovery_through.isoformat()),
        "completeness": observation.completeness.value,
        "account_identity": _identity(observation.account_identity),
        "positions": [
            {
                "instrument": _instrument(position.instrument),
                "quantity": str(position.quantity),
            }
            for position in sorted(
                observation.positions,
                key=lambda item: item.instrument.security_id)
        ],
        "orders": [
            {
                "broker_order_id": str(order.broker_order_id),
                "client_key": order.client_key,
                "instrument": _instrument(order.instrument),
                "side": order.side.value,
                "state": order.state.value,
                "quantity": str(order.quantity),
                "filled_quantity": str(order.filled_quantity),
                "filled_average_price": (
                    None if order.filled_average_price is None
                    else str(order.filled_average_price)),
                "submitted_at": (
                    None if order.submitted_at is None
                    else order.submitted_at.isoformat()),
                "external_replacement": bool(order.external_replacement),
            }
            for order in sorted(
                observation.orders,
                key=lambda item: (item.broker_order_id, item.client_key or ""))
        ],
    }


def _require_flat_regenesis_observation(observation: BrokerObservation) -> None:
    """Refuse predecessor book/order state as a new segment sizing input."""
    observation.require_complete("post-gap PAPER sizing")
    if observation.positions:
        raise DualPlanAuthorityRefused(
            "post-gap PAPER plan sizing requires a flat broker account; "
            "predecessor-strategy positions cannot seed fresh Wealth Core state")
    working = []
    replaced = []
    for order in observation.orders:
        if order.external_replacement:
            replaced.append(str(order.broker_order_id))
        if order.state in IN_FLIGHT:
            working.append(str(order.broker_order_id))
    if replaced:
        raise DualPlanAuthorityRefused(
            "post-gap PAPER plan sizing observed externally replaced order(s): "
            + ", ".join(sorted(replaced)[:8]))
    if working:
        raise DualPlanAuthorityRefused(
            "post-gap PAPER plan sizing still has working broker order(s): "
            + ", ".join(sorted(working)[:8]))


def _decode_identity(value: Any, *, where: str) -> BrokerAccountIdentity:
    raw = _mapping(value, where=where)
    if set(raw) != {"broker", "account_id"}:
        raise DualPlanAuthorityRefused(f"{where} has an unknown shape")
    return BrokerAccountIdentity(
        broker=_text(raw["broker"], where=f"{where}.broker"),
        account_id=_text(raw["account_id"], where=f"{where}.account_id"))


def _decode_instrument(value: Any, *, where: str) -> BrokerInstrument:
    raw = _mapping(value, where=where)
    if set(raw) != {"security_id", "symbol", "broker_id"}:
        raise DualPlanAuthorityRefused(f"{where} has an unknown shape")
    broker_id = raw["broker_id"]
    return BrokerInstrument(
        security_id=_text(raw["security_id"], where=f"{where}.security_id"),
        symbol=_text(raw["symbol"], where=f"{where}.symbol"),
        broker_id=(None if broker_id is None
                   else _text(broker_id, where=f"{where}.broker_id")))


def _decode_account(value: Any) -> BrokerAccountSnapshot:
    raw = _mapping(value, where="retained account snapshot")
    expected = {
        "identity", "equity", "cash", "buying_power", "multiplier",
        "status", "trading_blocked", "account_blocked",
        "trade_suspended_by_user",
    }
    if set(raw) != expected:
        raise DualPlanAuthorityRefused(
            "retained account snapshot has an unknown shape")
    for name in (
            "trading_blocked", "account_blocked", "trade_suspended_by_user"):
        if type(raw[name]) is not bool:
            raise DualPlanAuthorityRefused(
                f"retained account snapshot {name} is not boolean")
    return BrokerAccountSnapshot(
        identity=_decode_identity(raw["identity"], where="account identity"),
        equity=_decimal(raw["equity"], where="account equity"),
        cash=_decimal(raw["cash"], where="account cash"),
        buying_power=(
            None if raw["buying_power"] is None
            else _decimal(raw["buying_power"], where="account buying power")),
        multiplier=(
            None if raw["multiplier"] is None
            else _decimal(raw["multiplier"], where="account multiplier")),
        status=str(raw["status"]),
        trading_blocked=raw["trading_blocked"],
        account_blocked=raw["account_blocked"],
        trade_suspended_by_user=raw["trade_suspended_by_user"])


def _decode_observation(value: Any) -> BrokerObservation:
    raw = _mapping(value, where="retained broker observation")
    expected = {
        "observed_at", "started_at", "terminal_recovery_through",
        "completeness", "account_identity", "positions", "orders",
    }
    if set(raw) != expected:
        raise DualPlanAuthorityRefused(
            "retained broker observation has an unknown shape")
    try:
        completeness = Completeness(str(raw["completeness"]))
    except ValueError as exc:
        raise DualPlanAuthorityRefused(
            "retained broker completeness is unknown") from exc
    positions = []
    if not isinstance(raw["positions"], list):
        raise DualPlanAuthorityRefused("retained positions are not a list")
    for index, value in enumerate(raw["positions"]):
        item = _mapping(value, where=f"retained position {index}")
        if set(item) != {"instrument", "quantity"}:
            raise DualPlanAuthorityRefused(
                f"retained position {index} has an unknown shape")
        positions.append(BrokerPosition(
            instrument=_decode_instrument(
                item["instrument"], where=f"retained position {index}"),
            quantity=_decimal(
                item["quantity"], where=f"retained position {index} quantity")))
    orders = []
    if not isinstance(raw["orders"], list):
        raise DualPlanAuthorityRefused("retained orders are not a list")
    for index, value in enumerate(raw["orders"]):
        item = _mapping(value, where=f"retained order {index}")
        fields = {
            "broker_order_id", "client_key", "instrument", "side", "state",
            "quantity", "filled_quantity", "filled_average_price",
            "submitted_at", "external_replacement",
        }
        if set(item) != fields:
            raise DualPlanAuthorityRefused(
                f"retained order {index} has an unknown shape")
        try:
            side = Side(str(item["side"]))
            state = CommandState(str(item["state"]))
        except ValueError as exc:
            raise DualPlanAuthorityRefused(
                f"retained order {index} has an unknown state") from exc
        if type(item["external_replacement"]) is not bool:
            raise DualPlanAuthorityRefused(
                f"retained order {index} replacement flag is not boolean")
        orders.append(BrokerOrder(
            broker_order_id=_text(
                item["broker_order_id"],
                where=f"retained order {index} broker id"),
            client_key=(
                None if item["client_key"] is None
                else _text(item["client_key"],
                           where=f"retained order {index} client key")),
            instrument=_decode_instrument(
                item["instrument"], where=f"retained order {index}"),
            side=side, state=state,
            quantity=_decimal(
                item["quantity"], where=f"retained order {index} quantity"),
            filled_quantity=_decimal(
                item["filled_quantity"],
                where=f"retained order {index} filled quantity"),
            filled_average_price=(
                None if item["filled_average_price"] is None
                else _decimal(
                    item["filled_average_price"],
                    where=f"retained order {index} average price")),
            submitted_at=_timestamp(
                item["submitted_at"],
                where=f"retained order {index} submitted_at"),
            external_replacement=item["external_replacement"]))
    account_identity = raw["account_identity"]
    return BrokerObservation(
        observed_at=_timestamp(
            raw["observed_at"], where="retained observed_at"),
        started_at=_timestamp(
            raw["started_at"], where="retained started_at"),
        orders=tuple(orders), positions=tuple(positions),
        completeness=completeness,
        terminal_recovery_through=_timestamp(
            raw["terminal_recovery_through"],
            where="retained terminal recovery boundary"),
        account_identity=(
            None if account_identity is None
            else _decode_identity(
                account_identity, where="retained observation account")))


def build_authority(
        *, plan, shadow_result, publication, account_snapshot,
        observation, marks: Mapping, tickers: Mapping) -> dict:
    """Build the immutable evidence committed beside one PAPER plan."""
    state = getattr(shadow_result, "state", None)
    if not isinstance(state, SessionState):
        raise DualPlanAuthorityRefused(
            "verified shadow result has no canonical SessionState")
    record_sha = str(getattr(shadow_result, "record_sha256", ""))
    runtime_sha = str(
        getattr(shadow_result, "runtime_authority_sha256", "") or "")
    if not _HEX64.fullmatch(record_sha) or not _HEX64.fullmatch(runtime_sha):
        raise DualPlanAuthorityRefused(
            "verified shadow record/runtime authority is incomplete")
    if state.state_hash != plan.shadow_snapshot_hash:
        raise DualPlanAuthorityRefused(
            "plan does not commit the verified shadow state")
    if regenesis_flat_sizing_required():
        _require_flat_regenesis_observation(observation)
    body = {
        "schema": SCHEMA,
        "plan_id": str(plan.plan_id),
        "plan_fingerprint": str(plan.fingerprint()),
        "decision_session": plan.decision_session.isoformat(),
        "shadow_record_sha256": record_sha,
        "shadow_runtime_authority_sha256": runtime_sha,
        "shadow_state": state.to_dict(),
        "publication": _mapping(publication, where="pinned publication"),
        "account_snapshot": _account_payload(account_snapshot),
        "broker_observation": _observation_payload(observation),
        "marks": {str(key): str(value)
                  for key, value in sorted(marks.items())},
        "tickers": {str(key): str(value)
                    for key, value in sorted(tickers.items())},
    }
    body["authority_sha256"] = _sha256(body)
    return json.loads(_canonical(body))


def _validate_payload(value: Any, *, plan_id: str | None = None) -> dict:
    raw = _mapping(value, where="dual sizing authority")
    expected = {
        "schema", "plan_id", "plan_fingerprint", "decision_session",
        "shadow_record_sha256", "shadow_runtime_authority_sha256",
        "shadow_state", "publication", "account_snapshot",
        "broker_observation", "marks", "tickers", "authority_sha256",
    }
    if set(raw) != expected or raw.get("schema") != SCHEMA:
        raise DualPlanAuthorityRefused(
            "dual sizing authority has an unknown schema or shape")
    digest = str(raw.get("authority_sha256") or "")
    unsigned = dict(raw)
    unsigned.pop("authority_sha256", None)
    if not _HEX64.fullmatch(digest) or digest != _sha256(unsigned):
        raise DualPlanAuthorityRefused(
            "dual sizing authority digest does not match its content")
    if plan_id is not None and raw.get("plan_id") != plan_id:
        raise DualPlanAuthorityRefused(
            "dual sizing authority names a different plan")
    return json.loads(_canonical(raw))


def require_regenesis_flat_authority(
        value: Any, *, plan_id: str | None = None) -> dict:
    """Recheck that immutable sizing never contained predecessor broker state."""
    raw = _validate_payload(value, plan_id=plan_id)
    _require_flat_regenesis_observation(
        _decode_observation(raw["broker_observation"]))
    return raw


def _cursor(plan_id: str) -> str:
    return CURSOR_PREFIX + _text(plan_id, where="plan id")


def load_authority(conn, *, plan_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (_cursor(plan_id),))
        row = cur.fetchone()
    if row is None:
        return None
    value = row[1] if isinstance(row[1], Mapping) else json.loads(str(row[1]))
    result = _validate_payload(value, plan_id=plan_id)
    if str(row[0]) != str(result["decision_session"]):
        raise DualPlanAuthorityRefused(
            "dual sizing authority session column disagrees with its payload")
    return result


def record_authority(conn, authority: Mapping, *, commit: bool = True) -> dict:
    """Persist once. An idempotent retry may reproduce, never replace, inputs."""
    value = _validate_payload(authority)
    existing = load_authority(conn, plan_id=value["plan_id"])
    if existing is not None:
        if existing != value:
            raise DualPlanAuthorityRefused(
                "dual sizing authority is immutable")
        return existing
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (_cursor(value["plan_id"]), value["decision_session"],
             _canonical(value)))
    stored = load_authority(conn, plan_id=value["plan_id"])
    if stored != value:
        raise DualPlanAuthorityRefused(
            "a concurrent writer recorded different dual sizing inputs")
    if commit:
        conn.commit()
    return stored


def rederive_plan(
        conn, *, plan, binding, rollout_state,
        expected_shadow_result=None) -> dict[str, str]:
    """Re-run canonical account sizing from the exact retained inputs."""
    authority = load_authority(conn, plan_id=plan.plan_id)
    if authority is None:
        raise DualPlanAuthorityRefused(
            "the plan has no immutable dual sizing authority")
    if authority["plan_fingerprint"] != plan.fingerprint():
        raise DualPlanAuthorityRefused(
            "the retained sizing authority names different plan economics")
    try:
        state = SessionState.from_dict(authority["shadow_state"])
    except Exception as exc:  # noqa: BLE001 - convert canonical state refusal
        raise DualPlanAuthorityRefused(
            "retained shadow state is not canonical") from exc
    if state.state_hash != plan.shadow_snapshot_hash:
        raise DualPlanAuthorityRefused(
            "retained shadow state differs from the plan commitment")
    if expected_shadow_result is not None:
        expected_state = getattr(expected_shadow_result, "state", None)
        if (expected_state is None
                or expected_state.state_hash != state.state_hash
                or str(getattr(expected_shadow_result, "record_sha256", ""))
                != authority["shadow_record_sha256"]
                or str(getattr(
                    expected_shadow_result,
                    "runtime_authority_sha256", "") or "")
                != authority["shadow_runtime_authority_sha256"]):
            raise DualPlanAuthorityRefused(
                "current verified shadow authority differs from the plan input")
    marks_raw = _mapping(authority["marks"], where="retained close marks")
    tickers_raw = _mapping(authority["tickers"], where="retained tickers")
    marks = {str(key): _decimal(value, where=f"mark {key}")
             for key, value in marks_raw.items()}
    tickers = {str(key): _text(value, where=f"ticker {key}")
               for key, value in tickers_raw.items()}
    try:
        derived = build_execution_plan(
            state=state, binding=binding,
            publication=_mapping(
                authority["publication"], where="retained publication"),
            account_snapshot=_decode_account(authority["account_snapshot"]),
            observation=_decode_observation(authority["broker_observation"]),
            marks=marks, tickers=tickers,
            decision_session=plan.decision_session,
            effective_session=plan.effective_session,
            rollout_state=rollout_state)
    except DualPlanAuthorityRefused:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize adapter failure
        raise DualPlanAuthorityRefused(
            f"canonical dual plan re-derivation refused: {exc}") from exc
    if (derived.plan.plan_id != plan.plan_id
            or derived.plan.fingerprint() != plan.fingerprint()
            or derived.plan.to_dict() != plan.to_dict()):
        raise DualPlanAuthorityRefused(
            "retained sizing inputs do not re-derive the exact PAPER plan")
    return {
        "schema": SCHEMA,
        "authority_sha256": authority["authority_sha256"],
        "shadow_record_sha256": authority["shadow_record_sha256"],
        "state_sha256": state.state_hash,
        "plan_fingerprint": plan.fingerprint(),
        "canonical_symbols": dict(sorted(tickers.items())),
        "verdict": "MATCH",
    }


__all__ = [
    "CURSOR_PREFIX", "SCHEMA", "DualPlanAuthorityRefused",
    "build_authority", "load_authority", "record_authority",
    "regenesis_flat_sizing_required", "regenesis_flat_sizing_scope",
    "require_regenesis_flat_authority", "rederive_plan",
]
