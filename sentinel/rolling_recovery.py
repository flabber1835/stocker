"""One preserved-state historical step per service wake. No broker authority."""
from dataclasses import asdict, replace

from sentinel import backup_runtime_authority, rolling_initialization as initial
from sentinel import rolling_daily as daily, rolling_daily_checkpoint as checkpoints
from sentinel import rolling_authority as authority, rolling_reconstruction_evidence as evidence
from sentinel.execution import journal
from sentinel.feed import calendar, rolling_go_inputs as inputs, operational_snapshot as snapshots, publication
from sentinel.feed.rolling_contract import digest


def result_with_receipt(result, receipt):
    return replace(result, verification_scope=receipt.scope,
                   runtime_authority_sha256=digest(receipt.model_dump(by_alias=True)))


def advance_one(conn, *, through, observation_id, starting_cash):
    """Recover a trailing candidate or advance exactly one expired session."""
    from sentinel import rolling_runtime as runtime
    try:
        inputs.require_schemas(conn)
        context = initial._context(observation_id, starting_cash)
        with journal.writer_lock(conn), snapshots.pinned(conn, commit=False):
            checkpoint, observer, prior, attested, previous = runtime._closure(conn, context)
            if checkpoint.session == through and isinstance(attested, authority.ReconstructionReceipt):
                conn.rollback()
                return result_with_receipt(prior, attested)
            session = checkpoint.session if attested is None else calendar.next_session(checkpoint.session)
            if session > through:
                raise evidence.InputsUnavailable("NEXT_FRESH_SESSION_REQUIRED:" + session)
            evidence.timing(conn, session)  # No reconstruction before the actual cutoff.
            if attested is None:
                raw = checkpoint.publication
                pub = publication.Publication(raw["version"], raw["previous_version"], raw["run_id"],
                                              *raw["window"], raw["evidence"])
                evidence.require_dated(conn, pub)
                result = prior
            else:
                pub, binding = evidence.select(conn, session=session, previous_version=prior.state.data_version)
                inputs.validate_reconstruction(conn, pub)
                result = daily.commit_next(
                    conn, checkpoint=checkpoint, observer=observer, prior=prior, pub=pub, binding=binding,
                    context=context, checkpoint_type=checkpoints.ReconstructionCheckpoint, timing=evidence.timing)
            # The canonical commit is durable before this clock/receipt. Re-read
            # the closure so retries after a lost acknowledgement never replay it.
            checkpoint, _, restored, attested, previous = runtime._closure(conn, context)
            if attested is not None:
                return result_with_receipt(restored, attested)
            _, _, report = inputs.validate_reconstruction(conn, pub)
            backup_runtime_authority.require(conn, operation="rolling reconstruction receipt")
            value = authority.ReconstructionReceipt(
                observation_id=observation_id, session=session,
                checkpoint_sha256=digest(checkpoint.model_dump(by_alias=True)),
                record_sha256=checkpoint.record_sha256, state_sha256=checkpoint.state_sha256,
                input_sha256=digest(checkpoint.input_value), runtime_sha256=digest(checkpoint.runtime_identity),
                publication_sha256=digest(checkpoint.publication),
                previous_authority_sha256=digest(previous.model_dump(by_alias=True)) if previous else None,
                previous_record_sha256=previous.record_sha256 if previous else None,
                readiness_sha256=digest(asdict(report)), timing=evidence.timing(conn, session),
                pitr=publication._publication_recovery_target(conn))
            authority.append(conn, value)
            conn.commit()
            return result_with_receipt(result, value)
    except BaseException:
        conn.rollback()
        raise
