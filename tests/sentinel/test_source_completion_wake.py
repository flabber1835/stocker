"""Real durable retries consume producer changes only as scheduling hints."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from sentinel.automation import source_completion
from sentinel.automation.model import (
    CycleState, NonRetryableCallbackRefused, SourceDataPending, TickAction,
)
from sentinel.feed import store as feed_store
from sentinel.rolling_authority import name
from tests.sentinel.test_automation_service import (
    AFTER_WEDNESDAY_CLOSE, THURSDAY_AFTER_OPEN, THURSDAY_AFTER_CLOSE,
    conn, pg, config, enable, service_for, refresh_result,
)


DECISION = date(2026, 8, 12)
PREVIOUS = date(2026, 8, 11)


@pytest.fixture
def publications(conn):
    # The helper reads these native pointer columns, never publication JSON.
    conn.execute(
        "CREATE TABLE sentinel_corpus_publications (version bigserial PRIMARY KEY,"
        "window_end date NOT NULL,evidence jsonb NOT NULL DEFAULT '{}'::jsonb)"
    )
    conn.execute("INSERT INTO sentinel_corpus_publications(window_end) VALUES (%s)", (PREVIOUS,))
    conn.commit()
    return conn


def read_hint(database_url, *, observation_id="primary", decision_session=DECISION):
    connection = feed_store.connect(database_url)
    try:
        connection.execute("BEGIN TRANSACTION READ ONLY")
        return source_completion.read(connection, observation_id=observation_id,
                                      decision_session=decision_session)
    finally:
        connection.rollback()
        connection.close()


def publish(conn, session=DECISION):
    conn.execute("INSERT INTO sentinel_corpus_publications(window_end) VALUES (%s)", (session,))
    conn.commit()


def attest(conn, *, observation_id="primary", session=DECISION, stored_session=None):
    conn.execute(
        "INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,'{}')",
        (name(observation_id, str(session)), stored_session or session),
    )
    conn.commit()


def worker(cfg, database_url, callback):
    result = service_for(cfg, refresh=callback)
    result.source_completion_hint = lambda cycle: read_hint(
        database_url, decision_session=cycle.decision_session)
    return result


def test_hint_reads_both_handoffs_without_loading_state(publications, pg):
    before = read_hint(pg.sync_dsn)
    assert before.publication_frontier == PREVIOUS
    assert before.attestation_row is None
    assert not source_completion.progressed(before, before, decision_session=DECISION)
    publish(publications)
    published = read_hint(pg.sync_dsn)
    assert source_completion.progressed(before, published, decision_session=DECISION)
    attest(publications, observation_id="foreign")
    assert read_hint(pg.sync_dsn) == published
    attest(publications)
    completed = read_hint(pg.sync_dsn)
    assert source_completion.progressed(published, completed, decision_session=DECISION)
    assert not source_completion.progressed(completed, completed, decision_session=DECISION)
    assert not source_completion.progressed(completed, published, decision_session=DECISION)


@pytest.mark.parametrize("bad", ["missing", "malformed", "foreign", "later", "regression"])
def test_missing_foreign_and_invalid_hints_cannot_shorten_retry(publications, pg, bad):
    before = read_hint(pg.sync_dsn)
    publish(publications)
    after = read_hint(pg.sync_dsn).model_dump(mode="json")
    if bad == "missing":
        after = None
    elif bad == "malformed":
        after["publication_row"]["unexpected"] = True
    elif bad == "foreign":
        after["observation_id"] = "foreign"
    elif bad == "later":
        after["decision_session"] = "2026-08-13"
    else:
        after["publication_version"] = 0
    assert not source_completion.progressed(before, after, decision_session=DECISION)


def test_wrong_attestation_session_is_unavailable(publications, pg):
    publish(publications)
    attest(publications, stored_session=PREVIOUS)
    assert read_hint(pg.sync_dsn) is None


@pytest.mark.parametrize("recovery", [False, True])
@pytest.mark.parametrize("mode", ["dual", "paper"])
def test_production_runtime_wires_only_dual_paper_hint(
        publications, pg, tmp_path, monkeypatch, recovery, mode):
    from sentinel import automation_runtime, automation_recovery
    from sentinel.config import SentinelConfig

    monkeypatch.setenv("SENTINEL_REVIEWED_DEPLOYMENT_MODE", mode)
    monkeypatch.setenv("SENTINEL_SHADOW_OBSERVATION_ID", "primary")
    runtime_class = (automation_recovery.ProductionAutomation if recovery
                     else automation_runtime.ProductionAutomation)
    runtime = runtime_class(sentinel_config=SentinelConfig(
        alpaca_key="", alpaca_secret="", base_url="https://paper-api.alpaca.markets",
        state_dir=tmp_path, max_cycles=1, poll_seconds=1, database_url=pg.sync_dsn),
        automation_config=config())
    assert runtime.service.source_completion_hint.__self__ is runtime
    observed = runtime.source_completion_hint(SimpleNamespace(decision_session=DECISION))
    assert observed == (read_hint(pg.sync_dsn) if mode == "dual" else None)


@pytest.mark.asyncio
async def test_publication_then_attestation_each_wakes_once_across_restart(publications, pg):
    cfg = config().model_copy(update={"retry_base_seconds": 900, "retry_max_seconds": 900})
    enable(publications, cfg)
    calls = []

    def refresh(context):
        calls.append(context.cycle.cycle_id)
        hint = read_hint(pg.sync_dsn)
        if hint.publication_frontier != DECISION or hint.attestation_row is None:
            raise SourceDataPending("the exact source and attestation are pending")
        return refresh_result(context)

    running = worker(cfg, pg.sync_dsn, refresh)
    assert (await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)).action is TickAction.RECOVERED
    first = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    assert first.action is TickAction.RETRY_SCHEDULED and len(calls) == 1
    original_wake = first.cycle.next_wake_at
    original_cycle = first.cycle.cycle_id
    saved = first.cycle.diagnostic["source_completion_hint"]
    assert saved["publication_frontier"] == str(PREVIOUS)
    assert original_wake == AFTER_WEDNESDAY_CLOSE + timedelta(seconds=900)

    # Recreate the service: the baseline belongs to the durable cycle.
    running = worker(cfg, pg.sync_dsn, refresh)
    now = AFTER_WEDNESDAY_CLOSE + timedelta(seconds=1)
    waiting = await running.tick(publications, now=now)
    assert waiting.action is TickAction.WAITING and len(calls) == 1
    assert waiting.cycle.next_wake_at == original_wake

    publish(publications)
    publication_wake = await running.tick(publications, now=now)
    assert publication_wake.action is TickAction.RETRY_SCHEDULED and len(calls) == 2
    assert publication_wake.cycle.cycle_id == original_cycle
    assert publication_wake.cycle.diagnostic["phase_attempt_count"] == 2
    second_wake = publication_wake.cycle.next_wake_at
    assert second_wake == now + timedelta(seconds=900)
    for _ in range(3):
        unchanged = await running.tick(publications, now=now)
        assert unchanged.action is TickAction.WAITING and len(calls) == 2
        assert unchanged.cycle.next_wake_at == second_wake

    attest(publications, observation_id="foreign")
    assert (await running.tick(publications, now=now)).action is TickAction.WAITING
    assert len(calls) == 2
    attest(publications)
    running = worker(cfg, pg.sync_dsn, refresh)
    completed = await running.tick(publications, now=now)
    assert completed.action is TickAction.REFRESHED and len(calls) == 3
    assert completed.cycle.state is CycleState.PREPARING
    assert completed.cycle.cycle_id == original_cycle
    assert "source_completion_hint" not in completed.cycle.diagnostic
    assert (await running.tick(publications, now=now)).action is TickAction.PREPARED
    # The wake only advances the ordinary state machine; the original open is unchanged.
    assert (await running.tick(publications, now=now)).action is TickAction.WAITING
    assert (await running.tick(publications, now=THURSDAY_AFTER_OPEN)).action is TickAction.EXECUTED


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unreadable", "missing", "malformed", "foreign"])
async def test_hint_loss_preserves_retry_and_normal_due_recovery(publications, pg, failure):
    cfg = config()
    enable(publications, cfg)
    calls = []

    def refresh(context):
        calls.append(1)
        raise SourceDataPending("source pending")

    running = worker(cfg, pg.sync_dsn, refresh)
    await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    first = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    publish(publications)
    if failure == "unreadable":
        def broken(_cycle):
            raise RuntimeError("unreadable optional hint")
        running.source_completion_hint = broken
    elif failure == "foreign":
        running.source_completion_hint = lambda cycle: read_hint(
            pg.sync_dsn, decision_session=DECISION + timedelta(days=1))
    else:
        running.source_completion_hint = lambda cycle: None if failure == "missing" else {"invalid": True}
    waiting = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE + timedelta(seconds=1))
    assert waiting.action is TickAction.WAITING and len(calls) == 1
    assert waiting.cycle.next_wake_at == first.cycle.next_wake_at
    due = await running.tick(publications, now=first.cycle.next_wake_at)
    assert due.action is TickAction.RETRY_SCHEDULED and len(calls) == 2


@pytest.mark.asyncio
async def test_legacy_source_wait_without_saved_hint_keeps_backoff(publications, pg):
    cfg = config()
    enable(publications, cfg)

    def pending(_context):
        raise SourceDataPending('source pending without an optional hint')

    running = service_for(cfg, refresh=pending)
    await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    original = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    assert 'source_completion_hint' not in original.cycle.diagnostic
    publish(publications)
    running.source_completion_hint = lambda cycle: read_hint(pg.sync_dsn)
    waiting = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE + timedelta(seconds=1))
    assert waiting.action is TickAction.WAITING
    assert waiting.cycle.next_wake_at == original.cycle.next_wake_at


@pytest.mark.asyncio
async def test_changed_hint_does_not_override_financial_refusal(publications, pg):
    cfg = config()
    enable(publications, cfg)
    ready = False
    calls = []

    def refresh(context):
        calls.append(1)
        if not ready:
            raise SourceDataPending("source pending")
        raise NonRetryableCallbackRefused("full current verification refused")

    running = worker(cfg, pg.sync_dsn, refresh)
    await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    publish(publications)
    ready = True
    blocked = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE + timedelta(seconds=1))
    assert blocked.action is TickAction.BLOCKED and len(calls) == 2
    assert blocked.cycle.failure_code == "NonRetryableCallbackRefused"
    assert blocked.cycle.plan_id is None
    assert publications.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_newer_obligation_supersedes_stale_wait_before_hint(publications, pg):
    cfg = config()
    enable(publications, cfg)

    def refresh(_context):
        raise SourceDataPending("source pending")

    running = worker(cfg, pg.sync_dsn, refresh)
    await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    original = await running.tick(publications, now=AFTER_WEDNESDAY_CLOSE)
    publish(publications)
    attest(publications)
    superseded = await running.tick(publications, now=THURSDAY_AFTER_CLOSE)
    assert superseded.action is TickAction.SUPERSEDED
    assert superseded.cycle.cycle_id == original.cycle.cycle_id
    assert superseded.cycle.failure_code == "MISSED_EXECUTION_WINDOW"
    assert publications.execute("SELECT COUNT(*) FROM sentinel_commands").fetchone()[0] == 0


__all__ = ["conn", "pg"]
