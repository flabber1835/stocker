"""The full-size rehearsal must refuse close resource and callback margins."""

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
