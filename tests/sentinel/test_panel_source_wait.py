"""Typed source waits retain only authenticated, explicitly historical display."""
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import inspect
from types import SimpleNamespace

import pytest

from sentinel import rolling_runtime as runtime, shadow_runtime
from sentinel.feed.rolling_go_inputs import RollingSourceFrontierPending
from sentinel.panel import authority_reader as reader, model, sources
from sentinel.panel import shadow_source_wait as waiting
from tests.sentinel.test_panel_authority_reader import complete, surfaces

NOW = datetime(2026, 10, 22, 20, 10, tzinfo=timezone.utc)
ATTESTED = datetime(2026, 10, 21, 21, tzinfo=timezone.utc)
DEADLINE = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def historical_ui_database_profile(request, tmp_path, monkeypatch):
    if request.node.name != 'test_real_retained_attestation_survives_close_wait_and_fails_tampering':
        return
    # This explicitly synthetic formation fixture has no deployed recovery
    # media. Match its existing developer policy without changing a registry,
    # touching backup media or bypassing any publication/attestation guard.
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER',
                        tmp_path / 'absent-production-backup-policy')
    monkeypatch.delenv(backup_runtime_authority.AUTHORITY_ENV, raising=False)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'test-only-receipt-key-'*4)


def refused(cause=None):
    error = shadow_runtime.ShadowRuntimeRefused('ROLLING_INPUTS_NOT_READY: rolling source-final frontier')
    error.__cause__ = cause
    return error


@pytest.fixture
def history(monkeypatch):
    from sentinel import committed_read
    class Connection:
        def execute(self, query):
            assert query == 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'
        def rollback(self):
            pass
        def close(self):
            pass
    conn = Connection()
    @contextmanager
    def synthetic_proof(subject):
        # Only this already synthetic historical-material fixture uses a fake
        # connection. Real ownership is covered on PG by the transaction tests;
        # the retained-attestation case below uses the actual public helper.
        assert subject is conn
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        try:
            yield conn
        finally:
            conn.rollback()
    monkeypatch.setattr(committed_read, 'proof_connection', synthetic_proof)
    result = SimpleNamespace(session='2026-10-21', sessions_lag=0,
        shadow_verdict='SHADOW_GO', verification='VERIFIED',
        strategy_nav='100', strategy_cumulative_return='0.01')
    pub = SimpleNamespace(window_end=result.session, to_dict=lambda: {'version': 4})
    checkpoint = SimpleNamespace(session=result.session,
        publication=pub.to_dict(), snapshot={'snapshot': 'bound'})
    attestation = SimpleNamespace(timing={'observed_at': ATTESTED.isoformat()})
    closure = [checkpoint, None, result, attestation, None]
    validations = []
    @contextmanager
    def pinned(_conn):
        assert _conn is conn
        yield pub
    monkeypatch.setattr(runtime.inputs, 'require_schemas', lambda _conn: None)
    monkeypatch.setattr(runtime.initial, '_context', lambda *args: {})
    monkeypatch.setattr(runtime.inputs, 'pinned', pinned)
    monkeypatch.setattr(runtime.inputs, 'is_rolling', lambda _pub: True)
    monkeypatch.setattr(runtime, '_closure', lambda *a, **kw: tuple(closure))
    def validate(_conn, _pub, *, target, summary_only):
        validations.append((target, summary_only))
        return {'snapshot': 'bound'}, None, None
    monkeypatch.setattr(runtime.inputs, '_validate', validate)
    return SimpleNamespace(conn=conn, closure=closure, pub=pub,
                           checkpoint=checkpoint, result=result, validations=validations)


def read_history(history, error=None, now=NOW):
    return waiting.read(history.conn,
        error or refused(RollingSourceFrontierPending('sole frontier clause')),
        observation_id='primary', starting_cash='50000', now=now)


