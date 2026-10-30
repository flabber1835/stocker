"""Production proof ordering with private media, without a database process."""
import ast
import inspect

import pytest

from sentinel import backup_runtime_authority as authority
from sentinel.execution import journal
from lab import Cursor, Database, Media, wal_name


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv(authority.AUTHORITY_ENV, authority.AUTHORITY_VALUE)
    return Database(Media(tmp_path / "media"))


def _slow_writer_admission(world, monkeypatch):
    clock = [100.0]
    reads = []
    original = authority._hash_objects
    monkeypatch.setattr(authority.time, "monotonic", lambda: clock[0])

    def slow(*args, **kwargs):
        if kwargs["objects"]:
            reads.append(bool(world.locks))
            clock[0] += authority.FULL_SCRUB_SECONDS
        return original(*args, **kwargs)

    monkeypatch.setattr(authority, "_hash_objects", slow)
    with journal.writer_lock(world):
        assert world.locks == {journal.WRITER_LOCK_KEY: 1}
    # Both complete passes take place before owning the account. Completion,
    # rather than the scrub's start, gives the inner check a reusable proof.
    assert reads == [False, False]
    assert not world.locks


def test_slow_cold_proof_finishes_before_writer_and_is_not_immediately_repeated(world, monkeypatch):
    _slow_writer_admission(world, monkeypatch)


def _fault_after_preflight(world):
    class LoseMediaAtAcquisition(Cursor):
        def execute(self, sql, params=()):
            super().execute(sql, params)
            if sql == "SELECT pg_try_advisory_lock(%s)":
                (world.media.namespace / wal_name(4)).unlink()

    world.cursor = lambda: LoseMediaAtAcquisition(world)
    mutations = []
    with pytest.raises(authority.BackupRuntimeUnavailable, match="missing/truncated"):
        with journal.writer_lock(world):
            mutations.append("unsafe")
    assert mutations == []
    assert world.locks == {} and world.rollbacks == 1


def test_fresh_inner_gate_still_refuses_media_loss_after_successful_preflight(world):
    _fault_after_preflight(world)


def test_preflight_refusal_never_takes_writer_or_commits(world):
    (world.media.namespace / wal_name(4)).unlink()
    with pytest.raises(authority.BackupRuntimeUnavailable):
        with journal.writer_lock(world):
            pytest.fail("missing archive authorized mutation")
    assert not any("advisory_lock" in sql for sql, _ in world.statements)
    assert world.rollbacks == 1 and world.commits == 0


