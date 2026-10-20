"""Full-hash facts remain pin-bound and preserve every dated reference check."""
from dataclasses import asdict, fields, replace
from datetime import date
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import paper
from sentinel.core import rolling_inputs as adapter
from sentinel.execution import feed_inputs
from sentinel.feed import calendar, publication, readiness_scope, rolling_store
from sentinel.feed.rolling_contract import FormationWindow, CurrentFormationWindow
from tests.sentinel import test_rolling_inputs as fixture_inputs
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


@pytest.fixture(autouse=True)
def declared_nonfinancial_source_fixture(source, monkeypatch, tmp_path):
    # This is an explicit synthetic source/SQL unit fixture, not installed
    # media or software authority. Unlike legacy module opt-ins, declare the
    # external prerequisites here; retain all real row/hash/pin/schema
    # and reference validators. Exact candidate gateway qualification is separate.
    from sentinel import backup_runtime_authority, identity
    from sentinel.feed import coherence
    # The imported source fixture uses a one-row calibration. This module's
    # published fixture supplies 25 names; every other coherence clause is real.
    monkeypatch.setattr(coherence, 'MIN_SEED_SESSION_ROWS', 25)
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path / 'no-deployed-media')
    monkeypatch.setenv(publication.RECEIPT_KEY_ENV, 'fusion-unit-receipt-key-' * 4)
    monkeypatch.setattr(identity, 'require_feed_producer_identity', lambda: {
        'schema': 'sentinel.feed-producer/1', 'git_commit': 'a' * 40,
        'runtime_image_digest': 'sha256:' + 'b' * 64, 'image_source_revision': 'a' * 40})


def raw_context(conn, key):
    completed = rolling_store._verify_content_uncached(conn, key[0])
    assert completed.readiness is None  # Unscoped full scans collect no reusable facts.
    accumulator = rolling_store._ReadinessAccumulator(completed.manifest)
    for row in rolling_store.read_bars(conn, key[0]):
        accumulator.observe(row)
    facts = accumulator.finish(key[0], completed.manifest, tuple(rolling_store.read_benchmarks(conn, key[0])))
    refs = adapter.SnapshotReferences(conn, candidate_id=key[0], snapshot_id=key[1])
    session = str(refs.manifest.window.end)
    axis = calendar.previous_sessions(session, 300 if refs.current_window else 253)
    meta, _ = refs.current_metadata()
    return facts, refs, session, axis, axis[:-1], meta


def projected(context):
    return adapter._readiness_from_facts(*context)


def old_summary(conn, context):
    _, refs, session, axis, warm, meta = context
    result = adapter.ReadinessInputs(session, warm, adapter._benchmarks(conn, refs.candidate_id, session),
                                     any(row.related_tickers for row in meta.values()))
    for bar in adapter._mapped_bars(conn, refs.candidate_id, refs, meta, warm[0]):
        result.observe(bar)
    assert sorted(result.counts) == axis
    return result


def test_actual_resolver_first_path_supplies_completed_facts_without_second_stream(
        conn, published, monkeypatch):
    events = []
    read = rolling_store.read_bars
    references = adapter.SnapshotReferences

    def observed(*args, **kwargs):
        events.append('bars-start')
        yield from read(*args, **kwargs)
        events.append('bars-complete')

    def refs(*args, **kwargs):
        events.append('references')
        return references(*args, **kwargs)

    monkeypatch.setattr(rolling_store, 'read_bars', observed)
    monkeypatch.setattr(adapter, 'SnapshotReferences', refs)
    with feed_inputs.pinned(conn, commit=False) as pub:
        paper.build_security_resolver(conn, calendar.next_session(pub.window_end))
        assert events[:3] == ['bars-start', 'bars-complete', 'references']
        monkeypatch.setattr(adapter, '_mapped_bars', lambda *a: pytest.fail('second mapped stream'))
        result = adapter.readiness_inputs(
            conn, candidate_id=published['candidate_id'], snapshot_id=published['snapshot_id'])
        assert result.counts[result.session] > 0
        assert events.count('bars-start') == events.count('bars-complete') == 1
        record, = readiness_scope._current.get().verified_snapshots.values()
        assert isinstance(record, rolling_store.VerifiedSnapshot)
        assert record.readiness is not None
        assert set(field.name for field in fields(record.readiness)) == {
            'candidate_id', 'snapshot_id', 'sessions', 'counts', 'positive',
            'benchmarks', 'reference_uses'}
        facts = rolling_store.readiness_facts(conn, published['candidate_id'])
        facts.reference_uses.clear()
        assert rolling_store.readiness_facts(conn, published['candidate_id']).reference_uses
    assert rolling_store.readiness_facts(conn, published['candidate_id']) is None


