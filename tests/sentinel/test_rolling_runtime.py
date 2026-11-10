"""Real rolling runtime approval, interrupted commit recovery and service routing."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel import rolling_runtime as runtime, rolling_authority as authority
from sentinel import rolling_initialization as initial, rolling_daily_checkpoint as daily_cp
from sentinel import rolling_checkpoint as origin, shadow_runtime, shadow_service, shadow_recovery, shadow_observation as shadow
from sentinel.feed import rolling_go_inputs as inputs, operational_snapshot as op, store, calendar
from sentinel.feed.rolling_contract import PriceWindow, canonical_json, digest
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS, NOW
from tests.sentinel.test_rolling_daily import refresh
from tests.sentinel.test_alpaca_operational_snapshot import alpaca_path  # noqa: F401


def advance(conn, session="2026-09-14"):
    return runtime.advance(conn, through=session, observation_id=OBS, starting_cash=100_000)


def status(conn):
    return runtime.status(conn, observation_id=OBS, starting_cash=100_000)


def classify(conn, **kwargs):
    return runtime.classify(conn, observation_id=OBS, starting_cash=100_000, **kwargs)


def test_first_runtime_approval_is_signed_bound_and_idempotent(conn, published):
    assert classify(conn)["status"] == "NOT_STARTED"
    result = advance(conn)
    assert result.verification == shadow.VERIFIED and result.shadow_verdict == shadow.SHADOW_GO
    assert result.to_dict()["verification_scope"] == authority.SCOPE
    value = authority.latest(conn, OBS)[0]
    authority.require_binding(value, origin.read(conn))
    assert value.previous_authority_sha256 is None
    conn.rollback()
    again = advance(conn)
    assert again.state.state_hash == result.state.state_hash and not again.appended
    assert len(authority.latest(conn, OBS)) == 1
    assert initial.resume(conn, observation_id=OBS, starting_cash=100_000).verification == shadow.CANDIDATE
    for table in ("sentinel_execution_plans", "sentinel_commands", "sentinel_fills"):
        assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0


def test_new_attestation_persists_its_already_measured_readiness(conn, published, monkeypatch):
    from sentinel.feed import readers, readiness
    monkeypatch.setattr(readiness, 'check_readiness', lambda *_a, **_kw:
                        pytest.fail('attestation repeated a legacy full readiness scan'))
    result = advance(conn)
    frontier, snapshot = readers.status_snapshot(conn)
    assert frontier == result.session and snapshot is not None and snapshot.ready
    assert readers.snapshot_matches(readers.current(conn), snapshot)


@pytest.mark.parametrize('premature_commit', [False, True])
def test_attestation_and_display_verdict_share_the_final_commit(conn, published, monkeypatch, premature_commit):
    from sentinel.feed import readers, readiness
    before = conn.execute('SELECT count(*) FROM sentinel_readiness_snapshots').fetchone()[0]
    conn.rollback()
    save = readiness.save_snapshot
    class InjectedFailure(RuntimeError):pass
    def fail_after_insert(c, report, *, commit=True):
        assert commit is False
        save(c, report, commit=premature_commit)
        raise InjectedFailure('after readiness insert, before attestation commit')
    with monkeypatch.context() as damaged:
        damaged.setattr(readiness, 'save_snapshot', fail_after_insert)
        with pytest.raises(InjectedFailure):advance(conn)
    def atomic():
        assert authority.latest(conn, OBS) == []
        assert conn.execute('SELECT count(*) FROM sentinel_readiness_snapshots').fetchone()[0] == before
        conn.rollback()
    if premature_commit:
        # Executed falsifier: committing the auxiliary INSERT exposes the
        # financial attestation even though its final transaction then failed.
        with pytest.raises(AssertionError):atomic()
    else:
        atomic()
        result = advance(conn)
        assert result.verification == shadow.VERIFIED
        assert readers.status_snapshot(conn)[1].ready


def test_same_session_service_verifies_without_account_writer(conn, published, monkeypatch):
    """The real service read must coexist with the execution writer at open."""
    from sentinel.execution import journal
    expected = advance(conn)
    conn.rollback()
    reads=[]
    actual_closure=runtime._closure
    def read_once(*args,**kwargs):
        reads.append(True)
        return actual_closure(*args,**kwargs)
    monkeypatch.setattr(runtime,'_closure',read_once)
    other = store.connect(conn.info.dsn)
    try:
        with journal.writer_lock(other):
            actual = runtime.service_advance(
                conn, through=expected.session, observation_id=OBS,
                starting_cash=100_000)
            assert actual.record_sha256 == expected.record_sha256
            assert actual.verification == shadow.VERIFIED
            assert len(reads)==1
    finally:
        other.rollback()
        other.close()


def test_same_session_service_renews_measured_feed_evidence(conn, published, monkeypatch):
    from sentinel.feed import readers, readiness
    from sentinel.panel import model

    expected = advance(conn)
    readiness.save_snapshot(conn, readers.readiness(conn))
    conn.execute("UPDATE sentinel_readiness_snapshots SET computed_at=NOW()-INTERVAL '3 days'")
    conn.commit()
    assert readers.status_snapshot(conn)[1].stale
    authority_before = authority.latest(conn, OBS)
    conn.rollback()
    validations = []
    original = runtime._current

    def measured(*args, **kwargs):
        validations.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, '_current', measured)
    result = runtime.service_advance(
        conn, through=expected.session, observation_id=OBS, starting_cash=100_000)
    frontier, fresh = readers.status_snapshot(conn)
    assert len(validations) == 1, "display refresh must reuse the current canonical measurement"
    assert fresh.trustworthy and not fresh.stale
    assert readers.snapshot_matches(readers.current(conn), fresh)
    assert any(check['name'] == 'rolling immutable input closure' for check in fresh.checks)
    now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
    row = model.feed_row(frontier=frontier, sessions_behind=0, ready=fresh.ready,
        checks_passed=fresh.checks_passed, checks_total=fresh.checks_total,
        as_of=fresh.computed_at, checked_at=fresh.computed_at)
    assert row.effective_status(now) == model.OK
    assert result.record_sha256 == expected.record_sha256
    assert authority.latest(conn, OBS) == authority_before
    for table in ('sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills'):
        assert conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0


@pytest.mark.parametrize('defect', ['missing_source_session', 'corrupt_content'])
def test_failed_same_session_verification_cannot_renew_feed_pass(conn, published, monkeypatch, defect):
    from sentinel.feed import readers, readiness, rolling_store

    expected = advance(conn)
    readiness.save_snapshot(conn, readers.readiness(conn))
    conn.execute("UPDATE sentinel_readiness_snapshots SET computed_at=NOW()-INTERVAL '3 days'")
    conn.commit()
    prior = readiness.latest_snapshot(conn)
    count = conn.execute('SELECT COUNT(*) FROM sentinel_readiness_snapshots').fetchone()[0]
    conn.rollback()
    if defect == 'missing_source_session':
        monkeypatch.setattr(inputs.snapshots, 'source_final_session', lambda *_: '2026-09-15')
        error = inputs.RollingSourceFrontierPending
    else:
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('UPDATE sentinel_snapshot_bars SET volume=volume+1 WHERE candidate_id=%s',
                     (published['candidate_id'],))
        conn.commit()
        error = rolling_store.SnapshotStorageRefused
    with pytest.raises(error):
        runtime.service_advance(
            conn, through=expected.session, observation_id=OBS, starting_cash=100_000)
    latest = readiness.latest_snapshot(conn)
    assert latest.computed_at == prior.computed_at and latest.stale
    assert conn.execute('SELECT COUNT(*) FROM sentinel_readiness_snapshots').fetchone()[0] == count


def test_removed_same_session_read_path_is_detected(conn, monkeypatch):
    import inspect
    from sentinel.execution import journal
    marker = object()
    from sentinel.feed import readiness
    report = readiness.Readiness()
    report.add('rolling publication binding', readiness.PASS, 'b' * 64)
    monkeypatch.setattr(runtime, 'classify', lambda *_a, **_k:
        {'status':'VERIFIED_UNCHANGED','result':marker,'inventory_sha256':'a'*64,
         '_readiness_snapshot':report})
    monkeypatch.setattr(runtime, '_refresh_unchanged_health', lambda *_a, **_k: None)
    monkeypatch.setattr(initial, '_now', lambda _: NOW)
    source = inspect.getsource(runtime.service_advance)
    mutant = source.replace('if classified["status"] == "VERIFIED_UNCHANGED":', 'if False:')
    assert mutant != source
    namespace = dict(vars(runtime))
    exec(mutant, namespace)
    peer = store.connect(conn.info.dsn)
    try:
        with journal.writer_lock(peer):
            args=dict(through='2026-09-14',observation_id=OBS,starting_cash=100_000)
            assert runtime.service_advance(conn, **args) is marker
            with pytest.raises(journal.WriterLockUnavailable):
                namespace['service_advance'](conn, **args)
    finally:
        peer.close()


def test_committed_candidate_requires_runtime_attestation(conn, published):
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    assert classify(conn)["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(authority.Refused, match="ATTESTATION_REQUIRED"):
        status(conn)
    assert advance(conn).verification == shadow.VERIFIED


def test_authority_failure_preserves_candidate_and_recovery_never_replays(conn, published, monkeypatch):
    original = authority.append
    monkeypatch.setattr(authority, "append", lambda *_: (_ for _ in ()).throw(OSError("authority interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        advance(conn)
    checkpoint = origin.read(conn)
    assert checkpoint is not None and authority.latest(conn, OBS) == []
    conn.rollback()
    monkeypatch.setattr(authority, "append", original)
    monkeypatch.setattr(initial, "initialize", lambda *_a, **_k: pytest.fail("candidate replayed"))
    monkeypatch.setattr(shadow, "advance_state", lambda *_a, **_k: pytest.fail("kernel replayed"))
    result = advance(conn)
    assert result.state.state_hash == checkpoint.state_sha256
    assert result.verification == shadow.VERIFIED and not result.appended


def test_postcommit_cutoff_crossing_cannot_issue_authority(conn, published, monkeypatch):
    original = initial.initialize
    def crossing(*args, **kwargs):
        result = original(*args, **kwargs)
        opened, _ = calendar.session_window(calendar.next_session(result.session))
        monkeypatch.setattr(initial, "_now", lambda conn: opened)
        return result
    monkeypatch.setattr(initial, "initialize", crossing)
    with pytest.raises(origin.RollingColdStartRefused, match="MISSED_OPEN"):
        advance(conn)
    assert origin.read(conn) is not None and authority.latest(conn, OBS) == []
    conn.rollback()
    with pytest.raises(origin.RollingColdStartRefused, match="MISSED_OPEN"):
        classify(conn)


def test_lost_authority_commit_acknowledgement_recovers_exact_row(conn, published, monkeypatch):
    original = authority.append
    state = {"written": False, "raised": False}
    def append(*args):
        original(*args)
        state["written"] = True
    monkeypatch.setattr(authority, "append", append)
    class LostAck:
        def __getattr__(self, name):
            return getattr(conn, name)
        def commit(self):
            conn.commit()
            if state["written"] and not state["raised"]:
                state["raised"] = True
                raise OSError("lost authority acknowledgement")
    with pytest.raises(OSError, match="lost authority"):
        advance(LostAck())
    before = authority.latest(conn, OBS)[0]
    conn.rollback()
    monkeypatch.setattr(authority, "append", lambda *_: pytest.fail("duplicate authority"))
    result = advance(conn)
    assert result.runtime_authority_sha256 == digest(before.model_dump(by_alias=True))


@pytest.mark.parametrize("defect", ["signature", "checkpoint", "runtime", "timing", "chain"])
def test_authority_tamper_refuses_runtime_status(conn, published, defect):
    advance(conn)
    value = authority.latest(conn, OBS)[0].model_dump(by_alias=True)
    if defect in {"checkpoint", "runtime"}:
        value[defect + "_sha256"] = "a" * 64
    elif defect == "timing":
        value["timing"]["candidate_committed_at"] = value["timing"]["execution_open_at"]
    elif defect == "chain":
        value["previous_authority_sha256"] = "b" * 64
    raw = {"authority": value, "hmac_sha256": "0" * 64 if defect == "signature" else authority.signature(value)}
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 (canonical_json(raw), authority.name(OBS, value["session"])))
    conn.commit()
    with pytest.raises(shadow.ShadowObservationRefused):
        status(conn)


def test_status_is_readonly_without_warmup_or_transition(conn, published, monkeypatch):
    advance(conn)
    original = runtime._closure
    def closure(conn, context, **kwargs):
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SHOW transaction_isolation").fetchone()[0] == "repeatable read"
        return original(conn, context, **kwargs)
    monkeypatch.setattr(runtime, "_closure", closure)
    monkeypatch.setattr(initial, "warm_session_state", lambda *_a, **_k: pytest.fail("rewarmed"))
    monkeypatch.setattr(shadow, "advance_state", lambda *_a, **_k: pytest.fail("replayed"))
    assert status(conn).verification == shadow.VERIFIED


def test_daily_runtime_continuation_and_bounded_restart(conn, published, operational_source, monkeypatch):
    first = advance(conn)
    refresh(conn, operational_source, monkeypatch)
    with pytest.raises(authority.Refused, match="PUBLICATION_CHANGED"):
        status(conn)
    history = shadow.ShadowObserver._history
    reads = []
    def counted(observer, *args, **kwargs):
        reads.append(True)
        return history(observer, *args, **kwargs)
    with monkeypatch.context() as counting:
        counting.setattr(shadow.ShadowObserver, '_history', counted)
        second = advance(conn, "2026-09-15")
    # Initial authenticated closure, observation before/after, committed closure.
    assert len(reads) == 4
    assert second.state.wealth_core["episodes"]
    assert second.state.state_hash != first.state.state_hash
    assert status(conn).state.state_hash == second.state.state_hash
    conn.execute("SET LOCAL session_replication_role=replica")
    for table in ("sentinel_snapshot_bars", "sentinel_snapshot_benchmarks"):
        conn.execute("DELETE FROM " + table + " WHERE candidate_id=%s", (published["candidate_id"],))
    conn.commit()
    assert status(conn).verification == shadow.VERIFIED
    refresh(conn, operational_source, monkeypatch)
    third = advance(conn, "2026-09-16")
    assert third.verification == shadow.VERIFIED
    assert len(authority.latest(conn, OBS)) == 2
    assert status(conn).state.state_hash == third.state.state_hash


def test_daily_cannot_skip_missing_predecessor_authority(conn, published, operational_source, monkeypatch):
    advance(conn)
    refresh(conn, operational_source, monkeypatch)
    advance(conn, "2026-09-15")
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s", (authority.name(OBS, "2026-09-14"),))
    conn.commit()
    with pytest.raises(authority.Refused, match="PREDECESSOR_AUTHORITY_REQUIRED"):
        status(conn)


def test_unattested_candidate_cannot_be_skipped_by_new_publication(conn, published, operational_source, monkeypatch):
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    refresh(conn, operational_source, monkeypatch)
    with pytest.raises(authority.Refused, match="CANDIDATE_MUST_BE_ATTESTED_FIRST"):
        advance(conn, "2026-09-15")
    assert daily_cp.read(conn) is None


def test_runtime_requires_exact_target_and_adjacent_session(conn, published, operational_source, monkeypatch):
    with pytest.raises(authority.Refused, match="TARGET_CHANGED"):
        advance(conn, "2026-09-15")
    advance(conn)
    refresh(conn, operational_source, monkeypatch, days=2)
    with pytest.raises(authority.Refused, match="SESSION_GAP"):
        advance(conn, "2026-09-16")


def test_backup_refusal_after_candidate_commit_cannot_issue_authority(conn, published, monkeypatch):
    original = runtime.backup_runtime_authority.require
    def require(conn, *, operation, allow_continuity=False):
        if operation == "rolling runtime attestation":
            assert allow_continuity is False
            raise RuntimeError("backup refused")
        return original(conn, operation=operation, allow_continuity=allow_continuity)
    monkeypatch.setattr(runtime.backup_runtime_authority, "require", require)
    with pytest.raises(RuntimeError, match="backup refused"):
        advance(conn)
    assert origin.read(conn) is not None and authority.latest(conn, OBS) == []


def test_publication_and_writer_locks_span_candidate_and_authority_commits(conn, published, monkeypatch):
    import psycopg
    from sentinel.execution import journal
    from sentinel.feed import publication
    original = authority.append
    observed = []
    def append(conn, value):
        with psycopg.connect(conn.info.dsn) as contender:
            for key in (publication.CORPUS_LOCK_KEY, journal.WRITER_LOCK_KEY):
                acquired = contender.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
                if acquired:
                    contender.execute("SELECT pg_advisory_unlock(%s)", (key,))
                observed.append(acquired)
        original(conn, value)
    monkeypatch.setattr(authority, "append", append)
    advance(conn)
    assert observed == [False, False]


def test_changed_reviewed_runtime_withdraws_verification(conn, published, monkeypatch):
    advance(conn)
    original = shadow_runtime._validated_runtime_identity
    monkeypatch.setattr(shadow_runtime, "_validated_runtime_identity",
        lambda **kwargs: {**original(**kwargs), "changed_identity": "different"})
    with pytest.raises(origin.RollingColdStartRefused, match="CONFIG_CHANGED"):
        status(conn)


def test_rolling_book_cannot_dispatch_back_to_legacy_publication(conn, published, monkeypatch):
    advance(conn)
    monkeypatch.setattr(inputs, "current", lambda conn: None)
    with pytest.raises(shadow_runtime.ShadowRuntimeRefused, match="ROLLING_PUBLICATION_REQUIRED"):
        shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100_000)


def test_actual_shadow_service_initializes_and_acquires_next_snapshot(
        conn, published, operational_source, monkeypatch, connection_factory=None):
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", connection_factory or (lambda _: Borrowed()))
    monkeypatch.setattr(shadow_service.ingest, "daily", lambda *_a, **_k: pytest.fail("legacy ingest"))
    config = shadow_service.ShadowServiceConfig("fixture", OBS, Decimal("100000"),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    first = shadow_recovery.advance_once(config, now=NOW)
    assert first["verification_scope"] == authority.SCOPE and first["verification"] == "VERIFIED"
    # Advance only synthetic provider/clock state: the service must publish.
    data = operational_source
    for table in ("SEP", "SFP"):
        rows = [deepcopy(row) for row in data[table] if row["date"] == "2026-09-14"]
        for row in rows:
            row["date"] = "2026-09-15"
        data[table].extend(rows)
    for row in data["TICKERS"]:
        row["lastpricedate"] = "2026-09-15"
    start = str(PriceWindow.through("2026-09-15").start)
    data["SFP"][:] = [row for row in data["SFP"] if row["date"] >= start]
    later = NOW + timedelta(days=1)
    monkeypatch.setattr(calendar, "latest_closed_session", lambda now=None: "2026-09-15")
    monkeypatch.setattr(op, "_now", lambda: later)
    monkeypatch.setattr(initial, "_now", lambda conn: later)
    assert shadow_recovery.service_health(config, now=later)["service_health"] == "HEALTHY_WAITING"
    second = shadow_recovery.advance_once(config, now=later)
    assert second["session"] == "2026-09-15" and second["verification"] == "VERIFIED"
    calls = list(data["calls"])
    assert shadow_recovery.advance_once(config, now=later)["appended"] is False
    assert data["calls"] == calls


def test_production_worker_gap_waits_without_legacy_catchup(conn, published, monkeypatch):
    advance(conn)
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", lambda _: Borrowed())
    attempts = []
    monkeypatch.setattr(shadow_recovery, "_roll_and_advance",
        lambda *_a, **_k: attempts.append("legacy recovery"))
    monkeypatch.setattr(calendar, "latest_closed_session", lambda now=None: "2026-09-16")
    monkeypatch.setattr(initial, "_now", lambda conn: NOW + timedelta(days=2))
    config = shadow_service.ShadowServiceConfig("fixture", OBS, Decimal("100000"),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    with pytest.raises(shadow_service.ShadowServiceWaiting, match="MISSING_DATED_PUBLICATION:2026-09-15"):
        shadow_recovery.advance_once(config, now=NOW + timedelta(days=2))
    assert attempts == []
    assert daily_cp.read(conn) is None
    assert shadow_recovery.service_health(config, now=NOW + timedelta(days=2))["service_health"] == "RECONSTRUCTION_PENDING"


@pytest.fixture
def operational_dispatch(conn, alpaca_path, monkeypatch):
    """Real signed Alpaca publication/checkpoints; only external certification is supplied."""
    from sentinel import schema
    from sentinel.feed import publication
    from sentinel.feed.rolling_contract import CurrentFormationWindow
    schema.ensure_schema(conn)
    # The current production formation window is wider than the older Alpaca
    # fixture's 300-session default. Supply complete native bars, not a bypass.
    alpaca_path.window = CurrentFormationWindow.through('2026-09-14')
    insert = publication._insert_receipted_publication
    def publish_at_fixture_time(connection, **kwargs):
        return insert(connection, **dict(kwargs, published_at=NOW))
    monkeypatch.setattr(publication, '_insert_receipted_publication', publish_at_fixture_time)
    _, strategy = shadow_runtime._strategy()
    job = op.enqueue(conn, strategy_sha256=digest(strategy),
                     dependencies_sha256=digest('operational-dispatch-private-fixture'))
    conn.commit()
    binding = op.prepare(conn, job)
    with op.pinned(conn) as (pub, _):
        subject = shadow_runtime._data_publication_subject_sha256(pub, pub.window_end)
    monkeypatch.setattr(shadow_runtime, '_validated_runtime_identity', lambda **kwargs: {
        'schema': 'test-reviewed-runtime/1', 'validated_data_publication_sha256': subject})
    monkeypatch.setattr(initial, '_now', lambda _: NOW)
    conn.rollback()
    class Borrowed:
        def __getattr__(self, name): return getattr(conn, name)
        def close(self): pass
    monkeypatch.setattr(store, 'connect', lambda _: Borrowed())
    config = shadow_service.ShadowServiceConfig('private-existing-connection', OBS,
        Decimal('100000'), shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300,
        operational_source_only=True)
    return config, binding


def _dispatch_predecessors():
    import hashlib, json
    from pathlib import Path
    from types import ModuleType
    fixture = Path(__file__).resolve().parents[1]/'support/operational-shadow-dispatch-21df-sources.json'
    raw = fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '61388165f25b9fea7e852eda75504e72d07e78f5315088892baec39526a5f761'
    value = json.loads(raw)
    assert value['schema'] == 'sentinel.operational-shadow-dispatch-baseline/1'
    assert value['revision'] == '21dfb0e8508d8d924a8b29a121977b1502997a0c'
    pins = {'sentinel/shadow_recovery.py': '20aa7b13a872092b270235c31c09b836b7e840e694dc1d57e6b73da0ab753e0f',
            'sentinel/shadow_service.py': 'caf4ad5aceb1df3b8b3bf2694f69f27eda42dfb7cec10320555c84bc6a79d572'}
    assert set(value['modules']) == set(pins)
    modules = {}
    for name, expected in pins.items():
        source = value['modules'][name]
        assert hashlib.sha256(source.encode()).hexdigest() == expected
        module = ModuleType('private_' + name.rsplit('/', 1)[1].removesuffix('.py'))
        exec(compile(source, '<authenticated-21df-' + name + '>', 'exec'), vars(module))
        modules[name] = module
    recovery = modules['sentinel/shadow_recovery.py']
    recovery.base = modules['sentinel/shadow_service.py']
    return recovery


def _dispatch_counts(monkeypatch):
    from collections import Counter
    counts = Counter()
    for label, module, name in [('closure', runtime, '_closure'), ('origin', origin, '_read'),
                                ('daily', daily_cp, '_read')]:
        original = getattr(module, name)
        def counted(*args, _label=label, _read=original, **kwargs):
            counts[_label] += 1
            return _read(*args, **kwargs)
        monkeypatch.setattr(module, name, counted)
    return counts


def _dispatch_financial_rows(conn):
    tables = ('sentinel_processed_sessions', 'sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills')
    value = [conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in tables]
    conn.rollback()
    return value


def test_operational_worker_owns_one_signed_unchanged_closure_instead_of_three(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    expected = advance(conn)
    conn.rollback()
    before = _dispatch_financial_rows(conn)
    counts = _dispatch_counts(monkeypatch)
    old = _dispatch_predecessors().advance_once(config, now=NOW)
    assert counts == dict(closure=3, origin=3, daily=3)
    counts.clear()
    actual = shadow_recovery.advance_once(config, now=NOW)
    assert counts == dict(closure=1, origin=1, daily=1), 'operational route repeated a complete proof'
    assert actual == old and actual['record_sha256'] == expected.record_sha256
    assert actual['verification'] == 'VERIFIED' and actual['appended'] is False
    assert _dispatch_financial_rows(conn) == before


@pytest.mark.parametrize('removed', ['recovery', 'service'])
def test_operational_dispatch_work_count_detects_either_reintroduced_route_proof(
        conn, operational_dispatch, monkeypatch, removed):
    config, _ = operational_dispatch
    advance(conn); conn.rollback()
    counts = _dispatch_counts(monkeypatch)
    predecessor = _dispatch_predecessors()
    if removed == 'recovery':
        predecessor.base = shadow_service
        callback = predecessor.advance_once
    else:
        monkeypatch.setattr(shadow_recovery.base, 'advance_once', predecessor.base.advance_once)
        callback = shadow_recovery.advance_once
    callback(config, now=NOW)
    with pytest.raises(AssertionError, match='repeated'):
        assert counts['closure'] == 1, 'operational route repeated a complete proof'
    assert counts['closure'] == 2


@pytest.mark.parametrize('defect', ['signature', 'content', 'source-session', 'publication', 'origin'])
def test_operational_dispatch_retains_fresh_signed_lineage_source_and_publication_refusals(
        conn, operational_dispatch, monkeypatch, defect):
    config, binding = operational_dispatch
    advance(conn); conn.rollback()
    if defect == 'signature':
        assert conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',to_jsonb(%s::text)) "
                     "WHERE cursor_name=%s", ('0'*64, authority.name(OBS, '2026-09-14'))).rowcount == 1
    elif defect == 'content':
        conn.execute('SET LOCAL session_replication_role=replica')
        # Current candidates store shared blocks; the legacy payload table is
        # legitimately empty and changing it would not inject any defect.
        assert conn.execute("DELETE FROM sentinel_candidate_blocks WHERE candidate_id=%s AND kind='BARS' "
            "AND session=(SELECT min(session) FROM sentinel_candidate_blocks WHERE candidate_id=%s AND kind='BARS')",
            (binding['candidate_id'], binding['candidate_id'])).rowcount == 1
    elif defect == 'source-session':
        monkeypatch.setattr(inputs.snapshots, 'source_final_session', lambda *_: '2026-09-15')
    elif defect == 'publication':
        conn.execute('SET LOCAL session_replication_role=replica')
        assert conn.execute("UPDATE sentinel_corpus_publications SET evidence=evidence||'{\"foreign\":true}'::jsonb").rowcount == 1
    else:
        assert conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (origin.CURSOR,)).rowcount == 1
    conn.commit()
    before = _dispatch_financial_rows(conn)
    monkeypatch.setattr(inputs, '_prepare', lambda *_a, **_k: pytest.fail('invalid lineage reached acquisition'))
    with pytest.raises((shadow_service.ShadowServiceRefused, shadow_service.ShadowServiceWaiting)):
        shadow_recovery.advance_once(config, now=NOW)
    assert _dispatch_financial_rows(conn) == before


def test_operational_dispatch_rechecks_source_movement_after_cheap_guard(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    advance(conn); conn.rollback()
    original = shadow_service._require_operational_source
    def moved(connection):
        original(connection)
        connection.rollback()
        connection.execute('SET LOCAL session_replication_role=replica')
        assert connection.execute("UPDATE sentinel_corpus_publications SET evidence=evidence||'{\"foreign\":true}'::jsonb").rowcount == 1
        connection.commit()
    monkeypatch.setattr(shadow_service, '_require_operational_source', moved)
    monkeypatch.setattr(inputs, '_prepare', lambda *_a, **_k: pytest.fail('moved source reached acquisition'))
    with pytest.raises(shadow_service.ShadowServiceRefused):
        shadow_recovery.advance_once(config, now=NOW)


def test_operational_source_guard_falsifier_preserves_legacy_provider_refusal(
        conn, published, monkeypatch):
    advance(conn); conn.rollback()
    config = shadow_service.ShadowServiceConfig('fixture', OBS, Decimal('100000'),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300, operational_source_only=True)
    class Borrowed:
        def __getattr__(self, name): return getattr(conn, name)
        def close(self): pass
    monkeypatch.setattr(store, 'connect', lambda _: Borrowed())
    def refusal():
        with pytest.raises(shadow_service.ShadowServiceRefused, match='ALPACA_OPENFIGI_SOURCE_REQUIRED'):
            shadow_recovery.advance_once(config, now=NOW)
    refusal()
    with monkeypatch.context() as missing:
        missing.setattr(shadow_service, '_require_operational_source', lambda _: None)
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            refusal()


def test_operational_dispatch_recovers_signed_candidate_without_reforming(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    before = origin.read(conn).model_dump(by_alias=True); conn.rollback()
    assert authority.latest(conn, OBS) == []; conn.rollback()
    monkeypatch.setattr(initial, 'initialize', lambda *_a, **_k: pytest.fail('candidate was reformed'))
    actual = shadow_recovery.advance_once(config, now=NOW)
    assert actual['verification'] == 'VERIFIED' and actual['state_sha256'] == before['state_sha256']
    assert origin.read(conn).model_dump(by_alias=True) == before


def test_operational_dispatch_keeps_attestation_backup_fence_after_signed_candidate(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    conn.rollback()
    original = runtime.backup_runtime_authority.require
    def refuse(connection, *, operation, **kwargs):
        if operation == 'rolling runtime attestation':
            from sentinel import backup_guard
            raise backup_guard.BackupWriteFenced('private backup refused')
        return original(connection, operation=operation, **kwargs)
    monkeypatch.setattr(runtime.backup_runtime_authority, 'require', refuse)
    with pytest.raises(shadow_service.ShadowServiceRetry, match='source/backup unavailable'):
        shadow_recovery.advance_once(config, now=NOW)
    assert origin.read(conn) is not None and authority.latest(conn, OBS) == []


def test_operational_dispatch_not_before_and_guard_omission_falsifier(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    advance(conn); conn.rollback()
    not_before = shadow_runtime.publication_not_before('2026-09-14')
    early = not_before - timedelta(microseconds=1)
    def refusal():
        with pytest.raises(shadow_service.ShadowServiceWaiting, match='publication not-before'):
            shadow_recovery.advance_once(config, now=early)
    refusal()
    with monkeypatch.context() as missing:
        missing.setattr(shadow_service, '_causal_target', lambda **_k: '2026-09-14')
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            refusal()


def test_operational_dispatch_original_budget_includes_source_guard(
        conn, operational_dispatch, monkeypatch):
    from sentinel import shadow_budget
    config, _ = operational_dispatch
    clock = [NOW]
    monkeypatch.setattr(shadow_budget, 'now', lambda: clock[0])
    monkeypatch.delenv(shadow_budget.DEADLINE_ENV, raising=False)
    monkeypatch.setenv('SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS', '7200')
    source_guard = shadow_service._require_operational_source
    def slow(connection):
        source_guard(connection); clock[0] += timedelta(seconds=1000)
    monkeypatch.setattr(shadow_service, '_require_operational_source', slow)
    def final(connection, **kwargs):
        assert kwargs['acquisition_deadline'] == NOW + timedelta(seconds=7200)
        assert (kwargs['acquisition_deadline'] - clock[0]).total_seconds() == 6200
        from types import SimpleNamespace
        return SimpleNamespace(to_dict=lambda: {'bounded': True})
    monkeypatch.setattr(runtime, 'service_advance', final)
    assert shadow_recovery.advance_once(config, now=NOW) == {'bounded': True}


def test_operational_dispatch_forms_fresh_genesis_without_route_proofs(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    assert origin.read(conn) is None; conn.rollback()
    monkeypatch.setattr(shadow_service, 'preflight', lambda *_a, **_k:
                        pytest.fail('operational genesis repeated a route proof'))
    actual = shadow_recovery.advance_once(config, now=NOW)
    assert actual['verification'] == 'VERIFIED' and actual['appended'] is True
    authority.require_binding(authority.latest(conn, OBS)[0], origin.read(conn))
    assert _dispatch_financial_rows(conn)[1:] == [0, 0, 0]


def test_operational_dispatch_expired_candidate_is_reconstruction_never_prospective_go(
        conn, operational_dispatch, monkeypatch):
    config, _ = operational_dispatch
    candidate = initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    conn.rollback()
    later = NOW + timedelta(days=2)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: '2026-09-16')
    monkeypatch.setattr(op, '_now', lambda: later)
    monkeypatch.setattr(initial, '_now', lambda _: later)
    monkeypatch.setattr(initial, 'initialize', lambda *_a, **_k: pytest.fail('expired candidate reformed'))
    actual = shadow_recovery.advance_once(config, now=later)
    assert actual['state_sha256'] == candidate.state.state_hash
    assert actual['verification'] == shadow.CANDIDATE
    assert actual['shadow_verdict'] == shadow.NOT_DEPLOYABLE
    assert actual['verification_scope'] == 'ROLLING_RECONSTRUCTION_ONLY'
    assert isinstance(authority.latest(conn, OBS)[0], authority.ReconstructionReceipt)


def test_operational_dispatch_gap_keeps_exact_data_only_recovery_and_provider_refusal(
        conn, operational_dispatch, monkeypatch):
    from sentinel import shadow_budget
    config, _ = operational_dispatch
    first = advance(conn); conn.rollback()
    financial_before = _dispatch_financial_rows(conn)
    publication_before = op._current(conn).to_dict(); conn.rollback()
    later = NOW + timedelta(days=2)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: '2026-09-16')
    monkeypatch.setattr(op, '_now', lambda: later)
    monkeypatch.setattr(initial, '_now', lambda _: later)
    monkeypatch.setattr(inputs, '_prepare', lambda *_a, **_k: pytest.fail('missing history backdated'))
    monkeypatch.setattr(shadow_recovery, '_roll_and_advance', lambda *_a, **_k:
                        pytest.fail('operational publication entered legacy rollover'))
    original_deadline = shadow_budget.now() + timedelta(hours=1)
    monkeypatch.setenv(shadow_budget.DEADLINE_ENV, original_deadline.isoformat())
    requests = []
    enqueue = op.enqueue_reconstruction
    def record_recovery(connection, **kwargs):
        requests.append(kwargs)
        return enqueue(connection, **kwargs)
    monkeypatch.setattr(op, 'enqueue_reconstruction', record_recovery)
    # Current-window recovery may acquire the exact missing dated data; this
    # provider fixture deliberately has no Sep15 coverage. Its hard native
    # refusal must not become a backdated publication or prospective authority.
    with pytest.raises(shadow_service.ShadowServiceRefused, match='BIL split-only/raw prices lack corroborated coverage'):
        shadow_recovery.advance_once(config, now=later)
    assert len(requests) == 1
    assert requests[0]['session'] == '2026-09-15' and requests[0]['cursor'] == '2026-09-14'
    assert requests[0]['absolute_deadline'] == original_deadline
    assert daily_cp.read(conn) is None
    assert origin.read(conn).state_sha256 == first.state.state_hash
    assert len(authority.latest(conn, OBS)) == 1
    assert _dispatch_financial_rows(conn) == financial_before
    assert op._current(conn).to_dict() == publication_before


def test_operational_fresh_genesis_rejects_valid_publication_moving_after_source_guard(
        conn, operational_dispatch, monkeypatch):
    from sentinel.feed import readers, rolling_store
    config, old_binding = operational_dispatch
    # Build another publication through its real signed publisher. Only private
    # provider responses are fixtures; no publication/receipt guard is replaced.
    original = shadow_service._require_operational_source
    observed = []
    def move_after_guard(connection):
        original(connection)
        connection.rollback()
        _, strategy = shadow_runtime._strategy()
        job = op.enqueue(connection, strategy_sha256=digest(strategy),
                         dependencies_sha256=digest('valid-native-publication-movement'))
        connection.commit()
        new_binding = op.prepare(connection, job)
        assert new_binding['data_version'] != old_binding['data_version']
        current = readers.current(connection)
        bound = op._bound(connection, current)
        assert rolling_store.manifest(connection, bound['candidate_id']).provider == 'ALPACA_OPENFIGI'
        with inputs.pinned(connection) as held:
            _binding, report = inputs.validate_status(connection, held)
            assert report.ready, 'publication-movement counterexample must have complete valid inputs'
        observed.append(bound)
        connection.rollback()
    monkeypatch.setattr(shadow_service, '_require_operational_source', move_after_guard)
    with pytest.raises(shadow_service.ShadowServiceRefused, match='UNREVIEWED_GENESIS_PUBLICATION'):
        shadow_recovery.advance_once(config, now=NOW)
    assert len(observed) == 1 and origin.read(conn) is None
    assert authority.latest(conn, OBS) == []
    assert _dispatch_financial_rows(conn)[1:] == [0, 0, 0]
