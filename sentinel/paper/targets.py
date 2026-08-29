"""Target/action projection, pre-open units, deltas, and instruments."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from decimal import Decimal, InvalidOperation

from typing import Mapping, Optional

from sentinel.core.decision import (
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)

from sentinel.core.loader import (
    CausalMetadataUnavailable,
    load_causal_meta_history, load_meta, load_window)

from sentinel.core.production import (
    CONCORDANCE_WITNESS_PROSPECTIVE,
    SessionState,
    advance_and_persist,
    load_published_session,
    warm_session_state,
)

from sentinel.execution import broker_cash, executor, journal

from sentinel.execution import commands as execution_commands

from sentinel.execution import preopen_authority

from sentinel.execution import reconcile as reconciliation

from sentinel.execution.commands import committed_quantity

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

from sentinel.execution.states import blocks_overlapping

from sentinel.execution import target_reprojection

from sentinel.feed import calendar, publication, readiness, store as feed_store

from .model import (
    PaperActivationRefused,
    PaperRetryableRefused,
    PreOpenShareUnitAuthorityUnavailable,
)

from .inspection import DEFENSIVE_SYMBOL

def _action_lookup(conn, state: SessionState, through: date):
    """Corporate-action quantity changes since the last durable decision.

    The plan/current state session is the earliest trustworthy boundary this
    activation gateway owns. Reconciliation's point-in-time resolver keeps
    ticker reuse out of the lookup; unsupported merger/spinoff shapes remain
    foreign activity and therefore block increases.
    """
    from sentinel.execution.reconcile import corpus_action_lookup

    start = date.fromisoformat(
        state.last_processed_session or through.isoformat())
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(created_at)::date FROM sentinel_commands")
        row = cur.fetchone()
    if row and row[0] is not None:
        start = min(start, row[0])
    return corpus_action_lookup(conn, start=start, end=through)

def _target_action_lookup(conn, plan: ExecutionPlan, through: date):
    """Share-count changes strictly after this immutable decision.

    Reconciliation needs enough history to age old filled commands into the
    observed book, so ``_action_lookup`` may begin before the current decision.
    That wider history is not evidence that the current target is stale: only
    an action in ``(decision_session, execution_session]`` can change shares
    after this plan fixed its basket.
    """
    from sentinel.execution.reconcile import corpus_action_lookup

    return corpus_action_lookup(
        conn, start=plan.decision_session, end=through)

def _target_action_multipliers(plan: ExecutionPlan, actions) -> dict[str, Decimal]:
    """Supported share changes in the exact target-validity window.

    Preserve an evidenced action sequence even when its aggregate multiplier is
    one.  Pending Wealth Core entries are action-aged once per effective
    session, so an intermediate fractional result may already have cancelled
    the entry and cannot be treated as an uneventful x1 target later.
    """
    target_ids = tuple(
        security_id for security_id, target
        in sorted(plan.target_basket.items()) if target != 0)
    evidence_reader = getattr(actions, "scalar_evidence_for", None)
    evidenced_ids = (
        {str(event.security_id) for event in evidence_reader(target_ids)}
        if callable(evidence_reader) else set())
    result = {}
    for security_id in target_ids:
        multiplier = actions(security_id)
        if (multiplier is not None
                and (multiplier != Decimal(1)
                     or security_id in evidenced_ids)):
            result[security_id] = multiplier
    return result

def _post_projection_action_multipliers(
        projection: target_reprojection.TargetProjection,
        actions) -> dict[str, Decimal]:
    """Age only shares that survived the immutable execution projection."""
    result = {}
    for security_id, target in sorted(projection.target_basket.items()):
        if target == 0:
            continue
        multiplier = actions(
            security_id, since=projection.through_session)
        if multiplier not in (None, Decimal(1)):
            result[security_id] = multiplier
    return result

def _preopen_active_security_ids(
        *, plan: ExecutionPlan, commands, actions) -> tuple[str, ...]:
    """Return every identity that can affect this execution boundary.

    A recovered command identity remains authority-relevant even when terminal
    with zero fill and therefore absent from the expected book.  Reconciliation
    can adopt such a row after the initial provider coverage was checked;
    omitting it would let projection/transport proceed under a publication that
    never answered for the newly trusted broker identity.  Ordinary terminal,
    zero-book commands do not expand the executable security set.
    """
    expected = reconciliation.expected_book_from_commands(
        commands, actions=actions)
    identities = {
        str(security_id)
        for security_id, quantity in plan.target_basket.items()
        if quantity != 0}
    identities.update(
        str(security_id) for security_id, quantity in expected.items()
        if quantity != 0)
    identities.update(
        str(command.security_id) for command in commands
        if blocks_overlapping(command.state) or command.is_recovered)
    return tuple(sorted(identities))

def _informational_active_symbols(
        *, active_security_ids, commands, observation: BrokerObservation,
        sizing_proof: Mapping) -> dict[str, str]:
    """Bind every active permanent id to one canonical transport symbol."""
    symbols: dict[str, str] = {}

    def add(security_id, symbol) -> None:
        sid = str(security_id)
        value = str(symbol or "").strip().upper()
        if not value or sid not in active_security_ids:
            return
        prior = symbols.get(sid)
        if prior is not None and prior != value:
            raise PaperActivationRefused(
                f"active security {sid} has conflicting canonical symbols")
        symbols[sid] = value

    canonical = sizing_proof.get("canonical_symbols") or {}
    if not isinstance(canonical, Mapping):
        raise PaperActivationRefused(
            "dual sizing authority has no canonical symbol mapping")
    for security_id, symbol in canonical.items():
        add(security_id, symbol)
    for command in commands:
        add(command.security_id, command.instrument.symbol)
    for position in observation.positions:
        add(position.instrument.security_id, position.instrument.symbol)
    for order in observation.orders:
        add(order.instrument.security_id, order.instrument.symbol)
    missing = sorted(set(active_security_ids) - set(symbols))
    if missing:
        raise PaperActivationRefused(
            "informational mirror lacks a canonical symbol for active "
            "security identities: " + ", ".join(missing))
    return dict(sorted(symbols.items()))

def _plan_deltas(
        *, target_basket: Mapping[str, Decimal],
        observation: BrokerObservation,
        minimum_quantity_increment: Decimal):
    identities = set(target_basket)
    identities.update(observation.positions_by_security())
    identities.update(
        order.instrument.security_id for order in observation.orders)
    return tuple(
        execution_commands.compute_delta(
            security_id=security_id,
            desired=target_basket.get(security_id, Decimal(0)),
            observation=observation,
            min_increment=minimum_quantity_increment)
        for security_id in sorted(identities))

def _provably_clean_empty_noop(
        *, deltas, commands, observation: BrokerObservation) -> bool:
    """Bypass authority only when no active share-unit domain exists.

    Equality between a nonzero raw plan target and a nonzero broker holding is
    not a no-event attestation: an unobserved split can make those incomparable
    units numerically equal.  Only the all-zero book has no share units whose
    open-boundary meaning needs affirmative authority.
    """
    return (
        all(delta.classification is execution_commands.DeltaClass.NONE
            for delta in deltas)
        and all(delta.desired == 0 and delta.held == 0
                and delta.committed == 0 for delta in deltas)
        and not any(blocks_overlapping(command.state) for command in commands)
        and not any(order.is_working for order in observation.orders))

def _preopen_views_or_none(
        conn, *, plan: ExecutionPlan, active_security_ids,
        required_cutoff_at: datetime, evaluated_at: datetime,
        actions, target_actions):
    """Load, validate, and overlay an immutable authority if one exists."""
    try:
        authority = preopen_authority.load_authority(
            conn, plan_id=plan.plan_id)
        if authority is None:
            return None, actions, target_actions
        preopen_authority.validate_for_plan(
            authority, plan=plan,
            required_security_ids=active_security_ids,
            required_cutoff_at=required_cutoff_at,
            evaluated_at=evaluated_at)
        return (
            authority,
            preopen_authority.overlay_actions(actions, authority),
            preopen_authority.overlay_actions(target_actions, authority))
    except preopen_authority.PreOpenAuthorityRefused as exc:
        raise PreOpenShareUnitAuthorityUnavailable(str(exc)) from exc

def _revalidate_preopen_authority_or_refuse(
        *, authority, plan: ExecutionPlan, commands, actions,
        required_cutoff_at: datetime, evaluated_at: datetime) -> None:
    """Recheck exact coverage after reconciliation may have adopted commands."""
    if authority is None:
        return
    active_security_ids = _preopen_active_security_ids(
        plan=plan, commands=commands, actions=actions)
    try:
        preopen_authority.validate_for_plan(
            authority, plan=plan,
            required_security_ids=active_security_ids,
            required_cutoff_at=required_cutoff_at,
            evaluated_at=evaluated_at)
    except preopen_authority.PreOpenAuthorityRefused as exc:
        raise PreOpenShareUnitAuthorityUnavailable(str(exc)) from exc

def _official_preopen_cutoff(plan: ExecutionPlan) -> datetime:
    """The evidence boundary is the exact certified XNYS session open."""
    opened, _closed = calendar.session_window(plan.effective_session)
    return opened

def _target_projection_or_refuse(
        conn, *, state: SessionState, plan: ExecutionPlan, binding,
        broker: ExecutionBroker, through: date, actions, target_actions,
        require_existing: bool = False,
        persist_projection: bool = True,
        expected_projection: Optional[
            target_reprojection.TargetProjection] = None):
    """Derive the exact unit projection and bind it to durable plan state."""
    if state.state_hash != plan.shadow_snapshot_hash:
        raise PaperActivationRefused(
            "target projection canonical state differs from the immutable "
            "plan snapshot")
    target = shadow_target(state)
    commands = journal.load_commands(conn, binding.identity)
    expected_book = reconciliation.expected_book_from_commands(
        commands, actions=actions)
    security_ids = (
        {security_id for security_id, quantity in plan.target_basket.items()
         if quantity != 0}
        | {security_id for security_id, quantity in target.shares.items()
           if quantity != 0}
        | set(expected_book))
    symbols = (
        {target.tickers[security_id] for security_id in security_ids
         if target.tickers.get(security_id)}
        | {command.instrument.symbol for command in commands
           if (command.security_id in security_ids
               and command.instrument.symbol)})
    if DEFENSIVE_SECURITY_ID in security_ids:
        # BIL is a fixed execution identity outside the Wealth Core shadow, so
        # ``target.tickers`` cannot supply it.  Unmapped corporate-action rows
        # are ticker-bound; omitting this symbol would let an unresolved BIL
        # action miss a fresh defensive target with no prior command/position.
        symbols.add(DEFENSIVE_SYMBOL)
    material = []
    for lookup in (actions, target_actions):
        finder = getattr(lookup, "material_events_for", None)
        if callable(finder):
            material.extend(finder(
                security_ids=security_ids, symbols=symbols))
    unique = {
        (event.source_row_id, event.reason): event for event in material}
    if unique:
        detail = [event.to_dict() for event in unique.values()]
        raise PaperActivationRefused(
            "corporate action intersects the executable book but has no "
            f"certified scalar projection: {detail}. Sentinel will not invent "
            "cash, positions, fills, or corrective orders for an Alpaca paper "
            "limitation")

    target_security_ids = tuple(
        security_id for security_id, quantity
        in sorted(plan.target_basket.items()) if quantity != 0)
    multipliers = {
        security_id: target_actions(security_id)
        for security_id in target_security_ids
        if target_actions(security_id) not in (None, Decimal(1))}
    evidence_reader = getattr(target_actions, "scalar_evidence_for", None)
    action_evidence = (
        tuple(event.to_dict() for event in evidence_reader(target_security_ids))
        if callable(evidence_reader) else ())
    try:
        projected = target_reprojection.project_target(
            plan, through_session=through,
            action_multipliers=multipliers,
            action_evidence=action_evidence,
            canonical_target_shares=target.shares,
            pending_open_shares=target.pending_open_shares,
            held_shares=target.held_shares,
            pending_close_shares=target.pending_close_shares,
            minimum_quantity_increment=(
                broker.capabilities.minimum_quantity_increment))
        if (expected_projection is not None
                and projected != expected_projection):
            raise target_reprojection.TargetProjectionRefused(
                "post-reconciliation authority-derived target projection "
                "differs from the pre-read projection")
        if require_existing:
            stored = target_reprojection.load_projection(
                conn, plan_id=plan.plan_id)
            if stored is None or stored != projected:
                raise target_reprojection.TargetProjectionRefused(
                    "recovery's authority-derived target projection is absent "
                    "or differs from the immutable projection used by execution")
            target_reprojection.assert_projection(
                conn, plan=plan, projection=stored,
                through_session=through)
            return stored
        if not persist_projection:
            return projected
        return target_reprojection.record_projection(conn, projected)
    except target_reprojection.TargetProjectionRefused as exc:
        raise PaperActivationRefused(str(exc)) from exc

async def _instrument_map(conn, broker: ExecutionBroker, state: SessionState,
                          plan: ExecutionPlan,
                          observation: BrokerObservation,
                          target_basket: Mapping[str, Decimal] | None = None,
                          ) -> dict[str, BrokerInstrument]:
    desired = plan.target_basket if target_basket is None else target_basket
    target = shadow_target(state)
    symbols = dict(target.tickers)
    symbols[DEFENSIVE_SECURITY_ID] = DEFENSIVE_SYMBOL
    meta = load_meta(conn)
    for security_id in desired:
        if security_id in meta:
            symbols.setdefault(security_id, meta[security_id].ticker)
    instruments: dict[str, BrokerInstrument] = {}
    for position in observation.positions:
        instruments[position.instrument.security_id] = position.instrument
    for order in observation.orders:
        instruments[order.instrument.security_id] = order.instrument
    # Resolve only securities that can produce an actionable command. The
    # desired basket always names the defensive sleeve, including BIL:0; an
    # irrelevant zero leg must not block a pure Core reduction on a needless
    # asset lookup.
    held = observation.positions_by_security()
    all_security_ids = set(desired) | set(held)
    effective_current = {
        security_id: held.get(security_id, Decimal(0)) + committed_quantity(
            observation.working_orders_for(security_id))
        for security_id in all_security_ids
    }
    needed = {
        security_id for security_id in all_security_ids
        if desired.get(security_id, Decimal(0))
        != effective_current[security_id]
    }
    unresolved = []
    for security_id in sorted(needed):
        current = instruments.get(security_id)
        increasing = (desired.get(security_id, Decimal(0))
                      > effective_current[security_id])
        # An observed broker asset id is already the strongest mapping the
        # adapter can provide for a REDUCTION. An increase revalidates active /
        # tradable status even when the asset is already held; yesterday's
        # stable id is identity evidence, not today's permission to buy.
        if current is not None and current.broker_id and not increasing:
            continue
        symbol = symbols.get(security_id) or (
            current.symbol if current is not None else None)
        if not symbol:
            unresolved.append(security_id)
            continue
        try:
            resolved = await broker.resolve_instrument(
                security_id=security_id, symbol=str(symbol))
        except BrokerAuthorityRefused:
            raise
        except Exception as exc:                              # noqa: BLE001
            raise PaperRetryableRefused(
                f"cannot resolve broker instrument {security_id}/{symbol}: "
                f"{type(exc).__name__}: {exc}") from exc
        if (resolved.security_id != security_id
                or not resolved.broker_id or not resolved.symbol):
            raise PaperActivationRefused(
                f"broker instrument resolution for {security_id}/{symbol} "
                "did not return the requested permanent identity, symbol and "
                "stable broker asset id")
        instruments[security_id] = resolved
    if unresolved:
        raise PaperActivationRefused(
            "no certified broker instrument mapping for: "
            + ", ".join(unresolved))
    return instruments