@pytest.mark.parametrize('window,current', [(None, False), (None, True),
                                           (FormationWindow, False), (CurrentFormationWindow, True)])
def test_raw_domain_counts_match_independent_sql_and_original_adapter(conn, monkeypatch, window, current):
    if window is not None:
        monkeypatch.setattr(fixture_inputs, 'PriceWindow', window)
    if current:
        from sentinel.core import window_policy
        monkeypatch.setattr(fixture_inputs, 'NORMALIZATION_VERSION', window_policy.NORMALIZATION)

    def sparse(bars, axis):
        return [bar.model_copy(update=(
            {'open_unadjusted': None, 'close_signal': None}
            if bar.security_id == '1' and bar.session < axis.end else
            {'volume': 0} if bar.security_id == '2' and bar.session == axis.end else {}))
            for bar in bars]

    key = fixture_inputs.candidate(conn, bar_change=sparse,
        reference_change=lambda value: value['tickers'][0].update(relatedtickers='S01 S02'),
        proof_change=lambda value: value.update(action_quarantine=[{'security_id': '1'}]))
    context = raw_context(conn, key)
    result = projected(context)
    rows = conn.execute(
        'SELECT session,count(*),count(*) FILTER (WHERE close_signal>0),'
        'count(*) FILTER (WHERE close_unadjusted>0),count(*) FILTER (WHERE open_unadjusted>0),'
        'count(*) FILTER (WHERE volume>0) FROM sentinel_snapshot_bars WHERE candidate_id=%s'
        ' AND session>=%s GROUP BY session ORDER BY session', (key[0], result.warmup_sessions[0])).fetchall()
    assert len(rows) == (300 if current else 253)
    assert result.counts == {str(row[0]): row[1] for row in rows}
    for index, name in enumerate(adapter.READINESS_DOMAINS, 2):
        assert result.frontier_positive[name] == rows[-1][index]
        assert result.warmup_positive[name] == sum(row[index] for row in rows[:-1])
    assert asdict(result) == asdict(old_summary(conn, context))
    assert result.frontier_positive['volume'] == 24 and result.related_issuers


def test_valid_full_hash_does_not_hide_wrong_middle_date_identity(conn):
    def wrong_middle(bars, axis):
        return [bar.model_copy(update={'ticker': 'S02'})
                if bar.security_id == '1' and bar.session == axis.sessions[-100] else bar for bar in bars]
    key = fixture_inputs.candidate(conn, bar_change=wrong_middle)
    context = raw_context(conn, key)
    # Both endpoint rows are valid; a first/last interval check is insufficient.
    with pytest.raises(adapter.RollingInputsRefused, match='BAR_REFERENCE_MISMATCH'):
        projected(context)


def test_absent_middle_row_is_not_invented_by_reference_mask(conn):
    omitted = []
    def absent(bars, axis):
        omitted.append(str(axis.sessions[-100]))
        return [bar for bar in bars if not (
            bar.security_id == '1' and str(bar.session) == omitted[0])]
    key = fixture_inputs.candidate(conn, bar_change=absent)
    context = raw_context(conn, key)
    facts, refs, *_ = context
    actual = refs.resolver
    calls = []
    def resolve(ticker, day):
        calls.append((ticker, day))
        return None if ticker == 'S01' and day == omitted[0] else actual.resolve(ticker, day)
    refs.resolver = SimpleNamespace(resolve=resolve)
    assert projected(context).counts[omitted[0]] == 24
    assert ('S01', omitted[0]) not in calls
    assert not (facts.reference_uses[('1', 'S01')] & (1 << facts.sessions.index(
        date.fromisoformat(omitted[0]))))


