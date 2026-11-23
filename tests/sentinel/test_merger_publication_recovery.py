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
