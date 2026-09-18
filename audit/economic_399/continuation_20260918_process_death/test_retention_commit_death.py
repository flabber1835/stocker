"""#399 actual SIGKILL at bounded retention mutations and diagnostic commits."""
import json
import os
import select
import signal
import traceback
from datetime import date

import pytest

from sentinel.feed import retention, store, rolling_store
from sentinel.execution import feed_actions
from tests.conftest import isolated_source_cache, isolated_image_backup_policy  # noqa: F401
from tests.sentinel.test_rolling_history_retention import aged_source, publish
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401

POINTS = ("retirement_row", "bar_delete", "benchmark_delete", "evidence_release",
          "retention_commit_before", "retention_commit_after", "diagnostic_write",
          "diagnostic_commit_before", "diagnostic_commit_after")


def kill_retention(dsn, inherited_fd, selected):
    r, w = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(r)
        os.close(inherited_fd)
        try:
            c = store.connect(dsn)
            state = {"stage": None, "candidate": None}
            def hit(point, changed=None):
                if point == selected:
                    marker = dict(boundary=point, pid=os.getpid(), backend_pid=c.info.backend_pid,
                                  candidate=state["candidate"], changed_rows=changed)
                    os.write(w, (json.dumps(marker) + "\n").encode())
                    while True:
                        signal.pause()
            class Connection:
                def __getattr__(self, name):
                    return getattr(c, name)
                def execute(self, query, *args, **kwargs):
                    result = c.execute(query, *args, **kwargs)
                    sql = " ".join(str(query).lower().split())
                    if sql.startswith("insert into sentinel_snapshot_retirements"):
                        state["candidate"] = str(args[0][0])
                        state["stage"] = "retention"
                        assert result.rowcount == 1
                        hit("retirement_row", result.rowcount)
                    elif sql.startswith("delete from sentinel_snapshot_bars"):
                        assert result.rowcount > 0
                        hit("bar_delete", result.rowcount)
                    elif sql.startswith("delete from sentinel_snapshot_benchmarks"):
                        assert result.rowcount > 0
                        hit("benchmark_delete", result.rowcount)
                    elif sql.startswith("update sentinel_snapshot_evidence set payload=null"):
                        assert result.rowcount > 0
                        hit("evidence_release", result.rowcount)
                    elif sql.startswith("insert into sentinel_snapshot_maintenance"):
                        state["stage"] = "diagnostic"
                        hit("diagnostic_write", result.rowcount)
                    return result
                def commit(self):
                    stage = state["stage"]
                    if stage:
                        hit(stage + "_commit_before")
                    c.commit()
                    if stage:
                        hit(stage + "_commit_after")
                        state["stage"] = None
            outcome = retention.maintain(Connection(), batch_rows=50000)
            os.write(w, (json.dumps(dict(error="boundary not reached", outcome=outcome)) + "\n").encode())
        except BaseException:
            os.write(w, (json.dumps(dict(error=traceback.format_exc())) + "\n").encode())
        os._exit(2)
    os.close(w)
    reaped = False
    try:
        readable, _, _ = select.select([r], [], [], 40)
        assert readable, f"retention did not reach {selected}"
        marker = json.loads(os.read(r, 65536))
        assert "error" not in marker, marker
        assert marker["boundary"] == selected and marker["pid"] == child
        os.kill(child, signal.SIGKILL)
        _, status = os.waitpid(child, 0)
        reaped = True
        assert os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        return marker
    finally:
        os.close(r)
        if not reaped:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child, 0)


def history(conn):
    return {
        table: conn.execute(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY row_to_json(t)::text").fetchall()
        for table in ("sentinel_action_history", "sentinel_action_coverage", "sentinel_corpus_publications",
                      "sentinel_operational_snapshots", "sentinel_snapshot_jobs")
    }


@pytest.mark.parametrize("boundary", POINTS)
def test_retention_death_preserves_publication_and_action_closure(
        conn, operational_source, monkeypatch, record_property, boundary):
    pubs = []
    # Isolate the next production maintenance invocation after three completed
    # publications; automatic inter-publication maintenance is deferred here.
    with monkeypatch.context() as defer:
        defer.setattr(retention, "maintain", lambda *_: None)
        for end in ("2025-01-02", "2025-12-01", "2026-09-14"):
            aged_source(operational_source, monkeypatch, end)
            pubs.append(publish(conn))
    conn.commit()
    assert conn.execute("SELECT count(*) FROM sentinel_snapshot_retirements").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM sentinel_snapshot_maintenance").fetchone()[0] == 0
    original_history = history(conn)
    original_evidence = dict(conn.execute("SELECT evidence_sha256,payload FROM sentinel_snapshot_evidence").fetchall())
    conn.rollback()
    marker = kill_retention(conn.info.dsn, conn.fileno(), boundary)
    record_property("kill_boundary", json.dumps(marker, sort_keys=True))
    c = store.connect(conn.info.dsn)
    try:
        committed = boundary in ("retention_commit_after", "diagnostic_write",
                                  "diagnostic_commit_before", "diagnostic_commit_after")
        candidate = marker["candidate"]
        assert candidate in {p["candidate_id"] for p in pubs[:-1]}
        assert rolling_store.retired(c, candidate) == committed
        for table, expected in (("sentinel_snapshot_bars", 600), ("sentinel_snapshot_benchmarks", 300)):
            assert c.execute(f"SELECT count(*) FROM {table} WHERE candidate_id=%s", (candidate,)).fetchone()[0] == (0 if committed else expected)
        diagnostic = c.execute("SELECT diagnostic FROM sentinel_snapshot_maintenance").fetchone()
        assert (diagnostic is not None) == (boundary == "diagnostic_commit_after")
        assert history(c) == original_history
        remaining_evidence = dict(c.execute("SELECT evidence_sha256,payload FROM sentinel_snapshot_evidence").fetchall())
        assert remaining_evidence.keys() == original_evidence.keys()
        if committed:
            assert sum(v is None for v in remaining_evidence.values()) > sum(v is None for v in original_evidence.values())
            assert all(v is None or v == original_evidence[k] for k,v in remaining_evidence.items())
        else:
            assert remaining_evidence == original_evidence
        c.rollback()
        for _ in range(4):
            assert retention.maintain(c, batch_rows=1000)["status"] == "COMPLETE"
        assert all(rolling_store.retired(c, p["candidate_id"]) for p in pubs[:-1])
        assert not rolling_store.retired(c, pubs[-1]["candidate_id"])
        assert c.execute("SELECT count(*) FROM sentinel_snapshot_bars").fetchone()[0] == 600
        assert c.execute("SELECT count(*) FROM sentinel_snapshot_benchmarks").fetchone()[0] == 300
        assert history(c) == original_history
        lookup = feed_actions.action_lookup(c, start=date(2024,12,13), end=date(2026,9,14))
        assert lookup("1") == lookup("SENTINEL:BIL") == 6
        record_property("retained_split_factor", str(lookup("1")))
        c.rollback()
    finally:
        c.close()
