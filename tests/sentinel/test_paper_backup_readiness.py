"""Delivery readiness consumes genuine newer proofs without retiming a prefix."""
import ast
import copy
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from tools import paper_backup_readiness as readiness


NOW = datetime(2031, 4, 21, 22, tzinfo=timezone.utc)
EPOCH = int(NOW.timestamp())
EXPECTED = dict(expected_commit='a' * 40,
                expected_image_digest='sha256:' + 'b' * 64,
                expected_account='PAFIXTURE', expected_engine='fixture-engine')


def chain(end):
    return dict(enabled=True, system_identifier='12345',
                base_backup='base-20310421T000000Z',
                recoverable_from_wal='000000010000000000000001',
                recovery_marker_wal='000000010000000000000002',
                recoverable_through_wal=f'0000000100000000{end:08X}',
                wal_segments=end, timeline_history=None,
                wal_integrity='sha256-sidecar-v1', integrity_full_scrub=True,
                integrity_objects_hashed=end, integrity_read_passes=1)


@pytest.fixture
def observation():
    context = dict(system_identifier='12345', postmaster_start_us=123,
                   deployment_id='fixture', broker='alpaca',
                   broker_account_id=EXPECTED['expected_account'], takeover_epoch=1,
                   git_commit=EXPECTED['expected_commit'],
                   runtime_image_digest=EXPECTED['expected_image_digest'])
    journal = NOW - timedelta(seconds=60)
    return dict(observed_at=NOW.isoformat(),
                primary=dict(system_identifier='12345', postmaster_start_us=123,
                             now=EPOCH, archive_mode='on', last_archive_at=EPOCH - 30,
                             last_archived_wal=chain(4)['recoverable_through_wal']),
                current_context=context, capacity_valid=True,
                capacity_engine=EXPECTED['expected_engine'],
                checkpoint_authenticated=True,
                checkpoint=dict(context=copy.deepcopy(context),
                                engine_id=EXPECTED['expected_engine'],
                                last_archive_at=EPOCH - 30, chain=chain(4)),
                native_chain_authenticated=True, native_chain=chain(3),
                native_chain_observed_at=(journal - timedelta(seconds=1)).isoformat(),
                journal_at=journal.isoformat(), segment_size=16 * 1024**2)


def check(observation, function=readiness.current_checkpoint_advancement):
    return function(observation, dict(maintenance_ready=True, continuity_ready=False,
                                     base='base-20310421T000000Z'), NOW, **EXPECTED)


@pytest.mark.parametrize('mode', ['native', 'runtime-full', 'runtime-incremental', 'runtime-cache'])
def test_accepts_canonical_producer_modes_and_preserves_evidence(observation, mode):
    if mode != 'native':
        full = mode == 'runtime-full'
        hashed = 8 if full else 2 if mode == 'runtime-incremental' else 0
        observation['checkpoint']['chain'].update(
            integrity_max_reuse_seconds=300, integrity_full_scrub=full,
            integrity_objects_hashed=hashed, integrity_read_passes=2 if hashed else 0)
    before = copy.deepcopy(observation)
    result = check(observation)
    assert observation == before
    assert result['maintenance_checkpoint_refreshed'] is False
    assert result['native_verified_through_wal'] == chain(3)['recoverable_through_wal']
    assert result['current_verified_through_wal'] == observation['primary']['last_archived_wal']
    assert result['original_last_archive_at'] == EPOCH - 30


@pytest.mark.parametrize('path,value', [
    (('checkpoint_authenticated',), False),
    (('native_chain_authenticated',), False),
    (('capacity_valid',), False),
    (('observed_at',), (NOW - timedelta(seconds=6)).isoformat()),
    (('observed_at',), (NOW + timedelta(seconds=1)).isoformat()),
    (('current_context', 'broker_account_id'), 'FOREIGN'),
    (('current_context', 'git_commit'), 'c' * 40),
    (('current_context', 'runtime_image_digest'), 'sha256:' + 'c' * 64),
    (('checkpoint', 'context', 'takeover_epoch'), 2),
    (('primary', 'postmaster_start_us'), 124),
    (('primary', 'archive_mode'), 'off'),
    (('capacity_engine',), 'other'),
    (('checkpoint', 'engine_id'), 'other'),
    (('segment_size',), 3),
    (('checkpoint', 'last_archive_at'), EPOCH),
    (('primary', 'last_archived_wal'), chain(3)['recoverable_through_wal']),
    (('native_chain_observed_at',), (NOW - timedelta(seconds=121)).isoformat()),
    (('native_chain_observed_at',), NOW.isoformat()),
])
def test_refuses_foreign_stale_or_uncovered_evidence(observation, path, value):
    target = observation
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(readiness.BackupReadinessRefused):
        check(observation)


