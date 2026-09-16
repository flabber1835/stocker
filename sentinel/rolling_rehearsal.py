"""Read-only price-reader qualification. Never emits GO or advances a cursor."""
from __future__ import annotations

from sentinel.core.kernel import advance_session
from sentinel.core.production import load_published_session
from sentinel.core.rolling_reader import RollingPriceReader, RollingReaderRefused
from sentinel.core.session import SessionState
from sentinel.feed import calendar, publication, rolling_jobs, rolling_publisher, rolling_store
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.shadow_observation import (
    PostgresShadowRuntime, ShadowObserver, _published_input_value,
)
from sentinel.shadow_segments import SegmentedPostgresShadowObservationStore

SHARED_LEGACY_INPUTS = (
    "dated_metadata", "sectors", "terminal_events", "spinoff_distributions",
    "returning_security_split_anchors", "history_revision_proof",
)


def _no_warmup():
    raise RollingReaderRefused("REHEARSAL_MUST_NOT_RELOAD_GENESIS_PRICES")


def checkpoint(runtime: PostgresShadowRuntime):
    """Reuse chain/attestation validators, not current-vendor status promotion."""
    rows, state = runtime._attested_history()
    if not rows:
        raise RollingReaderRefused("ATTESTED_CHECKPOINT_REQUIRED")
    authorities = runtime.observer.store.authorities()
    return state, {
        "observation_id": runtime.observer.observation_id,
        "genesis_sha256": runtime.observer.genesis_sha256,
        "record_sha256": rows[-1]["record_sha256"],
        "state_sha256": state.state_hash,
        "authority_sha256": authorities[-1]["authority_sha256"],
        "runtime_identity_sha256": runtime.observer.runtime_identity_sha256,
        "cursor": state.last_processed_session,
    }


def compare_transition(reader, *, prior, baseline, controller_config):
    """Pure-kernel comparison; returned successor hashes confer no authority."""
    prior = SessionState.from_dict(prior.to_dict())
    reader.require_checkpoint_window(prior)
    if (prior.last_processed_session is None
            or baseline.session != calendar.next_session(prior.last_processed_session)):
        raise RollingReaderRefused("CHECKPOINT_SUCCESSOR_REQUIRED")
    prices = reader.prices(
        session=baseline.session, spy_sessions=len(baseline.spy_expected_sessions),
        anchor_sessions={sid: bar.session for sid, bar in baseline.signal_basis_anchors.items()})
    candidate = prices.comparison_input(baseline)
    baseline_input = _published_input_value(baseline)
    candidate_input = _published_input_value(candidate)
    if canonical_json(baseline_input) != canonical_json(candidate_input):
        raise RollingReaderRefused("PRICE_INPUT_DIFFERENCE")
    before = prior.to_dict()
    results = [advance_session(
        SessionState.from_dict(before), inputs, controller_config=controller_config,
        strategy_identity=prior.strategy_identity) for inputs in (baseline, candidate)]
    if results[0].state_hash != results[1].state_hash:
        raise RollingReaderRefused("SUCCESSOR_STATE_DIFFERENCE")
    if prior.to_dict() != before:
        raise RollingReaderRefused("CHECKPOINT_MUTATED")
    return {
        "session": baseline.session, "input_sha256": digest(candidate_input),
        "successor_state_sha256": results[1].state_hash,
        "decision_sha256": digest(results[1].last_decision),
    }


def rehearse(conn, *, job_id: str, observation_id: str, controller_config):
    """Caller supplies a READ ONLY REPEATABLE READ transaction; no commits here."""
    with conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        read_only = cur.fetchone()[0]
        cur.execute("SHOW transaction_isolation")
        isolation = cur.fetchone()[0]
    if read_only != "on" or isolation != "repeatable read":
        raise RollingReaderRefused("READ_ONLY_REPEATABLE_READ_REQUIRED")
    with publication.pinned(conn, commit=False) as legacy:
        comparison = rolling_publisher.published(conn, job_id)
        if comparison is None:
            raise RollingReaderRefused("PUBLISHED_COMPARISON_REQUIRED")
        request = rolling_jobs.PreparationRequest.model_validate(
            rolling_jobs.status(conn, job_id)["request"])
        if request.expected_publication_version != legacy.version:
            raise RollingReaderRefused("LEGACY_PUBLICATION_CHANGED")
        store = SegmentedPostgresShadowObservationStore(conn, observation_id=observation_id)
        genesis = store.genesis()
        if genesis is None:
            raise RollingReaderRefused("ATTESTED_CHECKPOINT_REQUIRED")
        observer = ShadowObserver.resume(
            store=store, observation_id=observation_id,
            starting_cash=genesis["starting_cash"], first_session=genesis["first_session"],
            controller_config=controller_config, strategy_identity=genesis["strategy_identity"],
            runtime_identity=genesis["runtime_identity"])
        runtime = PostgresShadowRuntime(conn, observer=observer, warmup_input_loader=_no_warmup)
        prior, origin = checkpoint(runtime)
        if request.strategy_sha256 != digest(prior.strategy_identity):
            raise RollingReaderRefused("CHECKPOINT_STRATEGY_MISMATCH")
        if request.cursor is None or str(request.cursor) != prior.last_processed_session:
            raise RollingReaderRefused("CHECKPOINT_CURSOR_MISMATCH")
        target = str(request.window.end)
        if target != calendar.next_session(prior.last_processed_session):
            raise RollingReaderRefused("CHECKPOINT_SUCCESSOR_REQUIRED")
        manifest = rolling_store.verify_content(conn, comparison["candidate_id"])
        if manifest.window != request.window:
            raise RollingReaderRefused("COMPARISON_WINDOW_MISMATCH")
        reader = RollingPriceReader(conn, candidate_id=comparison["candidate_id"],
                                    snapshot_id=comparison["snapshot_id"])
        reader.require_checkpoint_window(prior)
        baseline = load_published_session(
            conn, target, spy_sessions=manifest.requirements.spy_sessions,
            known_feed_security_ids=tuple(prior.feed["series"]))
        if baseline.data_version != legacy.version:
            raise RollingReaderRefused("BASELINE_PUBLICATION_MISMATCH")
        result = compare_transition(reader, prior=prior, baseline=baseline,
                                    controller_config=controller_config)
        return {
            "schema": "sentinel.rolling-price-reader-rehearsal/1",
            "status": "PRICE_READER_PARITY_PASS", "scope": "PRICE_READER_COMPARISON_ONLY",
            "operational_go": False, "comparison": comparison,
            "reference_sha256": manifest.reference_sha256,
            "checkpoint": origin, "legacy_publication_version": legacy.version,
            "shared_legacy_inputs": list(SHARED_LEGACY_INPUTS), **result,
        }
