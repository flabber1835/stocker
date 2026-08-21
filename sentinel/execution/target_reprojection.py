"""Immutable share-unit projection for a durable execution plan.

Corporate actions can change the number of shares that express an unchanged
economic intent between the decision close and the execution open.  The plan is
never edited.  Instead, this module stores the exact scalar transformation in
the already-authoritative namespaced cursor store and lets the executor verify
that record under its writer lock.

This is deliberately not a broker-compensation ledger.  It records intended
order units only; it never creates a fill, position, cash movement, or expected
broker activity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping, Optional

from sentinel.execution.plan import ExecutionPlan


CURSOR_PREFIX = "plan-target-projection:v1:"
KIND = "plan-target-projection/v1"


class TargetProjectionRefused(RuntimeError):
    """The action-aged target is absent, corrupt, or not reproducible."""


def _canonical(payload: Mapping) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _decimal(value, *, where: str) -> Decimal:
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise TargetProjectionRefused(f"{where} is not a Decimal") from exc
    if not converted.is_finite():
        raise TargetProjectionRefused(f"{where} must be finite")
    return converted


@dataclass(frozen=True)
class TargetProjection:
    plan_id: str
    plan_fingerprint: str
    through_session: date
    action_multipliers: Mapping[str, Decimal]
    action_evidence: tuple[Mapping[str, object], ...]
    target_basket: Mapping[str, Decimal]

    def _content_payload(self) -> dict:
        return {
            "kind": KIND,
            "plan_id": self.plan_id,
            "plan_fingerprint": self.plan_fingerprint,
            "through_session": self.through_session.isoformat(),
            "action_multipliers": {
                key: str(value)
                for key, value in sorted(self.action_multipliers.items())
            },
            "action_evidence": [dict(item) for item in self.action_evidence],
            "target_basket": {
                key: str(value)
                for key, value in sorted(self.target_basket.items())
            },
        }

    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical(self._content_payload()).encode("ascii")).hexdigest()

    def payload(self) -> dict:
        return {
            **self._content_payload(),
            "projection_fingerprint": self.fingerprint(),
        }


def project_target(
        plan: ExecutionPlan, *, through_session: date,
        action_multipliers: Mapping[str, Decimal],
        action_evidence: tuple[Mapping[str, object], ...] = (),
        minimum_quantity_increment: Decimal = Decimal(1)) -> TargetProjection:
    """Re-express ``plan.target_basket`` after scalar share-count actions."""
    unknown = sorted(set(action_multipliers) - set(plan.target_basket))
    if unknown:
        raise TargetProjectionRefused(
            "corporate action cannot introduce securities outside the plan "
            f"target: {unknown}")

    increment = _decimal(
        minimum_quantity_increment, where="minimum quantity increment")
    if increment <= 0:
        raise TargetProjectionRefused(
            "minimum quantity increment must be positive")
    multipliers: dict[str, Decimal] = {}
    target: dict[str, Decimal] = {}
    for security_id, raw_quantity in sorted(plan.target_basket.items()):
        quantity = _decimal(
            raw_quantity, where=f"plan target {security_id}")
        multiplier = _decimal(
            action_multipliers.get(security_id, Decimal(1)),
            where=f"corporate-action multiplier {security_id}")
        if multiplier <= 0:
            raise TargetProjectionRefused(
                f"corporate-action multiplier {security_id} must be positive")
        projected = quantity * multiplier
        if projected < 0:
            raise TargetProjectionRefused(
                f"projected target {security_id} would be short")
        if projected % increment != 0:
            raise TargetProjectionRefused(
                f"projected target {security_id}={projected} is not a multiple "
                f"of the certified broker increment {increment}; refusing "
                "instead of rounding economic intent")
        target[str(security_id)] = projected
        if multiplier != 1:
            multipliers[str(security_id)] = multiplier
    normalized_evidence = tuple(
        dict(item) for item in sorted(
            action_evidence,
            key=lambda item: (
                str(item.get("session", "")),
                str(item.get("security_id", "")),
                str(item.get("source_row_id", "")))))
    evidence_ids = {
        str(item.get("security_id")) for item in normalized_evidence}
    if evidence_ids - set(multipliers):
        raise TargetProjectionRefused(
            "scalar action evidence names a security without a material "
            f"multiplier: {sorted(evidence_ids - set(multipliers))}")
    if any(not item.get("source_row_id") for item in normalized_evidence):
        raise TargetProjectionRefused(
            "scalar action evidence requires a durable source-row identity")
    projection = TargetProjection(
        plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(),
        through_session=through_session, action_multipliers=multipliers,
        action_evidence=normalized_evidence,
        target_basket=target)
    return projection


def _cursor_name(plan_id: str) -> str:
    return f"{CURSOR_PREFIX}{plan_id}"


def _decode(raw, *, plan_id: str, session) -> TargetProjection:
    try:
        state = raw if isinstance(raw, dict) else json.loads(str(raw))
    except (TypeError, ValueError) as exc:
        raise TargetProjectionRefused(
            f"target projection for {plan_id} is not valid JSON") from exc
    expected = {
        "kind", "plan_id", "plan_fingerprint", "through_session",
        "action_multipliers", "action_evidence", "target_basket",
        "projection_fingerprint"}
    if (not isinstance(state, dict) or set(state) != expected
            or state.get("kind") != KIND or state.get("plan_id") != plan_id):
        raise TargetProjectionRefused(
            f"target projection for {plan_id} has an unknown state shape")
    try:
        through = date.fromisoformat(str(state["through_session"]))
        stored_session = (
            session if isinstance(session, date) else date.fromisoformat(str(session)))
    except (TypeError, ValueError) as exc:
        raise TargetProjectionRefused(
            f"target projection for {plan_id} has an invalid session") from exc
    if through != stored_session:
        raise TargetProjectionRefused(
            f"target projection for {plan_id} session disagrees with its key row")
    if (not isinstance(state["action_multipliers"], dict)
            or not isinstance(state["action_evidence"], list)
            or not all(isinstance(item, dict)
                       for item in state["action_evidence"])
            or not isinstance(state["target_basket"], dict)):
        raise TargetProjectionRefused(
            f"target projection for {plan_id} mappings are corrupt")
    projection = TargetProjection(
        plan_id=plan_id, plan_fingerprint=str(state["plan_fingerprint"]),
        through_session=through,
        action_multipliers={
            str(key): _decimal(value, where=f"stored multiplier {key}")
            for key, value in state["action_multipliers"].items()},
        action_evidence=tuple(dict(item) for item in state["action_evidence"]),
        target_basket={
            str(key): _decimal(value, where=f"stored target {key}")
            for key, value in state["target_basket"].items()})
    if state["projection_fingerprint"] != projection.fingerprint():
        raise TargetProjectionRefused(
            f"target projection for {plan_id} has a corrupt fingerprint")
    return projection


def load_projection(conn, *, plan_id: str) -> Optional[TargetProjection]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s", (_cursor_name(plan_id),))
        row = cur.fetchone()
    return None if row is None else _decode(row[1], plan_id=plan_id, session=row[0])


def record_projection(conn, projection: TargetProjection,
                      *, commit: bool = True) -> TargetProjection:
    """Persist once; an idempotent retry must reproduce byte-identical meaning."""
    existing = load_projection(conn, plan_id=projection.plan_id)
    if existing is not None:
        if existing != projection:
            raise TargetProjectionRefused(
                f"target projection for plan {projection.plan_id} is immutable: "
                f"stored={existing.payload()}, attempted={projection.payload()}")
        return existing
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO NOTHING",
            (_cursor_name(projection.plan_id),
             projection.through_session.isoformat(),
             _canonical(projection.payload())))
    stored = load_projection(conn, plan_id=projection.plan_id)
    if stored != projection:
        raise TargetProjectionRefused(
            f"concurrent target projection for plan {projection.plan_id} "
            "recorded different economics")
    if commit:
        conn.commit()
    return stored


def assert_projection(
        conn, *, plan: ExecutionPlan, projection: TargetProjection,
        through_session: date) -> None:
    """Bind the executor input to the original plan and its durable record."""
    if projection.plan_id != plan.plan_id:
        raise TargetProjectionRefused("target projection names another plan")
    if projection.plan_fingerprint != plan.fingerprint():
        raise TargetProjectionRefused(
            "target projection names different immutable plan economics")
    if projection.through_session != through_session:
        raise TargetProjectionRefused(
            "target projection is not effective through this execution session")
    stored = load_projection(conn, plan_id=plan.plan_id)
    if stored is None or stored != projection:
        raise TargetProjectionRefused(
            "executor target projection is absent or differs from durable state")


__all__ = [
    "TargetProjection", "TargetProjectionRefused", "assert_projection",
    "load_projection", "project_target", "record_projection"]
