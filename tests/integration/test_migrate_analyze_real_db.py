"""db-migrator's ANALYZE step, run against a real migrated Postgres.

Every deploy blocks on this container: api and scheduler declare
`depends_on: db-migrator: service_completed_successfully`, so whatever is slow
here delays the whole stack. It used to issue a BARE `ANALYZE`, which walks
every table in the database — including daily_prices (millions of rows) and
live_positions (a full book snapshot per sync run), none of which the
plan-sensitive screener query touches. That is why a no-op deploy still took
minutes.

These run the REAL embedded block from migrate.sh (extracted, not
reimplemented) so the shipped script is what is exercised.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATE_SH = ROOT / "services" / "db-migrator" / "migrate.sh"


def _analyze_block() -> str:
    """The python heredoc that performs the ANALYZE, straight out of the shipped
    script — so this test cannot pass against a stale copy."""
    src = MIGRATE_SH.read_text()
    start = src.index("import os, time")
    end = src.index("\nEOF", start)
    return src[start:end]


def test_analyze_is_scoped_not_database_wide():
    """A bare `ANALYZE` is the regression: it must never come back."""
    src = MIGRATE_SH.read_text()
    assert not re.search(r'cur\.execute\(\s*["\']ANALYZE["\']\s*\)', src), \
        "bare database-wide ANALYZE reintroduced — it walks every table"
    assert 'ANALYZE "' in src, "expected a per-table ANALYZE"
    assert "to_regclass" in src, "missing the relation guard for absent tables"


def test_analyze_runs_against_a_real_migrated_database(migrated_dsn):
    """Executes the shipped block end-to-end: every listed table must either be
    analyzed or reported absent, and the process must exit clean."""
    env = dict(os.environ, DATABASE_URL=migrated_dsn)
    res = subprocess.run([sys.executable, "-c", _analyze_block()],
                         capture_output=True, text=True, env=env, timeout=180)
    assert res.returncode == 0, f"ANALYZE block failed:\n{res.stderr[-2000:]}"
    assert "ANALYZE complete" in res.stdout, res.stdout
    # the screener's plan-sensitive tables are the whole point of the step
    for table in ("rankings", "ranking_runs", "fundamentals",
                  "universe_tickers", "vetter_decisions"):
        assert table in res.stdout, f"{table} was neither analyzed nor reported absent"


def test_absent_tables_do_not_fail_the_deploy(migrated_dsn):
    """A fresh or partial database must not turn a stats refresh into a failed
    deploy — api and scheduler are gated on this container completing."""
    env = dict(os.environ, DATABASE_URL=migrated_dsn,
               ANALYZE_TABLES="rankings,no_such_table_here")
    res = subprocess.run([sys.executable, "-c", _analyze_block()],
                         capture_output=True, text=True, env=env, timeout=120)
    assert res.returncode == 0, res.stderr[-1000:]
    assert "absent: no_such_table_here" in res.stdout, res.stdout
    assert "rankings" in res.stdout


def test_daily_prices_is_not_analyzed_by_default(migrated_dsn):
    """The big tables are exactly what made the step slow, and no dashboard
    query the step exists for joins them."""
    env = dict(os.environ, DATABASE_URL=migrated_dsn)
    env.pop("ANALYZE_TABLES", None)
    res = subprocess.run([sys.executable, "-c", _analyze_block()],
                         capture_output=True, text=True, env=env, timeout=180)
    assert res.returncode == 0
    assert "daily_prices" not in res.stdout, "daily_prices back in the default set"
    assert "live_positions" not in res.stdout, "live_positions back in the default set"


@pytest.mark.parametrize("script_check", [
    ("ANALYZE_SKIP", "an escape hatch to skip the step entirely"),
    ("TOTAL", "a total elapsed line"),
    ("took $", "per-phase timings"),
])
def test_script_is_measurable(script_check):
    """The original had no timestamps at all, so 'db-migrator is slow' could not
    be attributed to a phase — the reason this was diagnosed by guesswork."""
    token, why = script_check
    assert token in MIGRATE_SH.read_text(), f"missing {why}"