@pytest.mark.parametrize('producer', ['native_chain', 'checkpoint'])
@pytest.mark.parametrize('field,value', [
    ('enabled', False), ('backup_state', 'DEGRADED'),
    ('system_identifier', 'other'), ('base_backup', 'other'),
    ('wal_integrity', 'other'), ('integrity_full_scrub', False),
    ('integrity_read_passes', 2), ('wal_segments', 100),
    ('integrity_objects_hashed', 0), ('recovery_marker_wal', 'invalid'),
])
def test_refuses_incomplete_or_inconsistent_chains(observation, producer, field, value):
    target = observation[producer]
    if producer == 'checkpoint':
        target = target['chain']
    target[field] = value
    with pytest.raises(readiness.BackupReadinessRefused):
        check(observation)


@pytest.mark.parametrize('field,value', [
    ('integrity_max_reuse_seconds', 301), ('integrity_max_reuse_seconds', True),
    ('integrity_full_scrub', 'false'), ('integrity_full_scrub', True),
    ('integrity_objects_hashed', 1), ('integrity_objects_hashed', 10),
    ('integrity_objects_hashed', False), ('integrity_read_passes', 1),
])
def test_refuses_invalid_runtime_cache_modes(observation, field, value):
    target = observation['checkpoint']['chain']
    target.update(integrity_max_reuse_seconds=300, integrity_full_scrub=False,
                  integrity_objects_hashed=0, integrity_read_passes=0)
    target[field] = value
    with pytest.raises(readiness.BackupReadinessRefused):
        check(observation)


def test_native_scan_cannot_claim_runtime_cache_reuse(observation):
    observation['native_chain'].update(integrity_max_reuse_seconds=300,
                                     integrity_full_scrub=False,
                                     integrity_objects_hashed=0, integrity_read_passes=0)
    with pytest.raises(readiness.BackupReadinessRefused):
        check(observation)


def test_original_archive_clock_and_strict_advancement_remain_required(observation):
    observation['native_chain'] = chain(4)
    with pytest.raises(readiness.BackupReadinessRefused, match='genuinely advance'):
        check(observation)
    observation['native_chain'] = chain(3)
    observation['primary']['last_archive_at'] = EPOCH - 600
    observation['checkpoint']['last_archive_at'] = EPOCH - 600
    with pytest.raises(readiness.BackupReadinessRefused, match='archive clock'):
        check(observation)


@pytest.mark.parametrize('reason,path,value', [
    ('current chain evidence unauthenticated', ('checkpoint_authenticated',), False),
    ('current checkpoint observation stale or future', ('observed_at',),
     (NOW - timedelta(seconds=6)).isoformat()),
    ('checkpoint does not cover actual current archive boundary',
     ('primary', 'last_archived_wal'), chain(3)['recoverable_through_wal']),
    ('checkpoint did not genuinely advance verified prefix', ('native_chain',), chain(4)),
    ('current producer integrity mode invalid',
     ('checkpoint', 'chain', 'integrity_objects_hashed'), 1),
])
def test_removed_guard_falsifiers_detect_unsafe_acceptance(observation, reason, path, value):
    target = observation
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(readiness.BackupReadinessRefused):
        check(observation)
    tree = ast.parse(inspect.getsource(readiness.current_checkpoint_advancement))
    removed = []

    class Remove(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == '_require' and len(call.args) > 1
                    and isinstance(call.args[1], ast.Constant) and call.args[1].value == reason):
                removed.append(reason)
                return ast.Pass()
            return self.generic_visit(node)

    tree = ast.fix_missing_locations(Remove().visit(tree))
    assert removed == [reason]
    namespace = dict(readiness.__dict__)
    exec(compile(tree, '<removed readiness guard>', 'exec'), namespace)
    check(observation, namespace['current_checkpoint_advancement'])
