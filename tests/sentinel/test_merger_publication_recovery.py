"""A corrected merger source keeps its original publication and clock."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinel import rolling_reconstruction_evidence as dated
from sentinel.feed import operational_snapshot as snapshots, rolling_jobs
from sentinel.feed.rolling_contract import PriceWindow, digest


SESSION = '2026-11-23'
BEFORE_OPEN = datetime(2026, 11, 23, 21, 12, tzinfo=timezone.utc)
AFTER_OPEN = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)


def test_unchanged_merger_source_allows_only_cursor_bound_state_recovery(monkeypatch):
    from sentinel.feed import calendar

    old = {'old_security_id': 'old-a', 'record_id': 'record-a',
           'effective_session': SESSION, 'terms_sha256': 'a' * 64}
    prior = [old]
    evidence = {
        'old-source': {'schema': snapshots._MERGER_ALPACA_POLICY[0],
                       'merger_conversions_sha256': digest(prior)},
        'old-reference': {'schema': snapshots._MERGER_ALPACA_POLICY[1],
                          'merger_conversions': prior},
        'new-source': {'schema': snapshots._MERGER_ALPACA_POLICY[0],
                       'merger_conversions_sha256': digest(prior)},
        'new-reference': {'schema': snapshots._MERGER_ALPACA_POLICY[1],
                          'merger_conversions': list(prior)},
    }
    old_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='old-source', reference_sha256='old-reference',
        normalization_version=snapshots._MERGER_ALPACA_POLICY[2], snapshot_id='old-snapshot')
    new_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='new-source', reference_sha256='new-reference',
        normalization_version=snapshots._MERGER_ALPACA_POLICY[2], snapshot_id='new-snapshot')
    previous = SimpleNamespace(version=27, window_end=SESSION,
                               to_dict=lambda: {'version': 27, 'window_end': SESSION})
    old_request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=26, strategy_sha256=digest('old strategy'),
        dependencies_sha256=digest('old dependencies'))
    cursor = calendar.previous_sessions(SESSION, 2)[0]
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        cursor=cursor, expected_publication_version=27,
        strategy_sha256=digest('new strategy'),
        dependencies_sha256=digest('new dependencies'))
    monkeypatch.setattr(snapshots, '_bound_and_manifest',
                        lambda conn, pub: ({'job_id': 'old-job'}, old_manifest))
    monkeypatch.setattr(snapshots.rolling_store, 'manifest', lambda conn, candidate: new_manifest)
    monkeypatch.setattr(snapshots.rolling_store, 'load_evidence',
                        lambda conn, sha: evidence[sha])
    monkeypatch.setattr(snapshots.jobs, 'status',
                        lambda conn, job: {'request': old_request.model_dump(mode='json')})

    edge = snapshots._edge_fields(None, previous, 'new-candidate', request)
    assert edge['schema'] == snapshots.RECOVERY_SUPERSESSION_SCHEMA
    assert edge['superseded_version'] == previous.version
    assert edge['superseded_source_sha256'] == 'old-source'
    assert edge['successor_source_sha256'] == 'new-source'
    assert edge['successor_strategy_sha256'] == request.strategy_sha256

    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_EXTENSION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate',
                               request.model_copy(update={'cursor': None}))
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='RECOVERY_CURSOR_CHANGED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request.model_copy(
            update={'cursor': calendar.previous_sessions(SESSION, 3)[0]}))
    changed = {**old, 'terms_sha256': 'b' * 64}
    evidence['new-reference']['merger_conversions'] = [changed]
    evidence['new-source']['merger_conversions_sha256'] = digest([changed])
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_EXTENSION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        return _Rows(self.rows)


def _row(version, at, *, edge=False):
    return (version, version - 1 if version > 27 else 26, None,
            '2025-09-11', SESSION,
            {'operational_supersession': {'schema': snapshots.SUPERSESSION_SCHEMA}} if edge else {}, at)


@pytest.mark.parametrize('rows,corrected,selected', [
    ([_row(27, BEFORE_OPEN)], False, 27),
    ([_row(27, BEFORE_OPEN), _row(28, BEFORE_OPEN, edge=True)], True, 28),
])
def test_dated_selection_uses_unique_authenticated_tip(monkeypatch, rows, corrected, selected):
    from sentinel.feed import publication

    predecessor = publication.Publication(*rows[0][:6])
    monkeypatch.setattr(snapshots, 'require_supersession',
                        lambda conn, pub: predecessor if corrected and pub.version == 28 else None)
    monkeypatch.setattr(dated, 'require_dated', lambda conn, pub: {'version': pub.version})
    pub, binding = dated.select(_Connection(rows), session=SESSION, previous_version=26)
    assert pub.version == selected and binding == {'version': selected}


def test_dated_selection_authenticates_serial_merger_corrections(monkeypatch):
    from sentinel.feed import publication

    rows = [_row(27, BEFORE_OPEN), _row(28, BEFORE_OPEN, edge=True),
            _row(29, BEFORE_OPEN, edge=True)]
    publications = {row[0]: publication.Publication(*row[:6]) for row in rows}
    monkeypatch.setattr(snapshots, 'require_supersession',
                        lambda conn, pub: publications.get(pub.version - 1)
                        if pub.version > 27 and pub.evidence.get('operational_supersession')
                        else None)
    monkeypatch.setattr(dated, 'require_dated', lambda conn, pub: {'version': pub.version})
    pub, binding = dated.select(_Connection(rows), session=SESSION, previous_version=26)
    assert pub.version == 29 and binding == {'version': 29}

    rows[-1] = _row(29, AFTER_OPEN, edge=True)
    with pytest.raises(dated.InputsUnavailable, match='MISSING_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)

    rows[-1] = _row(29, BEFORE_OPEN)
    with pytest.raises(dated.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)

    rows[-1] = _row(29, BEFORE_OPEN.replace(hour=20), edge=True)
    with pytest.raises(dated.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)


def test_dated_selection_refuses_changed_predecessor_or_unbounded_chain(monkeypatch):
    from sentinel.feed import publication

    rows = [_row(version, BEFORE_OPEN, edge=version > 27)
            for version in range(27, 30)]
    publications = {row[0]: publication.Publication(*row[:6]) for row in rows}
    monkeypatch.setattr(snapshots, 'require_supersession',
                        lambda conn, pub: publications[27] if pub.version == 29
                        else publications.get(pub.version - 1) if pub.version > 27 else None)
    with pytest.raises(dated.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)

    rows = [_row(version, BEFORE_OPEN, edge=version > 27)
            for version in range(27, 36)]
    with pytest.raises(dated.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)


@pytest.mark.parametrize('old_strategy_filtered', [False, True])
def test_late_correction_never_backdates_dated_recovery(monkeypatch, old_strategy_filtered):
    from sentinel.feed import publication

    older = _row(27, BEFORE_OPEN)
    rows = ([older, _row(28, AFTER_OPEN, edge=True)] if not old_strategy_filtered
            else [_row(28, AFTER_OPEN, edge=True)])
    predecessor = publication.Publication(*older[:6])
    monkeypatch.setattr(snapshots, 'require_supersession',
                        lambda conn, pub: predecessor if pub.version == 28 else None)
    monkeypatch.setattr(dated, 'require_dated',
                        lambda conn, pub: pytest.fail('late correction became dated authority'))
    with pytest.raises(dated.InputsUnavailable, match='MISSING_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)


def test_unrelated_same_session_publications_stay_ambiguous(monkeypatch):
    rows = [_row(27, BEFORE_OPEN), _row(28, BEFORE_OPEN)]
    monkeypatch.setattr(snapshots, 'require_supersession', lambda conn, pub: None)
    with pytest.raises(dated.InputsUnavailable, match='AMBIGUOUS_DATED_PUBLICATION'):
        dated.select(_Connection(rows), session=SESSION, previous_version=26)


def test_same_session_correction_requires_unconsumed_checkpoint(monkeypatch):
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint

    class Database:
        def execute(self, sql):
            assert sql == "SELECT to_regclass('sentinel_processed_sessions')"
            return _Rows([('sentinel_processed_sessions',)])

    conn = Database()
    monkeypatch.setattr(rolling_checkpoint, 'read', lambda conn: None)
    for checkpoint_session, expected in [('2026-11-20', False), (SESSION, True), ('2026-11-24', True)]:
        monkeypatch.setattr(rolling_daily_checkpoint, 'read',
                            lambda conn, value=checkpoint_session: SimpleNamespace(session=value))
        assert snapshots._session_consumed(conn, SESSION) is expected


def test_current_tip_rechecks_every_prior_correction_edge(monkeypatch):
    from sentinel.feed import publication

    rows = {version: _row(version, BEFORE_OPEN, edge=version > 27)
            for version in range(27, 30)}
    for version in (28, 29):
        rows[version][5]['operational_supersession'].update(
            **{'from': version - 1, 'superseded_version': version - 1})

    class Database:
        def execute(self, sql, params):
            if 'SELECT published_at' in sql:
                return _Rows([(rows[params[0]][6],)])
            return _Rows([rows[params[0]][:6]])

    request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=28, strategy_sha256=digest('selected'),
        dependencies_sha256=digest('dependencies'))
    monkeypatch.setattr(publication, '_validate_publication',
                        lambda conn, pub, allow_snapshot: pub)
    monkeypatch.setattr(snapshots, '_bound',
                        lambda conn, pub: {'candidate_id': 'candidate', 'job_id': 'job'})
    monkeypatch.setattr(snapshots.jobs, 'status',
                        lambda conn, job: {'request': request.model_dump(mode='json')})
    monkeypatch.setattr(snapshots, '_edge_fields',
                        lambda conn, previous, candidate, request: {
                            'schema': snapshots.SUPERSESSION_SCHEMA, 'from': previous.version,
                            'superseded_version': previous.version})
    tip = publication.Publication(*rows[29][:6])
    assert snapshots.require_supersession(Database(), tip).version == 28

    # The tip's own edge stays valid; a changed ancestor must still refuse.
    rows[28][5]['operational_supersession']['from'] = 26
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='OPERATIONAL_SUPERSESSION_CHANGED'):
        snapshots.require_supersession(Database(), tip)

    rows[28][5]['operational_supersession']['from'] = 27
    for version in range(30, 38):
        rows[version] = _row(version, BEFORE_OPEN, edge=True)
        rows[version][5]['operational_supersession'].update(
            **{'from': version - 1, 'superseded_version': version - 1})
    tip = publication.Publication(*rows[37][:6])
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='OPERATIONAL_SUPERSESSION_CHAIN_LIMIT'):
        snapshots.require_supersession(Database(), tip)


def test_correction_strategy_binds_retained_and_selected_identities(monkeypatch):
    from sentinel import economic_migration, rolling_checkpoint, rolling_daily_checkpoint, strategy

    old = {'strategy': 'fixture', 'cash_distribution_policy': economic_migration.POLICY,
           'data_semantics_source_sha256': 'a' * 64}
    selected = {**old, 'data_semantics_source_sha256': 'b' * 64}
    new_request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=27, strategy_sha256=digest(selected),
        dependencies_sha256=digest('new'))
    previous = SimpleNamespace(version=27, window_end=SESSION)
    monkeypatch.setattr(strategy, 'production_strategy', lambda: (None, selected))
    monkeypatch.setattr(rolling_daily_checkpoint, 'read',
                        lambda conn: SimpleNamespace(session='2026-11-20', strategy_identity=old))
    monkeypatch.setattr(rolling_checkpoint, 'read', lambda conn: None)
    snapshots._require_correction_strategy(None, previous, new_request)
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='SELECTED_STRATEGY_CHANGED'):
        snapshots._require_correction_strategy(None, previous,
            new_request.model_copy(update={'strategy_sha256': digest('foreign')}))
    monkeypatch.setattr(rolling_daily_checkpoint, 'read',
                        lambda conn: SimpleNamespace(session=SESSION, strategy_identity=old))
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='COMPATIBILITY_UNPROVEN'):
        snapshots._require_correction_strategy(None, previous, new_request)
    monkeypatch.setattr(rolling_daily_checkpoint, 'read',
                        lambda conn: SimpleNamespace(session='2026-11-20',
                                                     strategy_identity={**old, 'strategy': 'foreign'}))
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='COMPATIBILITY_UNPROVEN'):
        snapshots._require_correction_strategy(None, previous, new_request)


def test_edge_binds_exact_old_and_new_source_evidence(monkeypatch):
    conversions = [{'old_security_id': 'old-uuid', 'successor_security_id': 'new-uuid',
                    'effective_session': SESSION}]
    old_source = {'schema': snapshots._OLD_ALPACA_POLICY[0]}
    old_reference = {'schema': snapshots._OLD_ALPACA_POLICY[1]}
    new_source = {'schema': snapshots._MERGER_ALPACA_POLICY[0],
                  'merger_conversions_sha256': digest(conversions)}
    new_reference = {'schema': snapshots._MERGER_ALPACA_POLICY[1],
                     'merger_conversions': conversions}
    evidence = {'old-source': old_source, 'old-reference': old_reference,
                'new-source': new_source, 'new-reference': new_reference}
    old_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='old-source', reference_sha256='old-reference',
        normalization_version=snapshots._OLD_ALPACA_POLICY[2], snapshot_id='old-snapshot')
    new_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='new-source', reference_sha256='new-reference',
        normalization_version=snapshots._MERGER_ALPACA_POLICY[2], snapshot_id='new-snapshot')
    previous = SimpleNamespace(version=27, window_end=SESSION,
                               to_dict=lambda: {'version': 27, 'window_end': SESSION})
    old_request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=26, strategy_sha256=digest('old strategy'),
        dependencies_sha256=digest('old-dependencies'))
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=27, strategy_sha256=digest('new strategy'),
        dependencies_sha256=digest('new-dependencies'))
    monkeypatch.setattr(snapshots, '_bound_and_manifest',
                        lambda conn, pub: ({'job_id': 'old-job'}, old_manifest))
    monkeypatch.setattr(snapshots.rolling_store, 'manifest', lambda conn, candidate: new_manifest)
    monkeypatch.setattr(snapshots.rolling_store, 'load_evidence',
                        lambda conn, sha: evidence[sha])
    monkeypatch.setattr(snapshots.jobs, 'status',
                        lambda conn, job: {'request': old_request.model_dump(mode='json')})
    edge = snapshots._edge_fields(None, previous, 'new-candidate', request)
    assert edge['superseded_version'] == 27
    assert edge['superseded_snapshot_id'] == 'old-snapshot'
    assert edge['successor_snapshot_id'] == 'new-snapshot'
    assert edge['superseded_strategy_sha256'] == digest('old strategy')
    assert edge['successor_strategy_sha256'] == digest('new strategy')
    assert edge['successor_source_sha256'] == 'new-source'

    new_manifest.normalization_version = snapshots._OLD_ALPACA_POLICY[2]
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='SUPERSESSION_POLICY_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)
    new_manifest.normalization_version = snapshots._MERGER_ALPACA_POLICY[2]
    new_reference['merger_conversions'] = []
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_CORRECTION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)


def test_same_policy_merger_correction_requires_strict_source_extension(monkeypatch):
    old = {'old_security_id': 'old-a', 'record_id': 'record-a',
           'effective_session': SESSION, 'terms_sha256': 'a' * 64}
    added = {'old_security_id': 'old-b', 'record_id': 'record-b',
             'effective_session': SESSION, 'terms_sha256': 'b' * 64}
    prior = [old]
    current = [old, added]
    old_source = {'schema': snapshots._MERGER_ALPACA_POLICY[0],
                  'merger_conversions_sha256': digest(prior)}
    new_source = {'schema': snapshots._MERGER_ALPACA_POLICY[0],
                  'merger_conversions_sha256': digest(current)}
    evidence = {'old-source': old_source, 'old-reference': {
                    'schema': snapshots._MERGER_ALPACA_POLICY[1],
                    'merger_conversions': prior},
                'new-source': new_source, 'new-reference': {
                    'schema': snapshots._MERGER_ALPACA_POLICY[1],
                    'merger_conversions': current}}
    old_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='old-source', reference_sha256='old-reference',
        normalization_version=snapshots._MERGER_ALPACA_POLICY[2],
        snapshot_id='old-snapshot')
    new_manifest = SimpleNamespace(provider='ALPACA_OPENFIGI',
        source_evidence_sha256='new-source', reference_sha256='new-reference',
        normalization_version=snapshots._MERGER_ALPACA_POLICY[2],
        snapshot_id='new-snapshot')
    previous = SimpleNamespace(version=27, window_end=SESSION,
                               to_dict=lambda: {'version': 27, 'window_end': SESSION})
    request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=27, strategy_sha256=digest('new strategy'),
        dependencies_sha256=digest('new-dependencies'))
    old_request = rolling_jobs.PreparationRequest(window=PriceWindow.through(SESSION),
        expected_publication_version=26, strategy_sha256=digest('old strategy'),
        dependencies_sha256=digest('old-dependencies'))
    monkeypatch.setattr(snapshots, '_bound_and_manifest',
                        lambda conn, pub: ({'job_id': 'old-job'}, old_manifest))
    monkeypatch.setattr(snapshots.rolling_store, 'manifest', lambda conn, candidate: new_manifest)
    monkeypatch.setattr(snapshots.rolling_store, 'load_evidence',
                        lambda conn, sha: evidence[sha])
    monkeypatch.setattr(snapshots.jobs, 'status',
                        lambda conn, job: {'request': old_request.model_dump(mode='json')})

    edge = snapshots._edge_fields(None, previous, 'new-candidate', request)
    assert edge['superseded_source_schema'] == snapshots._MERGER_ALPACA_POLICY[0]
    assert edge['successor_source_schema'] == snapshots._MERGER_ALPACA_POLICY[0]
    assert edge['superseded_snapshot_id'] == 'old-snapshot'
    assert edge['successor_snapshot_id'] == 'new-snapshot'

    # Each mutation is a falsifier: omitting or weakening the extension guard
    # makes an identical or changed old conversion publish as a correction.
    evidence['new-reference']['merger_conversions'] = prior
    new_source['merger_conversions_sha256'] = digest(prior)
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_EXTENSION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)
    changed = {**old, 'terms_sha256': 'c' * 64}
    evidence['new-reference']['merger_conversions'] = [changed, added]
    new_source['merger_conversions_sha256'] = digest([changed, added])
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_EXTENSION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)
    duplicate = [old, old]
    evidence['new-reference']['merger_conversions'] = duplicate
    new_source['merger_conversions_sha256'] = digest(duplicate)
    with pytest.raises(snapshots.OperationalSnapshotRefused, match='MERGER_EXTENSION_REQUIRED'):
        snapshots._edge_fields(None, previous, 'new-candidate', request)
