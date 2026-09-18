"""#399 actual process-death visibility at publication/action-history SQL writes.

A test-only lease timestamp advance exercises expiry/reclaim after verifying the
immediate production refusal against the retained live lease. No source edits.
"""
import json
import os
import select
import signal
import traceback

import pytest

from sentinel.feed import operational_snapshot as op, publication, rolling_jobs as jobs
from sentinel.feed import store, action_history
from sentinel.feed.rolling_contract import digest
from tests.conftest import isolated_source_cache, isolated_image_backup_policy  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

POINTS = ("action_row", "coverage_row", "publication_row", "receipt_row",
          "binding_row", "published_job", "publication_commit_before", "publication_commit_after")
TABLES = ("sentinel_action_history", "sentinel_action_coverage", "sentinel_corpus_publications",
          "sentinel_publication_validation_receipts", "sentinel_operational_snapshots")


def kill_publisher(dsn, inherited_fd, job, selected):
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        os.close(inherited_fd)
        try:
            c = store.connect(dsn)
            final = {"written": False}
            def hit(point):
                if point == selected:
                    marker = dict(boundary=point, child_pid=os.getpid(), backend_pid=c.info.backend_pid,
                                  job=job, state=jobs.status(c, job)["state"])
                    os.write(write_fd, (json.dumps(marker) + "\n").encode())
                    while True:
                        signal.pause()
            def after(query):
                sql = " ".join(str(query).lower().split())
                for prefix, point in (
                    ("insert into sentinel_action_history ", "action_row"),
                    ("insert into sentinel_action_coverage ", "coverage_row"),
                    ("insert into sentinel_corpus_publications ", "publication_row"),
                    ("insert into sentinel_publication_validation_receipts ", "receipt_row"),
                    ("insert into sentinel_operational_snapshots ", "binding_row"),
                ):
                    if sql.startswith(prefix):
                        hit(point)
                if sql.startswith("update sentinel_snapshot_jobs set state='published'"):
                    final["written"] = True
                    hit("published_job")
            class Cursor:
                def __init__(self, cursor):
                    self.cursor = cursor
                def __getattr__(self, name):
                    return getattr(self.cursor, name)
                def __iter__(self):
                    return iter(self.cursor)
                def __enter__(self):
                    self.cursor.__enter__()
                    return self
                def __exit__(self, *args):
                    return self.cursor.__exit__(*args)
                def execute(self, query, *args, **kwargs):
                    self.cursor.execute(query, *args, **kwargs)
                    after(query)
                    return self
            class Connection:
                def __getattr__(self, name):
                    return getattr(c, name)
                def cursor(self, *a, **kw):
                    return Cursor(c.cursor(*a, **kw))
                def execute(self, query, *a, **kw):
                    result = c.execute(query, *a, **kw)
                    after(query)
                    return result
                def commit(self):
                    if final["written"]:
                        hit("publication_commit_before")
                    c.commit()
                    if final["written"]:
                        hit("publication_commit_after")
                        final["written"] = False
            op.prepare(Connection(), job)
            os.write(write_fd, b'{"error":"selected publication boundary was not reached"}\n')
        except BaseException:
            os.write(write_fd, (json.dumps(dict(error=traceback.format_exc())) + "\n").encode())
        os._exit(2)
    os.close(write_fd)
    reaped = False
    try:
        readable, _, _ = select.select([read_fd], [], [], 45)
        assert readable, f"publisher did not reach {selected}"
        marker = json.loads(os.read(read_fd, 65536))
        assert "error" not in marker, marker.get("error")
        assert marker["boundary"] == selected
        os.kill(pid, signal.SIGKILL)
        _, status = os.waitpid(pid, 0)
        reaped = True
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        return marker
    finally:
        os.close(read_fd)
        if not reaped:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


def counts(c):
    return {table: c.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in TABLES}


@pytest.mark.parametrize("boundary", POINTS)
def test_real_publisher_death_keeps_receipt_actions_binding_atomic(
        conn, operational_source, record_property, boundary):
    job = op.enqueue(conn, strategy_sha256=digest("audit-publication"),
                     dependencies_sha256=digest("audit-atomicity"), budget_seconds=600)
    conn.commit()
    assert counts(conn) == dict.fromkeys(TABLES, 0)
    conn.rollback()
    marker = kill_publisher(conn.info.dsn, conn.fileno(), job, boundary)
    record_property("kill_boundary", json.dumps(marker, sort_keys=True))
    c = store.connect(conn.info.dsn)
    try:
        committed = boundary == "publication_commit_after"
        before = counts(c)
        state = jobs.status(c, job)
        assert all(value > 0 for value in before.values()) if committed else before == dict.fromkeys(TABLES, 0)
        assert state["state"] == ("PUBLISHED" if committed else "READY")
        previous_fence = state["fence"]
        candidate_id = state["candidate_id"]
        retained = op.published(c, job)
        assert bool(retained) == committed
        c.rollback()
        if not committed:
            # Confirm original #400 A4: the normal caller refuses an active
            # dead worker lease. This witness retains that known disposition.
            with pytest.raises(jobs.JobRefused, match="owned, waiting, expired or terminal"):
                op.prepare(c, job)
            c.rollback()
            assert counts(c) == dict.fromkeys(TABLES, 0)
            c.execute("UPDATE sentinel_snapshot_jobs SET lease_until=clock_timestamp()-interval '1 second' "
                      "WHERE job_id=%s", (job,))
            c.commit()
        recovered = op.prepare(c, job)
        assert recovered["job_id"] == job and recovered["candidate_id"] == candidate_id
        assert recovered["data_version"] == 1 and recovered["scope"] == "DATA_ONLY"
        after = counts(c)
        assert after["sentinel_action_history"] > 0
        for table in TABLES[1:]:
            assert after[table] == 1
        state = jobs.status(c, job)
        assert state["state"] == "PUBLISHED"
        assert state["fence"] == previous_fence + int(not committed)
        if committed:
            assert recovered == retained
        c.rollback()
        with op.pinned(c) as (pub, binding):
            assert binding == recovered
            manifest = action_history.coverage(c, pub,
                start=__import__('datetime').date.fromisoformat(pub.window_start),
                end=__import__('datetime').date.fromisoformat(pub.window_end))
            records = action_history.records(c, version=pub.version,
                start=pub.window_start, end=pub.window_end)
            assert len(records) == len(manifest["added"]) > 0
            assert all(digest(records[day]) == sha for day, sha in manifest["added"].items())
            record_property("publication_version", pub.version)
            record_property("action_coverage_digest", digest(manifest))
        assert op.prepare(c, job) == recovered
        assert counts(c) == after
        c.rollback()
    finally:
        c.close()