def test_only_the_direct_native_frontier_cause_can_enter_wait(history):
    assert read_history(history).session == '2026-10-21'
    assert history.validations == [('2026-10-21', True)]
    nested = ValueError('nested')
    nested.__cause__ = RollingSourceFrontierPending('sole frontier clause')
    for cause in (None, ValueError('RollingSourceFrontierPending: sole frontier clause'), nested):
        assert read_history(history, refused(cause)) is None


def test_removing_native_cause_guard_is_detected(history, monkeypatch):
    body = inspect.getsource(waiting.read)
    guard = 'if type(refusal.__cause__) is not RollingSourceFrontierPending:'
    assert guard in body
    namespace = {}
    exec(compile(body.replace(guard, 'if False:'), 'source-type-falsifier', 'exec'),
         waiting.__dict__, namespace)
    monkeypatch.setattr(waiting, 'read', namespace['read'])
    with pytest.raises(AssertionError):
        test_only_the_direct_native_frontier_cause_can_enter_wait(history)


@pytest.mark.parametrize('changed', ['publication', 'session', 'result', 'snapshot', 'authority', 'reconstruction', 'clock'])
def test_historical_identity_authority_and_clock_fail_closed(history, monkeypatch, changed):
    if changed == 'publication':
        history.checkpoint.publication = {'version': 5}
    elif changed == 'session':
        history.checkpoint.session = '2026-10-20'
    elif changed == 'result':
        history.result.session = '2026-10-20'
    elif changed == 'snapshot':
        history.checkpoint.snapshot = {'snapshot': 'changed'}
    elif changed == 'authority':
        history.closure[3] = None
    elif changed == 'reconstruction':
        history.closure[3] = runtime.authority.ReconstructionReceipt.model_construct()
    else:
        history.closure[3].timing['observed_at'] = (NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        read_history(history)


def test_extra_input_failure_cannot_become_historical_wait(history, monkeypatch):
    def invalid(*args, **kwargs):
        raise ValueError('immutable input closure changed')
    monkeypatch.setattr(runtime.inputs, '_validate', invalid)
    with pytest.raises(ValueError, match='immutable input closure'):
        read_history(history)


def source_projection(monkeypatch, history):
    from sentinel.feed import store
    monkeypatch.setattr(store, 'connect', lambda *a, **kw: history.conn)
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *args: None)
    def pending(*args, **kwargs):
        raise refused(RollingSourceFrontierPending('sole frontier clause'))
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', pending)
    book = model.ShadowBook(session='2026-10-21', cash=Decimal('50'), nav=Decimal('100'),
        receivables=Decimal('5'), pending_operations=0,
        holdings=[model.ShadowHolding(security_id='one', ticker='AAA',
            quantity=Decimal('1'), raw_close=Decimal('45'), value=Decimal('45'),
            weight=Decimal('.45'))])
    monkeypatch.setattr(sources, '_verified_shadow_book_rows', lambda *a, **kw: (
        [model.Row('exposure', 'Exposure', '1.00', model.OK),
         model.Row('book', 'Book', 'Canonical holdings', model.OK, shadow_book=book),
         model.Row('terminals', 'Terminals', 'None', model.OK)], []))
    return sources._dual_authority_rows('postgresql://fixture@isolated.invalid/fixture', now=NOW, include_paper=False)


def observation(output):
    rows = output[0]
    raw = [asdict(row) for row in rows]
    for value, row in zip(raw, rows):
        value['shadow_book'] = row.shadow_book.model_dump(mode='json') if row.shadow_book else None
    return {'rows': raw, 'errors': output[3], 'observed_at': NOW}


