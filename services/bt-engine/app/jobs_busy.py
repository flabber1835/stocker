"""Mutual exclusion between the three corpus-loading job types on bt-engine.

`POST /jobs/run`, `POST /sweeps/run` and `POST /wealth-core/jobs/run` each load
the whole corpus for their own date range. Two resident at once is the memory
profile that gets the container OOM-killed — and the container's `OOMKilled`
flag does NOT reliably record that, so the job rows read `RESTART_ABORTED` and
an environment failure becomes indistinguishable from a strategy failure.

**The check has to be symmetric, and it was not.** Wealth Core refused to start
beside a backtest or a sweep. Neither of those looked at Wealth Core, and
`/jobs/run` and `/sweeps/run` did not look at each other either — each queried
only its OWN table. One of six ordered pairs was actually defended.

That asymmetry is invisible while one job type runs at a time, which is how it
survived: it took the nightly sweep firing at 02:00 UTC into a Wealth Core
rehearsal started at 00:55 to expose it, and it cost both jobs and four hours
(2026-08-09). The refusal comment in `wealth_core_api` had described this exact
failure since it was written; only one side of it was enforced.

Generalises the crash-brake rule in CLAUDE.md: a constraint between two parties
must be enforced from BOTH ends, not from whichever end was written last.
"""
from __future__ import annotations

from sqlalchemy import text

#: Labelled so a 409 can NAME what is in the way. Diagnosing the collision above
#: took a cross-reference of three tables against `dmesg` precisely because the
#: refusal messages said "a sweep is already running" without saying which job
#: the caller had actually lost to.
BACKTEST_RUN = "backtest run"
SWEEP = "sweep"
WEALTH_CORE_RUN = "Wealth Core run"

#: Any ONE running job disqualifies a new one, so `LIMIT 1` after the UNION is
#: sufficient — this asks "is anything running", not "what is running".
_BUSY_SQL = text(
    "SELECT kind FROM ("
    f"  SELECT '{BACKTEST_RUN}' AS kind FROM bt_runs WHERE status='running'"
    "  UNION ALL"
    f"  SELECT '{SWEEP}' AS kind FROM bt_sweeps WHERE status='running'"
    "  UNION ALL"
    f"  SELECT '{WEALTH_CORE_RUN}' AS kind FROM bt_wealth_core_runs"
    "   WHERE status='running'"
    ") AS running LIMIT 1"
)


async def running_job_kind(conn) -> str | None:
    """Which corpus-loading job is already running on this engine, if any."""
    row = (await conn.execute(_BUSY_SQL)).first()
    return row[0] if row else None


def busy_detail(kind: str) -> str:
    """The 409 body. Says what is running and why this is a refusal, not a queue."""
    return (
        f"a {kind} is already in progress on this engine. Refused rather than "
        "queued: each job loads the whole corpus for its range, two do not fit "
        "in the container together, and the resulting OOM is recorded as a "
        "strategy failure rather than an environment failure."
    )