def test_foreign_summary_identity_refuses(conn):
    context = raw_context(conn, fixture_inputs.candidate(conn))
    wrong = (replace(context[0], candidate_id='another-candidate'), *context[1:])
    with pytest.raises(adapter.RollingInputsRefused, match='READINESS_IDENTITY_MISMATCH'):
        projected(wrong)


def test_unscoped_verification_does_not_allocate_summary(conn, monkeypatch):
    key = fixture_inputs.candidate(conn)
    monkeypatch.setattr(rolling_store, '_ReadinessAccumulator',
                        lambda *a: pytest.fail('unscoped summary allocation'))
    assert rolling_store.verify_content(conn, key[0]).snapshot_id == key[1]
    assert rolling_store._verify_content_uncached(conn, key[0]).readiness is None
    assert rolling_store.readiness_facts(conn, key[0]) is None
    assert adapter.readiness_inputs(conn, candidate_id=key[0], snapshot_id=key[1]).counts


def test_removed_live_pin_guard_is_detected(conn, monkeypatch):
    function = rolling_store._verify_content_uncached
    source = textwrap.dedent(inspect.getsource(function))
    marker = ("readiness = (_ReadinessAccumulator(value) if isinstance(binding, dict)\n"
              "                 and binding.get('candidate_id') == candidate_id\n"
              "                 and binding.get('snapshot_id') == value.snapshot_id else None)")
    assert marker in source
    namespace = {}
    exec(compile(source.replace(marker, 'readiness = _ReadinessAccumulator(value)'),
                 'fusion-live-pin-falsifier', 'exec'), rolling_store.__dict__, namespace)
    monkeypatch.setattr(rolling_store, function.__name__, namespace[function.__name__])
    with pytest.raises(pytest.fail.Exception, match='unscoped summary allocation'):
        test_unscoped_verification_does_not_allocate_summary(conn, monkeypatch)


@pytest.mark.parametrize('closure', ['terminals', 'distributions'])
def test_fused_reader_keeps_action_closures(conn, published, monkeypatch, closure):
    def refused(*args, **kwargs):
        raise adapter.RollingInputsRefused('expected ' + closure + ' refusal')
    monkeypatch.setattr(adapter.SnapshotReferences, closure, refused)
    with feed_inputs.pinned(conn, commit=False):
        with pytest.raises(adapter.RollingInputsRefused, match='expected ' + closure):
            adapter.readiness_inputs(conn, candidate_id=published['candidate_id'],
                                      snapshot_id=published['snapshot_id'])


def test_pair_bound_discards_optimization_and_keeps_original_reader(conn, published, monkeypatch):
    monkeypatch.setattr(rolling_store, 'READINESS_PAIR_LIMIT', 1)
    calls = []
    mapped = adapter._mapped_bars
    def original(*args, **kwargs):
        calls.append(True)
        yield from mapped(*args, **kwargs)
    monkeypatch.setattr(adapter, '_mapped_bars', original)
    with feed_inputs.pinned(conn, commit=False):
        result = adapter.readiness_inputs(conn, candidate_id=published['candidate_id'],
                                           snapshot_id=published['snapshot_id'])
        record, = readiness_scope._current.get().verified_snapshots.values()
        assert record.readiness is None
        assert rolling_store.verify_content(conn, published['candidate_id']) == record.manifest
        assert rolling_store.readiness_facts(conn, published['candidate_id']) is None
        assert result.counts[result.session] > 0 and calls == [True]


