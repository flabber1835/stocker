"""Opt-in canonical first decision from a real operational snapshot."""
from __future__ import annotations

from datetime import timezone

from sentinel import backup_runtime_authority, schema, shadow_runtime
from sentinel import rolling_checkpoint as checkpoints, shadow_observation as shadow
from sentinel.controller.machine import Controller
from sentinel.core.production import warm_session_state
from sentinel.core.rolling_inputs import cold_start_inputs
from sentinel.core.session import DefensiveBar, PublishedSession, SessionState
from sentinel.execution import journal
from sentinel.feed import calendar, operational_snapshot, publication, rolling_jobs, runtime_schema
from sentinel.feed.rolling_contract import digest

RollingColdStartRefused = checkpoints.RollingColdStartRefused


def _now(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT clock_timestamp()")
        return cur.fetchone()[0]


def _context(observation_id, starting_cash):
    name = shadow._observation_id(observation_id)
    amount = shadow_runtime._starting_cash(starting_cash)
    controller, strategy = shadow_runtime._strategy()
    runtime = shadow_runtime._validated_runtime_identity(observation_id=name, starting_cash=amount)
    return {"observation_id": name, "starting_cash": format(amount.normalize(), "f"),
            "controller": controller, "strategy": strategy, "runtime": runtime}


def _timing(conn, session):
    now = _now(conn)
    if operational_snapshot.source_final_session(now) != session:
        raise RollingColdStartRefused("SOURCE_FINAL_TARGET_CHANGED")
    execution = calendar.next_session(session)
    opened, _ = calendar.session_window(execution)
    if now >= opened:
        raise RollingColdStartRefused("FIRST_DECISION_MISSED_OPEN")
    return {"schema": "sentinel.shadow-activation-timing/1", "decision_session": session,
            "execution_session": execution, "observed_at": now.astimezone(timezone.utc).isoformat(),
            "execution_open_at": opened.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": shadow.BEFORE_NEXT_OPEN}


def _published(material, pub):
    def defensive(row):
        return DefensiveBar(str(row.session), "SENTINEL:BIL", "BIL", row.bil_open_signal,
                            row.bil_close_signal, row.bil_close_adjusted, row.bil_close_unadjusted)
    axis = tuple(str(row.session) for row in material.benchmarks)
    return PublishedSession(
        session=material.session, data_version=pub.version, bars=material.bars,
        meta=material.meta, sectors=material.sectors,
        spy_closeadj=tuple(row.spy_total_return for row in material.benchmarks),
        spy_sessions=axis, spy_expected_sessions=axis, terminal_events=material.terminal_events,
        defensive_bar=defensive(material.benchmarks[-1]),
        defensive_previous_bar=defensive(material.benchmarks[-2]),
        spinoff_distributions=material.spinoff_distributions, history_proof=pub.evidence["strategy_history"])


def _initialize(conn, pub, binding, context):
    checkpoints.require_fresh(conn)
    if shadow_runtime._data_publication_subject_sha256(pub, pub.window_end) != context["runtime"].get(
            "validated_data_publication_sha256"):
        raise RollingColdStartRefused("UNREVIEWED_GENESIS_PUBLICATION")
    request = rolling_jobs.status(conn, binding["job_id"])["request"]
    if request["strategy_sha256"] != digest(context["strategy"]):
        raise RollingColdStartRefused("ACQUISITION_STRATEGY_CHANGED")
    timing = _timing(conn, pub.window_end)
    material = cold_start_inputs(conn, candidate_id=binding["candidate_id"], snapshot_id=binding["snapshot_id"])
    initial = SessionState.fresh(starting_cash=float(context["starting_cash"]),
        controller=Controller(context["controller"]), strategy_identity=context["strategy"])
    seed = warm_session_state(initial, material.warmup, publication_version=pub.version,
                              prospective_concordance_witness=True)
    warmup = shadow_runtime._warmup_input_identity(
        material.warmup, material.warmup.sessions, prospective_witness=True)
    store = shadow.PostgresShadowObservationStore(
        conn, observation_id=context["observation_id"], commit_genesis=False)
    observer = shadow.ShadowObserver(
        store=store, observation_id=context["observation_id"], starting_cash=context["starting_cash"],
        first_session=material.session, initial_state=seed, controller_config=context["controller"],
        strategy_identity=context["strategy"], runtime_identity=context["runtime"],
        activation_timing=timing, warmup_input_identity=warmup)
    published = _published(material, pub)
    result = observer.observe(shadow.FullyPublishedSession(published, pub.to_dict()))
    completed = _timing(conn, material.session)
    backup_runtime_authority.require(conn, operation="rolling cold-start checkpoint")
    checkpoint = checkpoints.Checkpoint(
        observation_id=context["observation_id"], session=material.session,
        starting_cash=context["starting_cash"], strategy_identity=context["strategy"],
        runtime_identity=context["runtime"], snapshot=binding, publication=pub.to_dict(),
        genesis_sha256=observer.genesis_sha256, record_sha256=result.record_sha256,
        state_sha256=result.state.state_hash, input_value=shadow._published_input_value(published),
        warmup_input_identity=warmup, precommit_timing=completed,
        pitr=publication._publication_recovery_target(conn))
    checkpoints.write(conn, checkpoint)
    return result


def initialize(conn, *, observation_id: str, starting_cash):
    """Own an idle connection; atomically commit or recover the first state."""
    schema.require_runtime_schema(conn)
    runtime_schema.require_feed_schema(conn)
    context = _context(observation_id, starting_cash)
    with journal.writer_lock(conn):
        checkpoint = checkpoints.read(conn)
        if checkpoint:
            return checkpoints.restore(conn, checkpoint, **context)
        with operational_snapshot.pinned(conn, commit=False) as (pub, binding):
            try:
                result = _initialize(conn, pub, binding, context)
                _timing(conn, result.session)  # Final writes cannot extend the opening deadline.
                conn.commit()
                return result
            except BaseException:
                conn.rollback()
                raise


def resume(conn, *, observation_id: str, starting_cash):
    """Read a consistent checkpoint closure on an idle connection; no mutation."""
    try:
        schema.require_runtime_schema(conn)
        runtime_schema.require_feed_schema(conn)
        context = _context(observation_id, starting_cash)
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        checkpoint = checkpoints.read(conn)
        if checkpoint is None:
            raise RollingColdStartRefused("COLD_START_CHECKPOINT_REQUIRED")
        result = checkpoints.restore(conn, checkpoint, **context)
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise
