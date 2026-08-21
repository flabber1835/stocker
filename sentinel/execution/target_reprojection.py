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
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
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


# Publication ratios originate in DOUBLE PRECISION.  A repeating rational such
# as 1/30 therefore arrives as 0.03333333333333333 and Decimal faithfully
# preserves that approximation: 300 * ratio becomes 9.99999999999999900.  A
# generic nearest-lot rounding rule would silently change economic intent, so
# the only correction permitted below is an exact rational reconstruction from
# the durable per-action evidence that produced the aggregate multiplier.
_RATIO_REPRESENTATION_TOLERANCE = Fraction(1, 10**12)
_STATED_DENOMINATOR_TOLERANCE = Fraction(1, 100)
_RECIPROCAL_EVIDENCE_DISPOSITIONS = frozenset({
    "published_canonical_equity_ratio", "corroborated_reciprocal"})


def _fractions_close(left: Fraction, right: Fraction,
                     tolerance: Fraction) -> bool:
    scale = max(abs(left), abs(right), Fraction(1, 10**30))
    return abs(left - right) <= tolerance * scale


def _evidence_factor(item: Mapping[str, object]) -> tuple[Fraction, Fraction]:
    """Return (published approximation, exact evidenced multiplier)."""
    canonical = _decimal(
        item.get("canonical_multiplier"),
        where="scalar action evidence canonical multiplier")
    stated = _decimal(
        item.get("value"), where="scalar action evidence ACTIONS value")
    if canonical <= 0 or stated <= 0:
        raise TargetProjectionRefused(
            "scalar action evidence multipliers must be positive")
    published = Fraction(canonical)
    exact = published

    raw_numerator = item.get("canonical_numerator")
    raw_denominator = item.get("canonical_denominator")
    if (raw_numerator is None) != (raw_denominator is None):
        raise TargetProjectionRefused(
            "scalar action rational evidence is incomplete")
    if raw_numerator is not None:
        try:
            numerator = int(raw_numerator)
            denominator = int(raw_denominator)
        except (TypeError, ValueError) as exc:
            raise TargetProjectionRefused(
                "scalar action rational evidence is invalid") from exc
        if numerator <= 0 or denominator <= 0:
            raise TargetProjectionRefused(
                "scalar action rational evidence must be positive")
        rational = Fraction(numerator, denominator)
        if not _fractions_close(
                published, rational, _RATIO_REPRESENTATION_TOLERANCE):
            raise TargetProjectionRefused(
                "scalar action rational evidence contradicts its published "
                "canonical multiplier")
        return published, rational

    if (stated > 1
            and str(item.get("action")) in {"split", "adrratiosplit"}
            and str(item.get("split_disposition"))
            in _RECIPROCAL_EVIDENCE_DISPOSITIONS):
        stated_fraction = Fraction(stated)
        reciprocal = Fraction(1, 1) / stated_fraction
        if _fractions_close(
                published, reciprocal, _RATIO_REPRESENTATION_TOLERANCE):
            exact = reciprocal
        else:
            # The shared resolver deliberately snaps a near-integral noisy
            # reverse denominator (30.003, 9.00009, ...) when independent price
            # evidence corroborates the exact reciprocal. Mirror only that
            # already-certified representation, never an arbitrary nearest lot.
            denominator = int(stated.to_integral_value(
                rounding=ROUND_HALF_EVEN))
            integral = Fraction(denominator, 1)
            if (denominator > 0
                    and _fractions_close(
                        stated_fraction, integral,
                        _STATED_DENOMINATOR_TOLERANCE)
                    and _fractions_close(
                        published, Fraction(1, denominator),
                        _RATIO_REPRESENTATION_TOLERANCE)):
                exact = Fraction(1, denominator)
    return published, exact


def _exact_evidenced_projection(
        *, security_id: str, quantity: Decimal, multiplier: Decimal,
        increment: Decimal, projected: Decimal,
        evidence: tuple[Mapping[str, object], ...]) -> Optional[Decimal]:
    """Recover only an exact action rational that lands on a broker increment.

    Returning ``None`` means the ordinary exact-Decimal refusal remains in
    force.  This is intentionally not a tolerance-based quantity rounding path:
    all events must carry their published canonical multiplier, that product
    must reproduce the aggregate multiplier, and the exact rational result must
    already be an integer number of certified broker increments.
    """
    relevant = tuple(
        item for item in evidence
        if str(item.get("security_id")) == str(security_id))
    if not relevant or any(
            item.get("canonical_multiplier") is None for item in relevant):
        return None

    published_product = Fraction(1, 1)
    exact_product = Fraction(1, 1)
    for item in relevant:
        published, exact = _evidence_factor(item)
        published_product *= published
        exact_product *= exact
    if not _fractions_close(
            Fraction(multiplier), published_product,
            _RATIO_REPRESENTATION_TOLERANCE):
        return None

    exact_target = Fraction(quantity) * exact_product
    steps = exact_target / Fraction(increment)
    if steps.denominator != 1:
        return None
    snapped = Decimal(steps.numerator) * increment
    if not _fractions_close(
            Fraction(projected), Fraction(snapped),
            _RATIO_REPRESENTATION_TOLERANCE):
        return None
    return snapped


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

    normalized_evidence = tuple(
        dict(item) for item in sorted(
            action_evidence,
            key=lambda item: (
                str(item.get("session", "")),
                str(item.get("security_id", "")),
                str(item.get("source_row_id", "")))))
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
            exact = _exact_evidenced_projection(
                security_id=str(security_id), quantity=quantity,
                multiplier=multiplier, increment=increment,
                projected=projected, evidence=normalized_evidence)
            if exact is None:
                raise TargetProjectionRefused(
                    f"projected target {security_id}={projected} is not a "
                    f"multiple of the certified broker increment {increment}; "
                    "refusing instead of rounding economic intent")
            projected = exact
        target[str(security_id)] = projected
        if multiplier != 1:
            multipliers[str(security_id)] = multiplier
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
