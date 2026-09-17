"""Opt-in adjacent-session continuation, without GO or broker authority."""
from __future__ import annotations

from dataclasses import replace

from sentinel import rolling_initialization as initial, rolling_checkpoint as origin
from sentinel import rolling_daily_checkpoint as checkpoints
from sentinel import backup_runtime_authority, shadow_observation as shadow, schema
from sentinel.core import rolling_continuity
from sentinel.execution import journal
from sentinel.feed import operational_snapshot, rolling_jobs, publication, runtime_schema
from sentinel.feed.rolling_contract import digest


def advance(conn, *, observation_id: str, starting_cash):
    """Commit one next-session record and checkpoint, or recover its exact result."""
    try:
        schema.require_runtime_schema(conn)
        runtime_schema.require_feed_schema(conn)
        context = initial._context(observation_id, starting_cash)
        with journal.writer_lock(conn):
            checkpoint, observer, prior = checkpoints.load(conn, context)
            with operational_snapshot.pinned(conn, commit=False) as (pub, binding):
                if pub.version == prior.state.data_version and pub.window_end == prior.session:
                    conn.commit()
                    return prior
                initial._timing(conn, pub.window_end)
                backup_runtime_authority.require(conn, operation="rolling daily continuation")
                request = rolling_jobs.status(conn, binding["job_id"])["request"]
                if request["strategy_sha256"] != digest(context["strategy"]):
                    raise checkpoints.Refused("ACQUISITION_STRATEGY_CHANGED")
                material, anchors, proof = rolling_continuity.prepare(
                    conn, prior=prior.state, previous_binding=checkpoint.snapshot, publication=pub, binding=binding)
                published = replace(initial._published(material, pub), signal_basis_anchors=anchors, history_proof=proof)
                previous_row = observer._history()[0][-1]
                result = observer.observe(shadow.FullyPublishedSession(published, pub.to_dict()))
                row = observer._history()[0][-1]
                initial_checkpoint = origin.read(conn)
                updated = checkpoints.Checkpoint(
                    observation_id=observation_id, session=result.session, starting_cash=context["starting_cash"],
                    strategy_identity=context["strategy"], runtime_identity=context["runtime"],
                    snapshot=binding, publication=pub.to_dict(), genesis_sha256=observer.genesis_sha256,
                    record_sha256=result.record_sha256, state_sha256=result.state.state_hash,
                    input_value=shadow._published_input_value(published), warmup_input_identity=checkpoint.warmup_input_identity,
                    precommit_timing=initial._timing(conn, result.session), pitr=publication._publication_recovery_target(conn),
                    origin_sha256=digest(initial_checkpoint.model_dump(by_alias=True)),
                    history_anchor={"session": row["session"], "record_sha256": row["record_sha256"],
                        "previous_record_sha256": row["previous_record_sha256"],
                        "prior_state_sha256": row["prior_state_sha256"], "prior_data_version": prior.state.data_version,
                        "prior_strategy_economics": previous_row["strategy_economics"]})
                checkpoints.archive_input(conn, updated)
                checkpoints.write(conn, updated, previous=checkpoint)
                initial._timing(conn, result.session)
                backup_runtime_authority.require(conn, operation="rolling daily checkpoint commit")
                conn.commit()
                return result
    except BaseException:
        conn.rollback()
        raise


def resume(conn, *, observation_id: str, starting_cash):
    """Read only the authenticated current closure, without warming or advancing."""
    try:
        schema.require_runtime_schema(conn)
        runtime_schema.require_feed_schema(conn)
        context = initial._context(observation_id, starting_cash)
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        _, _, result = checkpoints.load(conn, context)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