def test_incremental_frontier_does_not_extend_completed_full_scrub_expiry(world, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(authority.time, "monotonic", lambda: clock[0])
    assert authority.require(world, operation="initial")["integrity_full_scrub"]
    clock[0] = 300.0
    world.media.segment(6)
    world.frontier = wal_name(6)
    increment = authority.require(world, operation="new tail")
    assert not increment["integrity_full_scrub"]
    assert increment["integrity_objects_hashed"] == 2
    clock[0] = 400.0
    renewed = authority.require(world, operation="original expiry")
    assert renewed["integrity_full_scrub"]
    assert renewed["integrity_objects_hashed"] == 10


def _forked_cache_boundary(world, monkeypatch):
    process = [100]
    monkeypatch.setattr(authority.os, "getpid", lambda: process[0])
    assert authority.require(world, operation="parent")["integrity_full_scrub"]
    assert not authority.require(world, operation="same process")["integrity_full_scrub"]
    process[0] = 200
    assert authority.require(world, operation="fork child")["integrity_full_scrub"]


def test_forked_process_cannot_reuse_inherited_parent_cache(world, monkeypatch):
    _forked_cache_boundary(world, monkeypatch)


def test_removing_process_scope_is_detected(world, monkeypatch):
    source = inspect.getsource(authority._connection_scope)
    old = 'return f"{os.getpid()}:{target}"'
    assert old in source
    namespace = dict(authority.__dict__)
    exec(compile(source.replace(old, "return target"), "<process-scope-falsifier>", "exec"), namespace)
    monkeypatch.setattr(authority, "_connection_scope", namespace["_connection_scope"])
    with pytest.raises(AssertionError):
        _forked_cache_boundary(world, monkeypatch)


def test_clock_rollback_forces_full_content_proof(world, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(authority.time, "monotonic", lambda: clock[0])
    assert authority.require(world, operation="initial")["integrity_full_scrub"]
    clock[0] = 99.0
    assert authority.require(world, operation="clock rollback")["integrity_full_scrub"]


def test_failed_refreshed_proof_invalidates_prior_success(world, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(authority.time, "monotonic", lambda: clock[0])
    authority.require(world, operation="initial")
    path = world.media.namespace / wal_name(4)
    path.write_bytes(b"X" * path.stat().st_size)
    with pytest.raises(authority.BackupRuntimeRefused, match="SHA-256"):
        authority.require(world, operation="damaged")
    assert not authority._PROOF_CACHE
    world.media.segment(4)
    assert authority.require(world, operation="repaired")["integrity_full_scrub"]


def test_failed_lock_acquisition_rolls_back_preflight_without_unlock_or_commit(world):
    class Busy(Cursor):
        def execute(self, sql, params=()):
            if sql == "SELECT pg_try_advisory_lock(%s)":
                self.rows = [(False,)]
                return
            super().execute(sql, params)

    world.cursor = lambda: Busy(world)
    with pytest.raises(journal.WriterLockUnavailable):
        with journal.writer_lock(world):
            pytest.fail("busy account writer yielded")
    assert world.rollbacks == 1 and world.commits == 0 and not world.locks
    assert not any("advisory_unlock" in sql for sql, _ in world.statements)


def test_recovery_scope_still_avoids_backup_admission_but_cannot_grant_nested_mutation(world):
    (world.media.namespace / wal_name(4)).unlink()
    with journal.writer_lock(world, recovery_only=True):
        with pytest.raises(authority.BackupRuntimeUnavailable):
            with journal.writer_lock(world):
                pytest.fail("recovery bypass reached financial mutation")
        assert world.locks == {journal.WRITER_LOCK_KEY: 1}


def _broken_writer(which):
    tree = ast.parse(inspect.getsource(journal.writer_lock))
    function = tree.body[0]
    guarded = next(node for node in function.body if isinstance(node, ast.Try))
    checks = [i for i, node in enumerate(guarded.body)
              if isinstance(node, ast.If) and ast.unparse(node.test) == "not recovery_only"]
    assert len(checks) == 2
    del guarded.body[checks[0] if which == "preflight" else checks[1]]
    namespace = dict(journal.__dict__)
    exec(compile(ast.fix_missing_locations(tree), "<writer-guard-falsifier>", "exec"), namespace)
    return namespace["writer_lock"]


def test_removing_preflight_is_detected_by_actual_hash_lock_observation(world, monkeypatch):
    monkeypatch.setattr(journal, "writer_lock", _broken_writer("preflight"))
    with pytest.raises(AssertionError):
        _slow_writer_admission(world, monkeypatch)


def test_removing_inner_guard_is_detected_by_post_preflight_media_loss(world, monkeypatch):
    monkeypatch.setattr(journal, "writer_lock", _broken_writer("inner"))
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        _fault_after_preflight(world)


def test_reverting_completion_clock_is_detected(world, monkeypatch):
    source = inspect.getsource(authority._validate_archive_objects)
    old = '"full_scrub_at": time.monotonic() if full_scrub'
    assert old in source
    namespace = dict(authority.__dict__)
    exec(compile(source.replace(old, '"full_scrub_at": now if full_scrub'),
                 "<scrub-clock-falsifier>", "exec"), namespace)
    monkeypatch.setattr(authority, "_validate_archive_objects", namespace["_validate_archive_objects"])
    with pytest.raises(AssertionError):
        _slow_writer_admission(world, monkeypatch)
