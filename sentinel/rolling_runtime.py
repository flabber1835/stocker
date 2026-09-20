"""Broker-free rolling runtime: durable candidate first, then timed authority."""
from __future__ import annotations

from dataclasses import asdict, replace

from sentinel import backup_runtime_authority, rolling_initialization as initial
from sentinel import rolling_checkpoint as origin, rolling_daily as daily
from sentinel import rolling_daily_checkpoint as checkpoints, rolling_authority as authority
from sentinel import shadow_observation as shadow
from sentinel.execution import journal
from sentinel.feed import calendar, rolling_go_inputs as inputs, operational_snapshot as snapshots, publication
from sentinel.feed.rolling_contract import digest

SCHEMA = authority.SCHEMA
Refused = authority.Refused


def selected(conn):
    rolling = inputs.is_rolling(inputs.current(conn))
    if not rolling and origin.read(conn) is not None:
        raise Refused("ROLLING_PUBLICATION_REQUIRED")
    return rolling


def _closure(conn, context, *, status_only=False):
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


def classify(conn, *, observation_id, starting_cash, structural_only=False, clock=None):
    """Own an idle read-only transaction; structural status grants no live GO."""
    try:
        inputs.require_schemas(conn)
        context = initial._context(observation_id, starting_cash)
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with inputs.pinned(conn) as pub:
            if not inputs.is_rolling(pub):
                raise Refused("ROLLING_PUBLICATION_REQUIRED")
            if origin.read(conn) is None:
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


def service_advance(conn, *, through, observation_id, starting_cash):
    """Acquire only after checking the previous runtime authority and adjacency."""
    classified = classify(conn, observation_id=observation_id, starting_cash=starting_cash, structural_only=True)
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
            inputs._prepare(conn, target_session=through)
    # Fresh genesis and crash recovery must consume the reviewed/current exact
    # publication; neither is permitted to replace it with newly acquired data.
    result = advance(conn, through=through, observation_id=observation_id, starting_cash=starting_cash)
    from sentinel.feed import retention
    retention.maintain(conn)
    return result
