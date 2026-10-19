"""Broker-free rolling runtime: durable candidate first, then timed authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from sentinel import backup_runtime_authority, rolling_initialization as initial
from sentinel import rolling_checkpoint as origin, rolling_daily as daily
from sentinel import rolling_daily_checkpoint as checkpoints, rolling_authority as authority
from sentinel import shadow_observation as shadow
from sentinel.execution import journal
from sentinel.feed import calendar, rolling_go_inputs as inputs, operational_snapshot as snapshots, publication
from sentinel.feed.rolling_contract import digest

SCHEMA = authority.SCHEMA
Refused = authority.Refused


@dataclass(frozen=True)
class _StatusBinding:
    session: str
    publication: dict
    snapshot: dict
    state_sha256: str


@dataclass(frozen=True)
class _GuardState:
    last_processed_session: str
    data_version: int
    strategy_identity: dict
    last_decision: dict
    concordance_witness_origin: str | None


@dataclass(frozen=True)
class _GuardIntent:
    session: str
    state: _GuardState
    state_sha256: str
    record_sha256: str
    runtime_authority_sha256: str | None


def selected(conn):
    rolling = inputs.is_rolling(inputs.current(conn))
    if not rolling and origin.read(conn) is not None:
        raise Refused("ROLLING_PUBLICATION_REQUIRED")
    return rolling


def _closure(conn, context, *, status_only=False):
    if status_only:
        from sentinel import structural_verification
        return structural_verification.material(conn, slot='rolling-checkpoint',
            key={**context, 'controller': context['controller'].to_dict()},
            load=lambda: _status_closure(conn, context))
    return _load_closure(conn, context, status_only=False)


def _status_closure(conn, context):
    checkpoint, _, result, attested, previous = _load_closure(conn, context, status_only=True)
    # Historical input has already been authenticated. Fresh status checks need
    # only these bindings; copying its entire origin input per broker guard is
    # unnecessary. The returned strategy state remains detached by the scope.
    bound = _StatusBinding(checkpoint.session, checkpoint.publication, checkpoint.snapshot,
                           checkpoint.state_sha256)
    return bound, None, result, attested, previous


def _guard_projection(value):
    checkpoint, _, result, attested, _ = value
    state = result.state
    small = _GuardState(state.last_processed_session, state.data_version,
        state.strategy_identity, state.last_decision, state.concordance_witness_origin)
    intent = _GuardIntent(result.session, small, checkpoint.state_sha256,
        result.record_sha256,
        digest(attested.model_dump(by_alias=True)) if attested is not None else None)
    return checkpoint, intent, attested


def _guard_status(conn, *, observation_id, starting_cash):
    """Fresh status from private structural inputs; no full state escapes."""
    from sentinel import structural_verification
    if not structural_verification.active():
        raise Refused('ROLLING_GUARD_SCOPE_REQUIRED')
    try:
        inputs.require_schemas(conn)
        context = initial._context(observation_id, starting_cash)
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        with inputs.pinned(conn) as pub:
            if not inputs.is_rolling(pub):
                raise Refused('ROLLING_PUBLICATION_REQUIRED')
            if not conn.execute('SELECT EXISTS (SELECT 1 FROM sentinel_processed_sessions '
                                'WHERE cursor_name=%s)', (origin.CURSOR,)).fetchone()[0]:
                origin.require_fresh(conn)
                return None
            checkpoint, intent, attested = structural_verification.projected_material(
                conn, slot='rolling-checkpoint',
                key={**context, 'controller': context['controller'].to_dict()},
                load=lambda: _status_closure(conn, context),
                projection_slot='rolling-guard-inputs', project=_guard_projection)
            if attested is None:
                raise Refused('ROLLING_RUNTIME_ATTESTATION_REQUIRED')
            if isinstance(attested, authority.ReconstructionReceipt):
                raise Refused('RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY')
            _current(conn, checkpoint, pub)
            return intent
    finally:
        conn.rollback()


def _load_closure(conn, context, *, status_only):
    checkpoint, observer, result = checkpoints.load(conn, context, status_only=status_only)
    values = authority.latest(conn, context["observation_id"])
    latest = values[0] if values else None
    if latest is not None and latest.session > checkpoint.session:
        raise Refused("ROLLING_AUTHORITY_AHEAD_OF_CHECKPOINT")
    attested = latest is not None and latest.session == checkpoint.session
    previous = values[1] if attested and len(values) == 2 else latest if not attested else None
    if hasattr(checkpoint, "history_anchor"):
        if (previous is None or calendar.next_session(previous.session) != checkpoint.session
                or previous.record_sha256 != checkpoint.history_anchor["previous_record_sha256"]
                or previous.runtime_sha256 != digest(checkpoint.runtime_identity)):
            raise Refused("ROLLING_PREDECESSOR_AUTHORITY_REQUIRED")
    elif previous is not None:
        raise Refused("ROLLING_UNEXPECTED_PREDECESSOR_AUTHORITY")
    if attested:
        authority.require_binding(latest, checkpoint)
        if (latest.previous_authority_sha256 != (digest(previous.model_dump(by_alias=True)) if previous else None)
                or latest.previous_record_sha256 != (previous.record_sha256 if previous else None)):
            raise Refused("ROLLING_AUTHORITY_CHAIN_CHANGED")
    return checkpoint, observer, result, latest if attested else None, previous


def _current(conn, checkpoint, pub, *, now=None):
    if checkpoint.publication != pub.to_dict():
        raise Refused("ROLLING_RUNTIME_PUBLICATION_CHANGED")
    binding, report = inputs.validate_status(conn, pub, now=now)
    if binding != checkpoint.snapshot:
        raise Refused("ROLLING_RUNTIME_SNAPSHOT_CHANGED")
    return report


def _result(result, value):
    if isinstance(value, authority.ReconstructionReceipt):
        raise Refused("RECONSTRUCTION_IS_NOT_PROSPECTIVE_AUTHORITY")
    return replace(result, shadow_verdict=shadow.SHADOW_GO, verification=shadow.VERIFIED,
                   runtime_authority_sha256=digest(value.model_dump(by_alias=True)),
                   live_frontier=result.session, verification_scope=authority.SCOPE)


def classify(conn, *, observation_id, starting_cash, structural_only=False, clock=None,
             unchanged_through=None):
    """Own an idle read-only transaction; structural status grants no live GO."""
    try:
        inputs.require_schemas(conn)
        context = initial._context(observation_id, starting_cash)
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with inputs.pinned(conn) as pub:
            if not inputs.is_rolling(pub):
                raise Refused("ROLLING_PUBLICATION_REQUIRED")
            # Dispatch without decoding the origin twice. _closure authenticates
            # it completely, including after a guarded row-version change.
            if not conn.execute("SELECT EXISTS (SELECT 1 FROM sentinel_processed_sessions "
                                "WHERE cursor_name=%s)", (origin.CURSOR,)).fetchone()[0]:
                origin.require_fresh(conn)
                return {"status": "NOT_STARTED"}
            checkpoint, _, result, attested, _ = _closure(conn, context, status_only=True)
            if attested is None:
                if structural_only:
                    return {"status": "RECONSTRUCTION_REQUIRED", "latest_session": checkpoint.session}
                _current(conn, checkpoint, pub, now=clock() if clock else None)
                timing = initial._timing(conn, checkpoint.session)
                return {"status": "RECOVERY_REQUIRED", "recovery_kind": "TRAILING_CANDIDATE",
                        "recovery_session": checkpoint.session, "execution_session": timing["execution_session"],
                        "recovery_cutoff_at": timing["execution_open_at"]}
            if structural_only:
                status = "RECONSTRUCTED_STRUCTURAL" if isinstance(attested, authority.ReconstructionReceipt) else "ATTESTED_STRUCTURAL"
                if status == "ATTESTED_STRUCTURAL" and checkpoint.session == unchanged_through:
                    report = _current(conn, checkpoint, pub, now=clock() if clock else None)
                    from sentinel.feed import readers
                    measured = readers.bound_readiness(pub, report)
                    from sentinel import shadow_health_projection
                    inventory, present = shadow_health_projection._inventory(conn)
                    if not present:
                        raise Refused('verified unchanged session has no origin inventory')
                    return {"status": "VERIFIED_UNCHANGED", "result": _result(result, attested),
                            "inventory_sha256": inventory,
                            "_readiness_snapshot": measured}
                return {"status": status, "latest_session": checkpoint.session}
            _current(conn, checkpoint, pub, now=clock() if clock else None)
            return {"status": "VERIFIED", "result": _result(result, attested)}
    finally:
        conn.rollback()


def status(conn, *, observation_id, starting_cash):
    classified = classify(conn, observation_id=observation_id, starting_cash=starting_cash)
    if classified["status"] == "NOT_STARTED":
        return None
    if classified["status"] != "VERIFIED":
        raise Refused("ROLLING_RUNTIME_ATTESTATION_REQUIRED")
    return classified["result"]


def advance(conn, *, through, observation_id, starting_cash):
    """Pin publication and behavioral ownership through both durable commits."""
    try:
        inputs.require_schemas(conn)
        context = initial._context(observation_id, starting_cash)
        with journal.writer_lock(conn):
            with snapshots.pinned(conn, commit=False) as (pub, _binding):
                if through != pub.window_end:
                    raise Refused("ROLLING_RUNTIME_TARGET_CHANGED")
                inputs.validate_status(conn, pub)
                if origin.read(conn) is None:
                    candidate = initial.initialize(conn, observation_id=observation_id, starting_cash=starting_cash)
                else:
                    checkpoint, _, candidate, attested, _ = _closure(conn, context)
                    if checkpoint.session == through:
                        _current(conn, checkpoint, pub)
                        if attested is not None:
                            return _result(candidate, attested)
                        # Candidate already committed; do not replay its transition.
                    else:
                        if attested is None:
                            raise Refused("ROLLING_CANDIDATE_MUST_BE_ATTESTED_FIRST")
                        if calendar.next_session(checkpoint.session) != through:
                            raise Refused("ROLLING_RUNTIME_SESSION_GAP")
                        candidate = daily.advance(conn, observation_id=observation_id, starting_cash=starting_cash)
                # Every path reaching here has a durable checkpoint. This clock
                # sample happens strictly after that commit or restart read.
                completed = initial._timing(conn, through)
                # Loading a retained predecessor binds its book provenance.
                # Re-read the process identity after a policy transition so the
                # new checkpoint is authenticated under its admitted target.
                context = initial._context(observation_id, starting_cash)
                checkpoint, _, restored, attested, retained_previous = _closure(conn, context)
                if attested is not None:
                    return _result(restored, attested)
                previous = retained_previous
                report = _current(conn, checkpoint, pub)
                timing = dict(checkpoint.precommit_timing, schema="sentinel.shadow-session-timing/1",
                              candidate_committed_at=completed["observed_at"])
                shadow._timing_proof(timing, decision_session=through, committed=True,
                                     where="rolling runtime post-commit timing")
                backup_runtime_authority.require(conn, operation="rolling runtime attestation")
                value = authority.Authority(
                    observation_id=observation_id, session=through,
                    checkpoint_sha256=digest(checkpoint.model_dump(by_alias=True)),
                    record_sha256=checkpoint.record_sha256, state_sha256=checkpoint.state_sha256,
                    input_sha256=digest(checkpoint.input_value), runtime_sha256=digest(checkpoint.runtime_identity),
                    publication_sha256=digest(checkpoint.publication),
                    previous_authority_sha256=digest(previous.model_dump(by_alias=True)) if previous else None,
                    previous_record_sha256=previous.record_sha256 if previous else None,
                    readiness_sha256=digest(asdict(report)), timing=timing,
                    pitr=publication._publication_recovery_target(conn))
                initial._timing(conn, through)
                authority.append(conn, value)
                conn.commit()
                return _result(candidate, value)
    except BaseException:
        conn.rollback()
        raise


def _refresh_unchanged_health(conn, result, verified_inventory):
    """Repair only the auxiliary hint under a short, nonfinancial writer lock."""
    import os, sys
    if os.environ.get('SENTINEL_FEED_SERVICE_MODE') != 'SHADOW':
        return
    try:
        from sentinel import shadow_health_projection as health, shadow_service
        config = shadow_service.ShadowServiceConfig.from_env()
        def unavailable(_):
            raise ValueError('verified origin health projection is unavailable')
        try:
            health.health(config, fallback=unavailable)
            return
        except Exception:
            pass
        # This writes no financial state. Full content verification completed
        # outside this lock and supplied its pinned snapshot's row inventory.
        with journal.writer_lock(conn, recovery_only=True):
            current_inventory, present = health._inventory(conn)
            if not present or current_inventory != verified_inventory:
                raise Refused('shadow inventory changed after read-only verification')
            health.publish(config, result.to_dict(), conn)
    except Exception as exc:
        print('WARNING: shadow health projection unavailable: ' +
              type(exc).__name__, file=sys.stderr, flush=True)
    finally:
        conn.rollback()


def service_advance(conn, *, through, observation_id, starting_cash, acquisition_deadline=None):
    """Acquire only after checking the previous runtime authority and adjacency."""
    from sentinel import shadow_budget
    if acquisition_deadline is None:
        acquisition_deadline = shadow_budget.cutoff()
    classified = classify(conn, observation_id=observation_id, starting_cash=starting_cash,
                          structural_only=True, unchanged_through=through)
    if classified["status"] == "VERIFIED_UNCHANGED":
        result = classified['result']
        # The canonical report was measured under the completed read-only pin.
        # This auxiliary INSERT renews evidence, never the life of an old PASS.
        from sentinel.feed import readiness
        readiness.save_snapshot(conn, classified['_readiness_snapshot'])
        _refresh_unchanged_health(conn, result, classified['inventory_sha256'])
        from sentinel.feed import retention
        retention.maintain(conn)
        return result
    if classified['status'] == 'NOT_STARTED':
        context = initial._context(observation_id, starting_cash)
        from sentinel.core import window_policy
        opened, _ = calendar.session_window(calendar.next_session(through))
        late = initial._now(conn) >= opened
        conn.rollback()
        if late and window_policy.formed(context['strategy']):
            initial.initialize(conn, observation_id=observation_id, starting_cash=starting_cash)
            from sentinel import rolling_recovery
            return rolling_recovery.advance_one(conn, through=through,
                observation_id=observation_id, starting_cash=starting_cash)
    if classified["status"] in {"ATTESTED_STRUCTURAL", "RECONSTRUCTED_STRUCTURAL", "RECONSTRUCTION_REQUIRED"}:
        previous = classified["latest_session"]
        next_step = previous if classified["status"] == "RECONSTRUCTION_REQUIRED" else calendar.next_session(previous)
        opened, _ = calendar.session_window(calendar.next_session(next_step))
        expired = initial._now(conn) >= opened
        conn.rollback()
        if next_step <= through and expired:
            from sentinel import rolling_recovery
            return rolling_recovery.advance_one(conn, through=through,
                observation_id=observation_id, starting_cash=starting_cash)
        if classified["status"] == "RECONSTRUCTED_STRUCTURAL" and previous == through:
            from sentinel.rolling_reconstruction_evidence import InputsUnavailable
            raise InputsUnavailable("NEXT_FRESH_SESSION_REQUIRED:" + next_step)
        if previous != through:
            if next_step != through:
                raise Refused("ROLLING_RUNTIME_SESSION_GAP")
            initial._timing(conn, through)
            conn.rollback()
            shadow_budget.require_remaining(acquisition_deadline)
            inputs._prepare(conn, target_session=through,
                            absolute_deadline=acquisition_deadline)
    # Fresh genesis and crash recovery must consume the reviewed/current exact
    # publication; neither is permitted to replace it with newly acquired data.
    # Keep the same canonical session lock through post-commit retention and
    # the small health projection, so it cannot certify a concurrently changed
    # behavioral row inventory. Financial guards never consume the projection.
    with journal.writer_lock(conn):
        result = advance(conn, through=through, observation_id=observation_id, starting_cash=starting_cash)
        from sentinel.feed import retention
        retention.maintain(conn)
        import os, sys
        if os.environ.get('SENTINEL_FEED_SERVICE_MODE') == 'SHADOW':
            try:
                from sentinel import shadow_health_projection, shadow_service
                shadow_health_projection.publish(
                    shadow_service.ShadowServiceConfig.from_env(), result.to_dict(), conn)
            except Exception as exc:
                print('WARNING: shadow health projection unavailable: ' +
                      type(exc).__name__, file=sys.stderr, flush=True)
        return result