def test_cold_reader_composes_dated_wait_metrics_holdings_json_and_html(history, monkeypatch):
    output = source_projection(monkeypatch, history)
    value = reader.Reader(runner=lambda *a, **kw: observation(output),
        evidence_reader=lambda *a: 'unchanged', wall_clock=lambda: NOW)
    value.read('fixture', include_paper=False)
    complete(value)
    current = value.read('fixture', include_paper=False)
    actual, html = surfaces(monkeypatch, current, NOW)
    assert actual['operational'] == model.WARN and not actual['source_errors']
    rows = {row.key: row for row in current[0]}
    assert rows['shadow_verification'].value == 'WAITING FOR 2026-10-22 INPUTS'
    assert all(row.status == model.WARN for row in current[0])
    assert rows['shadow_nav'].as_of == rows['book'].as_of == ATTESTED
    assert rows['shadow_nav'].value == '$100.00'
    assert rows['book'].shadow_book.holdings[0].ticker == 'AAA'
    public_book = next(row for row in actual['rows'] if row['key'] == 'book')
    assert public_book['shadow_book']['session'] == '2026-10-21'
    assert public_book['shadow_book']['receivables'] == '5'
    assert 'LAST ATTESTED THROUGH 2026-10-21' in html
    assert 'CURRENT SESSION NOT VERIFIED' in html
    assert 'Dividend receivables (not cash)' in html
    assert 'SHADOW VERIFIED THROUGH 2026-10-22' not in html
    expired, expired_html = surfaces(monkeypatch, current, DEADLINE)
    assert expired['operational'] == model.FAIL
    assert not expired['rows'][0]['recovery']['active']
    assert next(row for row in expired['rows'] if row['key'] == 'book')['shadow_book'] is None
    assert 'data-detail-key="shadow-holdings"' not in expired_html


def test_refresh_never_advances_attestation_clock_or_owed_open(history, monkeypatch):
    first = read_history(history)
    second = read_history(history, now=DEADLINE+timedelta(days=4))
    assert first.attested_at == second.attested_at == ATTESTED
    assert first.deadline == second.deadline == DEADLINE
    assert first.decision_session == second.decision_session == '2026-10-22'
    row = model.shadow_verification_row(verdict=None, verification=None, session=None,
                                       source_wait=second, now=DEADLINE)
    assert row.status == model.FAIL
    assert row.effective_status(DEADLINE) == model.FAIL


def test_expired_source_wait_keeps_historical_clocks_and_current_paper_clock(history, monkeypatch):
    output = source_projection(monkeypatch, history)
    rows = [replace(row, status=model.FAIL) if row.key == 'shadow_verification' else row
            for row in output[0]]
    rows.append(replace(model.paper_reconciliation_row(state='CLEAN'), as_of=ATTESTED))
    answer = observation((rows, {}, [], []))
    answer['observed_at'] = DEADLINE
    value = reader.Reader(runner=lambda *a, **kw: answer,
        evidence_reader=lambda *a: 'unchanged', wall_clock=lambda: DEADLINE)
    value.read('fixture'); complete(value)
    observed = {row.key: row for row in value.read('fixture')[0]}
    assert observed['shadow_nav'].as_of == observed['book'].as_of == ATTESTED
    assert observed['paper_reconciliation'].as_of == DEADLINE
    assert observed['shadow_verification'].effective_status(DEADLINE) == model.FAIL


def test_current_producer_failure_remains_red_during_source_wait(history, monkeypatch):
    output = source_projection(monkeypatch, history)
    output[0].append(model.Row('shadow_worker', 'Shadow publisher', 'FAILED', model.FAIL))
    actual, _ = surfaces(monkeypatch, output, NOW)
    assert actual['operational'] == model.FAIL