@pytest.mark.parametrize('failure', ['last-bar', 'last-benchmark'])
def test_interrupted_full_stream_installs_no_facts(conn, published, monkeypatch, failure):
    name = 'read_bars' if failure == 'last-bar' else 'read_benchmarks'
    original = getattr(rolling_store, name)
    def interrupted(*args, **kwargs):
        yield from original(*args, **kwargs)
        raise TimeoutError('interrupted after final row')
    with feed_inputs.pinned(conn, commit=False):
        monkeypatch.setattr(rolling_store, name, interrupted)
        with pytest.raises(TimeoutError):
            rolling_store.verify_content(conn, published['candidate_id'])
        assert not readiness_scope._current.get().verified_snapshots
        assert rolling_store.readiness_facts(conn, published['candidate_id']) is None
        monkeypatch.setattr(rolling_store, name, original)
        rolling_store.verify_content(conn, published['candidate_id'])
        assert rolling_store.readiness_facts(conn, published['candidate_id']) is not None


def test_bare_manifest_is_not_a_completed_summary(conn, published, monkeypatch):
    bare = rolling_store.manifest(conn, published['candidate_id'])
    monkeypatch.setattr(rolling_store, '_verify_content_uncached', lambda *a: bare)
    with feed_inputs.pinned(conn, commit=False):
        with pytest.raises(publication.CorpusIncoherent, match='RESULT_CHANGED'):
            rolling_store.verify_content(conn, published['candidate_id'])
        assert not readiness_scope._current.get().verified_snapshots


def test_last_row_corruption_still_fails_full_hash(conn, published):
    cid = published['candidate_id']
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('UPDATE sentinel_snapshot_bars SET close_unadjusted=close_unadjusted+1'
                 ' WHERE (candidate_id,session,security_id)=(SELECT candidate_id,session,security_id'
                 ' FROM sentinel_snapshot_bars WHERE candidate_id=%s ORDER BY session DESC,security_id DESC LIMIT 1)',
                 (cid,))
    conn.commit()
    with feed_inputs.pinned(conn, commit=False):
        with pytest.raises(rolling_store.SnapshotStorageRefused, match='manifest'):
            rolling_store.verify_content(conn, cid)
        assert not readiness_scope._current.get().verified_snapshots


@pytest.mark.parametrize('guard', ['identity', 'dates', 'bound', 'hash'])
def test_removed_fusion_guard_is_detected(conn, published, monkeypatch, guard):
    if guard in {'identity', 'dates'}:
        function = adapter._readiness_from_facts
        source = textwrap.dedent(inspect.getsource(function))
        marker = ('raise RollingInputsRefused("SNAPSHOT_READINESS_IDENTITY_MISMATCH")'
                  if guard == 'identity' else 'remaining = dates & selected')
        replacement = 'pass' if guard == 'identity' else 'remaining = 0'
        assert marker in source
        source = source.replace(marker, replacement)
        namespace = {}
        exec(compile(source, 'fusion-guard-falsifier', 'exec'), adapter.__dict__, namespace)
        monkeypatch.setattr(adapter, function.__name__, namespace[function.__name__])
        check = (lambda: test_foreign_summary_identity_refuses(conn)) if guard == 'identity' else (
            lambda: test_valid_full_hash_does_not_hide_wrong_middle_date_identity(conn))
    elif guard == 'bound':
        function = rolling_store._ReadinessAccumulator.observe
        source = textwrap.dedent(inspect.getsource(function))
        marker = 'if key not in self.reference_uses and len(self.reference_uses) >= READINESS_PAIR_LIMIT:'
        assert marker in source
        namespace = {}
        exec(compile(source.replace(marker, 'if False:'), 'fusion-bound-falsifier', 'exec'),
             rolling_store.__dict__, namespace)
        monkeypatch.setattr(rolling_store._ReadinessAccumulator, 'observe', namespace['observe'])
        check = lambda: test_pair_bound_discards_optimization_and_keeps_original_reader(conn, published, monkeypatch)
    else:
        function = rolling_store._verify_content_uncached
        source = textwrap.dedent(inspect.getsource(function))
        marker = 'or bars_hash.hexdigest() != value.bars_sha256'
        assert marker in source
        namespace = {}
        exec(compile(source.replace(marker, 'or False'), 'fusion-hash-falsifier', 'exec'),
             rolling_store.__dict__, namespace)
        monkeypatch.setattr(rolling_store, function.__name__, namespace[function.__name__])
        check = lambda: test_last_row_corruption_still_fails_full_hash(conn, published)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        check()
