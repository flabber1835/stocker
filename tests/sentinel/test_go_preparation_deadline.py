"""Host -> real preparation payload -> PostgreSQL, with elapsed work controlled."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import io
import json
from contextlib import redirect_stdout, redirect_stderr

import psycopg
import pytest

from sentinel.feed import rolling_go_inputs as inputs, rolling_jobs as jobs
from tests.sentinel.test_rolling_go_inputs import ROOT, issuer_source, operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


@pytest.mark.parametrize("value", [None, "", "secret", "2026-09-29T20:00:00",
                                  "2026-09-29T20:00:00+02:00", 7200])
def test_missing_or_invalid_host_cutoff_cannot_default_to_one_hour(value):
    with pytest.raises(inputs.RollingGoRefused, match="DEADLINE_INVALID"):
        inputs.deadline_from_host(value)


@pytest.mark.parametrize("exhaust", [False, True])
def test_slow_preparation_and_backup_share_original_host_deadline(
        conn, issuer_source, monkeypatch, tmp_path, exhaust):
    from sentinel import backup_guard, backup_runtime_authority as authority, shadow_runtime
    from sentinel.feed import rolling_builder, rolling_publisher, store, calendar, operational_snapshot
    from tests.sentinel.test_go_backup_refresh import backup, GrowingWalRunner, TOKEN, _cp, run_overlay
    import sentinel_go_deadline as host_deadline
    import sentinel_go_feed_progress as host_progress
    from sentinel_go_backup_retry import FAILURE

    initial = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.commit()
    elapsed = [0.0]
    clock = SimpleNamespace(monotonic=lambda: elapsed[0],
                            time=lambda: initial.timestamp() + elapsed[0])
    monkeypatch.setattr(host_deadline, "time", clock)
    monkeypatch.setenv("SENTINEL_GO_PREPARATION_TIMEOUT_SECONDS", "7200")
    monkeypatch.setitem(backup.phase._PHASE, "certified", True)
    monkeypatch.setattr(backup.go_lock, "lifecycle_lock_is_held", lambda *a: True)
    monkeypatch.setattr(backup.go_lock, "current_run_token", lambda *a: TOKEN)
    monkeypatch.setattr(backup, "_AUDIT_PATH", tmp_path / "audit.json")
    monkeypatch.setattr(backup_guard, "require_writes_permitted", lambda *_a, **_kw: None)
    monkeypatch.setattr(shadow_runtime, "publication_not_before",
                        lambda _day: datetime.min.replace(tzinfo=timezone.utc))
    monkeypatch.setattr(calendar, "session_window",
                        lambda _day: (datetime.max.replace(tzinfo=timezone.utc), None))

    class ClockCursor(psycopg.Cursor):
        def execute(self, query, params=None, **kwargs):
            # Only substitute the observed server clock in runtime SQL. Keep
            # schema/defaults/triggers and all real storage/fencing code intact.
            if isinstance(query, str) and not query.lstrip().startswith(("CREATE", "ALTER", "DROP")):
                now = (initial + timedelta(seconds=elapsed[0])).isoformat()
                query = query.replace("clock_timestamp()", "'%s'::timestamptz" % now)
            return super().execute(query, params, **kwargs)

    conn.cursor_factory = ClockCursor

    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, "connect", lambda *_a, **_kw: Borrowed())

    checkpoint = rolling_publisher._checkpoint
    def slow_checkpoint(*args, **kwargs):
        checkpoint(*args, **kwargs)
        elapsed[0] += 45  # Each of 22 parts; lease remains live between pulses.
    monkeypatch.setattr(rolling_publisher, "_checkpoint", slow_checkpoint)
    build = rolling_builder.build
    def slow_build(c, lease, *args, **kwargs):
        for _ in range(6):
            elapsed[0] += 300
            jobs.heartbeat(c, lease, lease_seconds=600)
        return build(c, lease, *args, **kwargs)
    monkeypatch.setattr(rolling_builder, "build", slow_build)

    renewed = []
    original_require = authority.require
    def horizon(c, *, operation, **kwargs):
        row = c.execute("SELECT job_id,state FROM sentinel_snapshot_jobs ORDER BY created_at DESC LIMIT 1").fetchone()
        if (row and row[1] == "READY" and not renewed
                and operation == 'operational publication preflight'):
            authority._expected_wals("000000010000000000000000", "000000010000000000000040",
                                     segment_size=16 * 1024 * 1024)
        return original_require(c, operation=operation, **kwargs)
    monkeypatch.setattr(authority, "require", horizon)

    validate = operational_snapshot.validate
    def slow_resumed_validation(c, lease, request):
        if exhaust and renewed:
            for _ in range(20):
                elapsed[0] += 300
                jobs.heartbeat(c, lease, lease_seconds=600)
        return validate(c, lease, request)
    monkeypatch.setattr(operational_snapshot, 'validate', slow_resumed_validation)

    class Runner(GrowingWalRunner):
        def run(self, argv, *, env=None, cwd=None):
            if list(argv)[:2] != ["docker", "compose"]:
                if "scripts/sentinel-backup-status.sh" in argv and not self.preparations:
                    elapsed[0] += 180  # Initial durability work consumes budget.
                if "scripts/sentinel-base-backup.sh" in argv:
                    elapsed[0] += 900
                result = super().run(argv, env=env, cwd=cwd)
                if "--backup" in argv and result.returncode == 0:
                    renewed.append(True)
                return result
            self.preparations.append((list(argv), dict(env)))
            assert argv[argv.index(host_deadline.DEADLINE_ENV) - 1] == "--env"
            out, err = io.StringIO(), io.StringIO()
            # Execute the actual payload, including deadline decoding and the
            # full rolling_go_inputs.prepare call. No fabricated success marker.
            with monkeypatch.context() as child, redirect_stdout(out), redirect_stderr(err):
                for key, value in env.items():
                    child.setenv(key, value)
                child.setenv("SENTINEL_DATABASE_URL", "fixture")
                try:
                    exec(compile(argv[-1], "<real-go-preparation>", "exec"), {})
                except jobs.JobDeadlineExceeded:
                    assert exhaust
                    return _cp(1, out=out.getvalue(), err=err.getvalue())
                except authority.BackupHorizonExceeded:
                    return _cp(1, out=out.getvalue(), err=err.getvalue())
            return _cp(0, out=out.getvalue(), err=err.getvalue())

    runner = Runner([])
    summary = run_overlay(monkeypatch, runner)
    row = conn.execute("SELECT job_id,deadline,state,reason FROM sentinel_snapshot_jobs").fetchone()
    assert row[1] == initial + timedelta(seconds=7200)
    assert len(runner.preparations) == 2 and renewed == [True]
    assert {env[host_deadline.DEADLINE_ENV] for _, env in runner.preparations} == {row[1].isoformat()}
    assert "RETAINED_PART_REUSED" in runner.last_preparation_output
    assert len([call for call in issuer_source['calls'] if call[0] == 'download']) == 21
    if exhaust:
        assert not summary.complete and row[2:] == ("REFUSED", "DEADLINE_EXHAUSTED")
        failure = next(json.loads(line[len(FAILURE):]) for line in runner.last_preparation_output.splitlines()
                       if line.startswith(FAILURE))
        assert failure['reason_code'] == "PREPARATION_DEADLINE_EXHAUSTED"
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 0
    else:
        assert elapsed[0] > 3600 and summary.complete and row[2] == "PUBLISHED"
        stages = {e['stage'] for e in host_progress.collect(runner.last_preparation_output)}
        assert {'rolling_identity', 'rolling_normalization', 'rolling_seal',
                'rolling_operational_validation', 'rolling_operational_publication'} <= stages
        assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 1


def test_nested_budgets_and_wall_clock_changes_do_not_extend_cutoff(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import sentinel_go_deadline as deadline
    clock = SimpleNamespace(monotonic=lambda: 100, time=lambda: 100000)
    monkeypatch.setattr(deadline, "time", clock)
    with deadline.preparation_budget(7200):
        original = deadline.job_deadline()
        clock.monotonic = lambda: 1000
        clock.time = lambda: 200000
        with deadline.preparation_budget(7200):
            assert deadline.job_deadline() == original
            assert deadline.command_timeout(7200) == 6300
        assert deadline.job_deadline() == original
    with pytest.raises(RuntimeError, match="not established"):
        deadline.job_deadline()