def test_unknown_or_expired_current_identity_cannot_retain_book(history, monkeypatch):
    output = source_projection(monkeypatch, history)
    identity = ['old']
    value = reader.Reader(runner=lambda *a, **kw: observation(output),
        evidence_reader=lambda *a: identity[0], wall_clock=lambda: NOW)
    value.read('fixture', include_paper=False); complete(value)
    assert any(row.shadow_book for row in value.read('fixture', include_paper=False)[0])
    value.wall_clock = lambda: NOW+timedelta(seconds=reader.FRESH_SECONDS+1)
    expired = value.read('fixture', include_paper=False, allow_start=False)
    assert not any(row.shadow_book for row in expired[0])
    assert expired[0][1].as_of == ATTESTED
    assert expired[0][0].status == model.UNKNOWN
    value.wall_clock = lambda: NOW
    identity[0] = 'new'
    changed = value.read('fixture', include_paper=False, allow_start=False)
    assert not any(row.shadow_book for row in changed[0])
    assert changed[0][1].value == 'UNAVAILABLE'
    def unreadable(*args):
        raise ValueError('unreadable')
    value.evidence_reader = unreadable
    assert not any(row.shadow_book for row in value.read('fixture', include_paper=False)[0])


def test_generic_refusal_and_new_success_keep_normal_semantics(history, monkeypatch):
    source_projection(monkeypatch, history)
    def invalid(*args, **kwargs):
        raise refused(ValueError('RollingSourceFrontierPending: sole frontier clause'))
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', invalid)
    output = sources._dual_authority_rows('postgresql://fixture@isolated.invalid/fixture', now=NOW, include_paper=False)
    assert output[0][0].status == model.FAIL
    assert output[0][1].value == 'UNAVAILABLE'
    monkeypatch.setattr(shadow_runtime, 'verified_shadow_status', lambda *a, **kw: history.result)
    output = sources._dual_authority_rows('postgresql://fixture@isolated.invalid/fixture', now=NOW, include_paper=False)
    assert output[0][0].status == model.OK
    assert output[0][0].recovery is None
    assert 'LAST ATTESTED' not in output[0][1].detail


def test_other_amber_books_never_gain_a_holdings_payload(history, monkeypatch):
    output = source_projection(monkeypatch, history)
    book = next(row for row in output[0] if row.key == 'book')
    from sentinel.panel.render import _holdings_html
    assert _holdings_html(book, NOW)
    assert not _holdings_html(replace(book, recovery=None), NOW)
    assert not _holdings_html(replace(book, recovery=model.RecoveryEvidence(
        phase='OTHER_WAIT', automatic=True, deadline=DEADLINE)), NOW)


def test_real_retained_attestation_survives_close_wait_and_fails_tampering(
        conn, published, monkeypatch):
    from sentinel import rolling_authority
    from sentinel.feed import calendar, operational_snapshot
    from tests.sentinel.test_rolling_initialization import OBS
    result = runtime.advance(conn, through='2026-09-14',
                             observation_id=OBS, starting_cash=100_000)
    now = datetime(2026, 9, 15, 20, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(operational_snapshot, '_now', lambda: now)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda *a: '2026-09-15')
    with pytest.raises(shadow_runtime.ShadowRuntimeRefused) as caught:
        shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100_000)
    assert type(caught.value.__cause__) is RollingSourceFrontierPending
    wait = waiting.read(conn, caught.value, observation_id=OBS,
                        starting_cash=100_000, now=now)
    assert wait.result.record_sha256 == result.record_sha256
    assert wait.result.state.state_hash == result.state.state_hash
    assert wait.session == '2026-09-14' and wait.decision_session == '2026-09-15'
    assert wait.deadline == calendar.session_window('2026-09-16')[0]
    assert wait.attested_at == datetime.fromisoformat(rolling_authority.latest(conn, OBS)[0].timing['observed_at'])
    conn.rollback()
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state, '{hmac_sha256}', to_jsonb(%s::text)) WHERE cursor_name=%s",
                 ('0'*64, rolling_authority.name(OBS, wait.session)))
    conn.commit()
    with pytest.raises(Exception, match='AUTHENTICATION_FAILED'):
        waiting.read(conn, caught.value, observation_id=OBS,
                     starting_cash=100_000, now=now)


from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: E402,F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: E402,F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: E402,F401
