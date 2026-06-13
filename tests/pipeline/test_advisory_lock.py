"""
Cross-process check-and-claim advisory-lock guard for the pipeline service.

The in-process ``_job_lock`` only serializes job starts WITHIN one process. If
the pipeline ever runs with >1 worker/replica, two processes could both pass the
``already_running`` / ``already_ran_today`` guard and both create a run row. Both
claim paths (``/jobs/run`` via ``_do_run_pipeline`` and ``/jobs/delta`` via
``start_delta_only``) therefore wrap their check-and-claim in a TRANSACTION-SCOPED
Postgres advisory lock (``pg_advisory_xact_lock``), which auto-releases at
commit/rollback — never a session lock to unlock by hand.

These tests drive the REAL claim functions against an in-memory fake engine that
records the advisory-lock keys, so the guard is verified without a live Postgres.
"""
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import main as pmain


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar


class _FakeConn:
    """Records advisory-lock keys and answers the few statements the claim paths
    issue. ``advisory_calls`` is shared across all transactions of an engine."""

    def __init__(self, advisory_calls: list):
        self.advisory_calls = advisory_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "pg_advisory_xact_lock" in sql:
            self.advisory_calls.append(params["key"] if params else None)
            return _FakeResult()
        if "SELECT MAX(date) FROM daily_prices" in sql:
            # No SPY data → both the force dup-count branch and the
            # already-ran-today branch are skipped; the claim proceeds to INSERT.
            return _FakeResult(scalar=None)
        # All INSERT/UPDATE statements (execution_traces, pipeline_runs,
        # delta_runs, sub-trace) just succeed.
        return _FakeResult()


class _FakeEngine:
    def __init__(self):
        self.advisory_calls: list = []

    def begin(self):
        return _FakeConn(self.advisory_calls)

    def connect(self):
        return _FakeConn(self.advisory_calls)


@pytest.fixture
def fake_engine(monkeypatch):
    eng = _FakeEngine()
    monkeypatch.setattr(pmain, "engine", eng, raising=False)
    # _create_pipeline_run / _create_sub_trace read these globals in Python.
    monkeypatch.setattr(pmain, "strategy",
                        SimpleNamespace(strategy_id="test_strat"), raising=False)
    monkeypatch.setattr(pmain, "config_hash", "deadbeef", raising=False)
    # Ensure no stale lock state leaks between tests.
    if pmain._job_lock.locked():
        pmain._job_lock.release()
    return eng


@pytest.mark.asyncio
async def test_do_run_pipeline_claim_takes_advisory_lock(fake_engine):
    """The /jobs/run check-and-claim takes pg_advisory_xact_lock with the run key."""
    try:
        result = await pmain._do_run_pipeline(triggered_by="manual")
        assert result["status"] == "started"
        assert fake_engine.advisory_calls == [pmain.PIPELINE_RUN_LOCK_KEY], (
            "the /jobs/run check-and-claim must take the cross-process advisory "
            "lock exactly once, with PIPELINE_RUN_LOCK_KEY"
        )
    finally:
        if pmain._job_lock.locked():
            pmain._job_lock.release()


@pytest.mark.asyncio
async def test_do_run_pipeline_check_and_claim_share_one_transaction(fake_engine):
    """The guard read and the INSERT must run in ONE transaction so the advisory
    lock spans both. Verified structurally: the check SELECT, any already-ran
    handling, and _create_pipeline_run all execute under a single engine.begin()
    that opens with the advisory lock."""
    src = inspect.getsource(pmain._do_run_pipeline)
    assert "pg_advisory_xact_lock" in src
    assert "_create_pipeline_run" in src
    # Match the actual SQL call, not the explanatory comment above the block.
    lock_pos = src.index('text("SELECT pg_advisory_xact_lock')
    claim_pos = src.index("_create_pipeline_run(conn")
    assert lock_pos < claim_pos, "lock must be taken before the claim"
    # No NEW transaction may be opened between taking the lock and creating the
    # run row — otherwise the xact lock would be released before the INSERT and
    # the check-and-claim would no longer be atomic across processes.
    between = src[lock_pos:claim_pos]
    assert "engine.begin()" not in between, (
        "the advisory lock (check) and _create_pipeline_run (claim) must share "
        "ONE engine.begin() transaction — no new transaction may open between them"
    )


@pytest.mark.asyncio
async def test_start_delta_only_claim_takes_advisory_lock(fake_engine):
    """The /jobs/delta check-and-claim takes pg_advisory_xact_lock with the delta key."""
    bt = MagicMock()
    bt.add_task = MagicMock()
    try:
        result = await pmain.start_delta_only(bt, manual=False)
        assert result["status"] == "started"
        assert fake_engine.advisory_calls == [pmain.PIPELINE_DELTA_LOCK_KEY], (
            "the /jobs/delta check-and-claim must take the cross-process advisory "
            "lock exactly once, with PIPELINE_DELTA_LOCK_KEY"
        )
    finally:
        if pmain._job_lock.locked():
            pmain._job_lock.release()


def test_distinct_keys_for_run_and_delta():
    """Run and delta claims use DISTINCT advisory keys (independent critical sections)."""
    assert pmain.PIPELINE_RUN_LOCK_KEY != pmain.PIPELINE_DELTA_LOCK_KEY


def test_claims_use_transaction_scoped_lock_not_session_lock():
    """Both claim paths must use the auto-released xact lock, never a session lock
    that would have to be manually unlocked (leak risk)."""
    for fn in (pmain._do_run_pipeline, pmain.start_delta_only):
        src = inspect.getsource(fn)
        assert "pg_advisory_xact_lock" in src, (
            f"{fn.__name__} must take a transaction-scoped advisory lock"
        )
        assert "pg_advisory_lock(" not in src, (
            f"{fn.__name__} must NOT use the session-scoped pg_advisory_lock"
        )
