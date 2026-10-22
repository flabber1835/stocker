"""Carry account share intent between strategy and allocation events."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.target_reprojection import TargetProjectionRefused

SCHEMA = "sentinel.held-share-targets/1"


def ownership(state):
    """A pending entry and its eventual episode share one causal identity."""
    from stock_strategy_shared.wealth_core.engine import Operation
    closing = {int(p["slot_id"]) for p in state.pending
               if p["operation"] == Operation.CLOSE_POSITION.value}
    result = {}
    for episode in state.wealth_core["episodes"].values():
        if int(episode["slot_id"]) in closing or Decimal(str(episode["current_shares"])) <= 0:
            continue
        result.setdefault(str(episode["security_id"]), []).append(
            (int(episode["slot_id"]), str(episode["signal_date"])))
    for pending in state.pending:
        if pending["operation"] == Operation.OPEN_SLOT_POSITION.value:
            result.setdefault(str(pending["security_id"]), []).append(
                (int(pending["slot_id"]), str(pending["signal_session"])))
    return {sid: sorted(values) for sid, values in result.items()}


def effective_exposure(state, rollout):
    from sentinel.authority import RolloutMode
    return (Decimal(1) if rollout.mode is RolloutMode.PINNED_1_00
            else Decimal(str(state.last_decision["target_core_exposure"])))


def carry_quantities(*, previous, previous_state, projection, state,
                     exposure, actions=None):
    """Use retained intent, never the observed partially filled broker book."""
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    from sentinel.execution.protected_limits import _factor
    if previous.target_exposure != exposure:
        return {}
    old, current = ownership(previous_state), ownership(state)
    basket = previous.target_basket if projection is None else projection.target_basket
    through = previous.decision_session if projection is None else projection.through_session
    decision = date.fromisoformat(state.last_processed_session)
    result = {}
    for sid, quantity in sorted(basket.items()):
        continuing = sid in current and old.get(sid) == current[sid]
        if sid != DEFENSIVE_SECURITY_ID and not continuing:
            continue
        # An unprojected dollar entry never acquired a sized account intent.
        if projection is None and any(p.security_id == sid for p in previous.opening_intents):
            continue
        if projection is not None and quantity == 0:
            from sentinel.execution.protected_limits import unavailable_opening_intents
            from sentinel.execution.opening_sizing import UNAVAILABLE_MODE
            evidence = projection.opening_sizing or {}
            if (evidence.get("mode") == UNAVAILABLE_MODE
                    or sid in unavailable_opening_intents(projection)):
                continue  # Unbound sizing is not a durable decision to own zero.
        factor = Fraction(1)
        if through > decision:
            if decision != previous.decision_session or projection is None:
                raise TargetProjectionRefused("retained targets have a future share-unit basis")
            factor /= _factor(projection, sid)
        elif through < decision:
            if actions is None:
                raise TargetProjectionRefused("retained targets require authenticated intervening actions")
            symbols = {str(ep["ticker"]) for snapshot in (previous_state, state)
                       for ep in snapshot.wealth_core["episodes"].values()
                       if str(ep["security_id"]) == sid}
            symbols.update(str(p["ticker"]) for snapshot in (previous_state, state)
                           for p in snapshot.pending if str(p["security_id"]) == sid)
            if sid == DEFENSIVE_SECURITY_ID:
                symbols.add("BIL")
            material = actions.material_events_for(security_ids=(sid,), symbols=tuple(sorted(symbols)))
            if material:
                raise TargetProjectionRefused("unsupported action intersects retained account shares")
            multiplier = actions(sid)
            if multiplier is None:
                multiplier = Decimal(1)
            events = tuple(item.to_dict() for item in actions.scalar_evidence_for((sid,)))
            factor *= _factor(SimpleNamespace(
                action_multipliers={sid: multiplier}, action_evidence=events), sid)
        if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
            raise TargetProjectionRefused("retained account share quantity is invalid")
        result[sid] = exact_decimal(Fraction(quantity) * factor)
    return result


def build_basis(conn, *, previous, state, binding, rollout):
    """Freeze the immediate predecessor and the derived continuing targets."""
    from sentinel import dual_plan_authority
    from sentinel.core.production import SessionState
    from sentinel.execution import feed_actions, journal, target_reprojection
    from sentinel.execution.states import CommandState
    body = {"schema": SCHEMA, "previous_plan_id": None,
            "previous_plan_fingerprint": None, "previous_authority_sha256": None,
            "previous_projection_fingerprint": None, "targets": {}}
    if previous is None or dual_plan_authority.regenesis_flat_sizing_required():
        return body
    if (previous.deployment_id != binding.deployment_id
            or previous.broker != binding.broker
            or previous.broker_account_id != binding.broker_account_id
            or previous.takeover_epoch != binding.takeover_epoch
            or previous.decision_session > date.fromisoformat(state.last_processed_session)):
        raise TargetProjectionRefused("retained share targets belong to another account, epoch or future decision")
    authority = dual_plan_authority.load_authority(conn, plan_id=previous.plan_id)
    if authority is None or authority["plan_fingerprint"] != previous.fingerprint():
        raise TargetProjectionRefused("retained share targets lack their original sizing authority")
    prior_state = SessionState.from_dict(authority["shadow_state"])
    if prior_state.state_hash != previous.shadow_snapshot_hash:
        raise TargetProjectionRefused("retained share targets have a different canonical predecessor")
    projection = target_reprojection.load_projection(conn, plan_id=previous.plan_id)
    if projection is not None:
        target_reprojection.assert_projection(conn, plan=previous, projection=projection,
            through_session=projection.through_session)
    elif any(c.state not in {CommandState.PLANNED, CommandState.SUPERSEDED}
             for c in journal.load_commands(conn, binding.identity, plan_id=previous.plan_id)):
        raise TargetProjectionRefused("executed predecessor is missing its immutable share projection")
    through = previous.decision_session if projection is None else projection.through_session
    decision = date.fromisoformat(state.last_processed_session)
    actions = (feed_actions.action_lookup(conn, start=through, end=decision)
               if through < decision and previous.target_exposure == effective_exposure(state, rollout)
               else None)
    targets = carry_quantities(previous=previous, previous_state=prior_state,
        projection=projection, state=state, exposure=effective_exposure(state, rollout), actions=actions)
    body.update(previous_plan_id=previous.plan_id,
        previous_plan_fingerprint=previous.fingerprint(),
        previous_authority_sha256=authority["authority_sha256"],
        previous_projection_fingerprint=None if projection is None else projection.fingerprint(),
        targets={sid: decimal_text(qty) for sid, qty in sorted(targets.items())})
    return body


def verify_basis(conn, *, basis, state, binding, rollout):
    from sentinel.execution import journal, target_reprojection
    if not isinstance(basis, dict) or basis.get("schema") != SCHEMA:
        raise TargetProjectionRefused("retained share target basis is absent or unsupported")
    previous_id = basis.get("previous_plan_id")
    previous = None if previous_id is None else journal.load_plan(conn, previous_id)
    if previous_id is not None and previous is None:
        raise TargetProjectionRefused("retained share predecessor is missing")
    if previous is not None:
        projection = target_reprojection.load_projection(conn, plan_id=previous_id)
        if (basis.get("previous_plan_fingerprint") != previous.fingerprint()
                or basis.get("previous_projection_fingerprint") != (
                    None if projection is None else projection.fingerprint())):
            raise TargetProjectionRefused("retained share targets do not re-derive from their predecessor")
    expected = build_basis(conn, previous=previous, state=state, binding=binding, rollout=rollout)
    if expected != basis:
        raise TargetProjectionRefused("retained share targets do not re-derive from their predecessor")
    return {sid: Decimal(qty) for sid, qty in expected["targets"].items()}


def plan_targets(conn, *, plan, state):
    """Read only the small current basis; full authority is verified separately."""
    from sentinel.authority import RolloutMode, RolloutState
    from sentinel.binding import AccountBinding
    basis = _basis_for_plan(conn, plan.plan_id)
    if basis is None:
        return None  # Historical plans keep their original exact arithmetic.
    binding = AccountBinding(deployment_id=plan.deployment_id, broker=plan.broker,
        broker_account_id=plan.broker_account_id, takeover_epoch=plan.takeover_epoch)
    rollout = RolloutState(mode=RolloutMode(plan.rollout_mode), version=plan.rollout_version,
        certificate_sha256=plan.rollout_certificate_sha256)
    return verified_targets(conn, plan=plan, basis=basis, state=state, binding=binding, rollout=rollout)


def _basis_for_plan(conn, plan_id):
    from sentinel import dual_plan_authority, structural_verification
    def load():
        row = conn.execute("SELECT state->'held_share_targets' FROM sentinel_processed_sessions WHERE cursor_name=%s",
            (dual_plan_authority.CURSOR_PREFIX + plan_id,)).fetchone()
        return None if row is None else row[0]
    return structural_verification.material(conn, slot="held-share-basis", key=plan_id,
        load=load) if structural_verification.active() else load()


def verified_targets(conn, *, plan, basis, state, binding, rollout):
    from sentinel import structural_verification
    def load():
        return verify_basis(conn, basis=basis, state=state, binding=binding, rollout=rollout)
    return structural_verification.material(conn, slot="held-share-targets",
        key=(plan.fingerprint(), basis, predecessor_version(conn, plan.plan_id)),
        load=load) if structural_verification.active() else load()


def predecessor_version(conn, plan_id):
    """Bind callback reuse to the parent projection, including absent rows."""
    from sentinel.execution import target_reprojection
    basis = _basis_for_plan(conn, plan_id)
    if basis is None or basis.get("previous_plan_id") is None:
        return None
    return conn.execute(
        "SELECT p.tableoid,p.xmin::text,p.ctid::text,r.tableoid,r.xmin::text,r.ctid::text "
        "FROM sentinel_execution_plans p "
        "LEFT JOIN sentinel_processed_sessions r ON r.cursor_name=%s || p.plan_id "
        "WHERE p.plan_id=%s",
        (target_reprojection.CURSOR_PREFIX, basis["previous_plan_id"])).fetchone()


def apply(projection, *, targets, canonical_target, marks):
    """Preserve continuing quantities and fund only genuinely new positions."""
    if targets is None:
        return projection
    quantities, notional = dict(projection.quantities), dict(projection.notional)
    opening = {intent.security_id for intent in canonical_target.opening_intents}
    defensive = projection.defensive_quantity
    for sid, qty in targets.items():
        if not isinstance(qty, Decimal) or not qty.is_finite() or qty < 0:
            raise TargetProjectionRefused("retained targets must be nonnegative finite Decimal quantities")
        if sid == projection.defensive_security:
            defensive = qty
        elif sid in canonical_target.shares and sid not in opening:
            quantities[sid] = qty
            if sid in marks and marks[sid].is_finite() and marks[sid] > 0:
                notional[sid] = exact_decimal(Fraction(qty) * Fraction(marks[sid]))
            else:
                notional.pop(sid, None)
        elif sid not in opening:
            raise TargetProjectionRefused("retained targets cannot resurrect a strategy exit")
    retained_value = sum((Fraction(notional.get(sid, 0)) for sid in targets
                          if sid != projection.defensive_security), Fraction(0))
    available = max(Fraction(0), Fraction(projection.nav) * Fraction(projection.target_exposure) - retained_value)
    for sid in sorted(set(quantities) - set(targets)):
        price = marks.get(sid)
        if price is not None and price.is_finite() and price > 0:
            quantities[sid] = min(quantities[sid], Decimal(available // Fraction(price)))
            notional[sid] = exact_decimal(Fraction(quantities[sid]) * Fraction(price))
            available -= Fraction(notional[sid])
    defensive_mark = marks.get(projection.defensive_security, Decimal(0))
    if not defensive_mark.is_finite() or defensive_mark < 0:
        defensive_mark = Decimal(0)
    residual = (Fraction(projection.nav) - sum(map(Fraction, notional.values()), Fraction(0))
                - Fraction(defensive) * Fraction(defensive_mark))
    return replace(projection, quantities=dict(sorted(quantities.items())), notional=notional,
        defensive_quantity=defensive, cash_residual=exact_decimal(residual))
