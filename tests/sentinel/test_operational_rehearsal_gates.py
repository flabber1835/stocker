"""The joint rehearsal must fail on thin margins and stalled evidence."""
from types import SimpleNamespace

import pytest

from tools.operational_rehearsal import paper as rehearsal
from tools.operational_rehearsal.runner import (
    _callback_headroom, _database_headroom,
)


def _sample(*, anon=0, shmem=0, active_file=0):
    return dict(anon=anon, shmem=shmem, active_file=active_file,
                slab_unreclaimable=0, kernel_stack=0, pagetables=0)


def test_database_headroom_counts_nonreclaimable_memory_not_file_cache():
    gib = 1024**3
    mib = 1024**2
    assert _database_headroom([_sample(anon=500*mib, active_file=500*mib)], gib)
    assert not _database_headroom([_sample(anon=900*mib, shmem=20*mib)], gib)
    assert not _database_headroom([], gib)


def test_full_size_callback_requires_twenty_percent_deadline_margin():
    cycles = lambda seconds: [dict(callbacks=[dict(seconds=seconds)])]
    assert _callback_headroom(cycles(720))
    assert not _callback_headroom(cycles(829.495))
    assert not _callback_headroom([])


@pytest.mark.parametrize('next_cursor,outcome', [((4, 'p2'), 'ready'), ((5, ''), 'ready'),
                                              ((4, 'p1'), 'stalled'), ((3, ''), 'stalled')])
def test_mirror_retry_requires_durable_page_progress(monkeypatch, next_cursor, outcome):
    cursors = iter([(4, 'p1'), next_cursor])
    def load(conn, domain):
        assert domain == 'MIRROR'
        sequence, after_plan = next(cursors)
        return {'through': sequence, 'body': {'event_after_plan': after_plan}}
    monkeypatch.setattr(rehearsal.evidence_projection, 'load', load)
    attempts = []
    async def prepare(**kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            cause = rehearsal.informational_paper_mirror.InformationalPaperMirrorPending('pending')
            raise rehearsal.paper.PaperRetryableRefused('not yet ready') from cause
        return 'ready'
    monkeypatch.setattr(rehearsal.paper, 'prepare_paper_plan', prepare)
    conn = SimpleNamespace(rollback=lambda: None)
    if outcome == 'ready':
        assert rehearsal.prepare_with_progress(conn, {}) == 'ready' and len(attempts) == 2
    else:
        with pytest.raises(AssertionError, match='no durable progress'):
            rehearsal.prepare_with_progress(conn, {})
        assert len(attempts) == 1


def test_other_activation_refusals_propagate_from_first_attempt(monkeypatch):
    monkeypatch.setattr(rehearsal.evidence_projection, 'load', lambda *_:
                        {'through': 1, 'body': {'event_after_plan': ''}})
    calls = []
    async def prepare(**kwargs):
        calls.append(1)
        raise rehearsal.paper.PaperRetryableRefused('other refusal')
    monkeypatch.setattr(rehearsal.paper, 'prepare_paper_plan', prepare)
    with pytest.raises(rehearsal.paper.PaperRetryableRefused, match='other refusal'):
        rehearsal.prepare_with_progress(SimpleNamespace(rollback=lambda: None), {})
    assert len(calls) == 1
