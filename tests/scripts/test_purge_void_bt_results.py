"""scripts/purge-void-bt-results.sh — a destructive script, so the guarantees
are asserted rather than assumed.

The dangerous failure is not "fails to delete" — it is deleting the source
corpus. bt_prices is ~35M rows and a multi-hour, rate-limited refetch; a stray
table name in the delete list turns a cleanup into a day of downtime. The
counterpart failure is a purge that misses the artifact bridge, leaving the same
void numbers reaching the evaluator's prompt by file instead of by SQL.
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "purge-void-bt-results.sh")


@pytest.fixture(scope="module")
def src() -> str:
    with open(SCRIPT) as f:
        return f.read()


def test_script_exists_and_is_executable():
    assert os.path.isfile(SCRIPT)
    assert os.access(SCRIPT, os.X_OK), "must be runnable without `bash scripts/...`"


def test_bash_syntax_is_valid():
    subprocess.run(["bash", "-n", SCRIPT], check=True)


# ── what must never be deleted ──────────────────────────────────────────────

@pytest.mark.parametrize("table", [
    "bt_prices", "bt_fundamentals", "bt_earnings", "bt_universe", "bt_data_runs"])
def test_source_corpus_is_never_in_the_delete_list(src, table):
    """~35M price rows and a rate-limited multi-hour refetch behind them."""
    result_line = re.search(r'^RESULT_TABLES="([^"]*)"', src, re.M)
    assert result_line, "RESULT_TABLES not found — did the script change shape?"
    assert table not in result_line.group(1).split()


def test_no_drop_or_truncate_cascade(src):
    """DELETE is recoverable-ish and scoped. DROP/TRUNCATE CASCADE can reach the
    corpus through a FK the author did not have in mind."""
    assert "DROP TABLE" not in src.upper()
    assert "CASCADE" not in src.upper()


def test_it_never_touches_the_live_database(src):
    """The live trading DB shares a host but nothing else. A purge script that
    can reach it is one typo from deleting orders and positions."""
    for forbidden in ("DATABASE_URL", "stocker-postgres", "docker-compose.yml "):
        assert forbidden not in src, forbidden
    assert "docker-compose.backtest.yml" in src


def test_it_never_passes_volumes_to_compose(src):
    """The standing rule: --volumes deletes the Postgres data volume."""
    assert "--volumes" not in src and " -v " not in src


# ── what must be deleted ────────────────────────────────────────────────────

@pytest.mark.parametrize("table", [
    "bt_sweeps", "bt_sweep_results", "bt_sweep_aggregates",
    "bt_runs", "bt_equity", "bt_positions", "bt_trades"])
def test_every_results_table_the_evaluator_can_read_is_purged(src, table):
    """These are exactly the tables in the evaluator's bt_sql_query allowlist.
    Missing one leaves a readable island of void evidence."""
    result_line = re.search(r'^RESULT_TABLES="([^"]*)"', src, re.M)
    assert table in result_line.group(1).split()


def test_purge_list_matches_the_evaluator_allowlist_exactly():
    """The two lists answer the same question — 'what can the evaluator see?' —
    so they must not drift. A table added to the allowlist without being added
    here becomes a permanent cache of void results."""
    import ast
    with open(os.path.join(ROOT, "services", "evaluator", "app", "tools.py")) as f:
        tools_src = f.read()
    m = re.search(r"^BT_TABLES\s*=\s*(\(.*?\))", tools_src, re.M | re.S)
    assert m, "BT_TABLES allowlist not found in evaluator/app/tools.py"
    allowlist = set(ast.literal_eval(m.group(1)))
    assert allowlist, "parsed an empty allowlist — the regex matched the wrong thing"
    with open(SCRIPT) as f:
        purged = set(re.search(r'^RESULT_TABLES="([^"]*)"', f.read(), re.M
                               ).group(1).split())
    assert allowlist == purged, (
        f"allowlist-only: {allowlist - purged}; purge-only: {purged - allowlist}")


def test_the_artifact_bridge_is_cleared_too(src):
    """The evaluator reads latest_sweep.json / promotion.json directly into its
    packet. Purging only the DB leaves the identical void numbers arriving by
    the other route."""
    assert "latest_sweep.json" in src
    assert "promotion.json" in src


def test_experiments_json_is_deliberately_kept(src):
    """It holds the lane's scheduling state (weekly counters, queued proposals),
    not results. Deleting it would silently reset the queue."""
    assert "kept artifacts/bt/experiments.json" in src


# ── safety behaviour ────────────────────────────────────────────────────────

def test_default_invocation_is_a_dry_run(src):
    assert "DRY RUN" in src
    assert re.search(r"CONFIRM=0", src), "confirmation must default to off"


def test_deletes_run_in_one_transaction(src):
    """A partial purge leaves the leaderboard pointing at sweeps whose results
    are gone — which reads as 'a sweep that found nothing', a worse lie than the
    one being removed."""
    assert "BEGIN;" in src and "COMMIT;" in src


def test_it_refuses_while_a_job_is_in_flight(src):
    """Same guard as up.sh/down.sh: deleting bt_sweeps under a running sweep
    destroys the job's own audit row mid-write."""
    assert "BLOCKED" in src
    assert "8031/sweeps/latest" in src and "8030/runs/latest" in src
    assert "--force" in src, "there must be a deliberate override"


def test_dry_run_does_not_reach_the_delete_path(src):
    """The exit must come BEFORE the purge block, not after."""
    dry_exit = src.index("DRY RUN")
    purge = src.index("purging results tables")
    assert dry_exit < purge


def test_it_explains_the_fail_closed_422_that_follows(src):
    """After purging, sweeps are refused by the coverage contract. Without this
    note the next operator reads 422 as a broken deploy and disables the gate."""
    assert "422" in src
    assert "earnings_surprise" in src
