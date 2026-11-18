"""A published refusal does not give an old worker authority to fence its successor."""
from concurrent.futures import ThreadPoolExecutor
import inspect
import queue
import time

import pytest

from sentinel.automation import store
from sentinel.automation.model import StaleLeaderRefused
from sentinel.feed import store as feed_store
from tests.sentinel.test_automation_store import conn, enable, identity, pg


def refused(conn):
    control = enable(conn)
    permit = store.acquire_lease(conn, holder_id="former-leader", lease_seconds=30)
    store.record_authority_verdict(conn, verdict="FAIL", detail="certificate revoked",
        holder_id=permit.holder_id, fence_token=permit.fence_token, control_generation=control.generation)
    return permit


def evidence(conn):
    try:
        return conn.execute("""
            SELECT (SELECT to_jsonb(c) FROM sentinel_automation_control c WHERE id=1),
                   (SELECT to_jsonb(l) FROM sentinel_automation_lease l WHERE id=1),
                   (SELECT jsonb_agg(to_jsonb(e) ORDER BY seq) FROM sentinel_automation_events e)
        """).fetchone()
    finally:
        conn.rollback()


def latch(conn, permit):
    return store.engage_kill_if_leader(conn, permit, actor="sentinel-automation", reason="idle authority refusal")


@pytest.mark.parametrize("change", ["takeover", "same_holder_new_fence", "foreign_holder", "generation", "expired", "none"])
def test_old_idle_refusal_cannot_fence_a_changed_worker_or_control(conn, pg, change):
    original = refused(conn)
    with feed_store.connect(pg.sync_dsn) as updated:
        if change in {"takeover", "same_holder_new_fence"}:
            if change == "takeover":
                updated.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-interval '1 second'")
                updated.commit()
            else:
                store.release_lease(updated, permit=original)
            new_holder = "replacement" if change == "takeover" else original.holder_id
            current = store.acquire_lease(updated, holder_id=new_holder, lease_seconds=30)
            assert current.fence_token != original.fence_token
        elif change == "foreign_holder":
            original = original.model_copy(update={"holder_id":"foreign"})
        elif change == "generation":
            store.engage_kill(updated, actor="operator", reason="deliberate handoff")
            store.release_kill(updated, expected_binding=identity(), actor="operator", reason="new authority")
            current = store.acquire_lease(updated, holder_id=original.holder_id, lease_seconds=30)
            assert current.control_generation != original.control_generation
        elif change == "expired":
            updated.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-interval '1 second'")
            updated.commit()
        else:
            original = None
        before = evidence(updated)
        with pytest.raises(StaleLeaderRefused):
            latch(conn, original)
        assert evidence(updated) == before


def test_current_idle_refusal_commits_one_kill_with_its_lease_invalidation(conn):
    permit = refused(conn)
    before = evidence(conn)
    assert before[0]['authority_verdict'] == 'FAIL'
    result = latch(conn, permit)
    after = evidence(conn)
    assert result.kill_switch_engaged and result.generation == permit.control_generation + 1
    assert after[1]['holder_id'] is None and after[1]['expires_at'] is None
    assert after[2][:-1] == before[2] and after[2][-1]['action'] == 'KILL_ENGAGED'
    with pytest.raises(StaleLeaderRefused):
        latch(conn, permit)
    assert evidence(conn) == after
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone() == (0,)


def test_permit_expiring_while_waiting_for_the_lease_row_cannot_latch(conn, pg):
    permit = refused(conn)
    waiting = queue.Queue()

    def former_leader():
        with feed_store.connect(pg.sync_dsn) as leader:
            waiting.put(leader.info.backend_pid)
            with pytest.raises(StaleLeaderRefused):
                latch(leader, permit)

    with feed_store.connect(pg.sync_dsn) as blocker, ThreadPoolExecutor(1) as pool:
        blocker.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()+interval '2 seconds'")
        blocker.commit()
        before = evidence(conn)
        blocker.execute("SELECT id FROM sentinel_automation_lease WHERE id=1 FOR UPDATE")
        try:
            pending = pool.submit(former_leader)
            target = waiting.get(timeout=5)
            deadline = time.monotonic()+4
            while not blocker.execute("SELECT pg_backend_pid()=ANY(pg_blocking_pids(%s))", (target,)).fetchone()[0]:
                assert time.monotonic()<deadline, "worker did not contend for the lease row"
                time.sleep(.01)
            assert blocker.execute("SELECT expires_at>clock_timestamp() FROM sentinel_automation_lease").fetchone() == (True,)
            blocker.execute("SELECT pg_sleep_until(expires_at+interval '20 milliseconds') FROM sentinel_automation_lease")
        finally:
            blocker.rollback()
        pending.result(timeout=5)
    assert evidence(conn) == before


def test_kill_rolled_back_if_database_clock_expires_after_lock_and_before_invalidation(conn, monkeypatch):
    permit = refused(conn)
    conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()+interval '1 second'")
    conn.commit()
    before = evidence(conn)
    invalidate = store._invalidate_lease

    def late(cur, *, require_live=False):
        cur.execute("SELECT generation FROM sentinel_automation_control WHERE id=1")
        assert cur.fetchone() == (permit.control_generation+1,)
        cur.execute("SELECT pg_sleep_until(expires_at+interval '20 milliseconds') FROM sentinel_automation_lease")
        invalidate(cur, require_live=require_live)

    monkeypatch.setattr(store, '_invalidate_lease', late)
    with pytest.raises(StaleLeaderRefused):
        latch(conn, permit)
    assert evidence(conn) == before


def test_removed_last_database_time_check_is_caught(conn, monkeypatch):
    source=inspect.getsource(store._invalidate_lease)
    guard='" AND expires_at>clock_timestamp()" if require_live else ""'
    assert source.count(guard) == 1
    namespace={}
    exec(compile(source.replace(guard, '""'), '<removed-live-expiry>', 'exec'), vars(store), namespace)
    monkeypatch.setattr(store, '_invalidate_lease', namespace['_invalidate_lease'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_kill_rolled_back_if_database_clock_expires_after_lock_and_before_invalidation(conn, monkeypatch)
