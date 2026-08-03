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
    "bt_runs", "bt_equity", "bt_positions", "bt_trades", "bt_sweep_equity", "bt_sweep_trades", "bt_sweep_positions"])
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


def test_experiments_json_is_kept_but_its_RESULTS_are_voided(src):
    """The premise this test used to assert was simply false. It said
    experiments.json holds "scheduling state, not results" — it holds BOTH: every
    finished entry carries an embedded `result` block, and the BASELINE's is the
    promotion yardstick. So the file was skipped whole and the void numbers kept
    reaching the Lab tab, the evaluator's experiment_lane packet section AND the
    promotion gate, by exactly the second route test_the_artifact_bridge_is_
    cleared_too exists to close.

    The file must survive (deleting it resets the queue and the weekly
    multiple-testing budget) with its results stripped."""
    assert "experiments.json" in src
    assert 'rm -f "$EXP"' not in src and "rm -f artifacts/bt/experiments.json" not in src
    assert "void" in src.lower()


def _void_step(src: str) -> str:
    """The experiments.json stanza, extracted so it can be RUN rather than
    grepped — a purge asserted only by string matching is a purge nobody has
    watched work."""
    start = src.index('EXP="artifacts/bt/experiments.json"')
    end = src.index("\nfi\n", start) + len("\nfi\n")
    return src[start:end]


def test_voiding_strips_results_but_preserves_the_SCHEDULE(src, tmp_path):
    """The behavioural test. Three things must hold at once, and they pull in
    opposite directions: void results must go, the weekly fire budget must NOT
    reset (it bounds multiple testing against one shared price history), and a
    queued-but-never-run candidate must survive to be tested."""
    import json
    import subprocess
    import sys

    (tmp_path / "artifacts" / "bt").mkdir(parents=True)
    doc = {"experiments": [
        {"kind": "baseline", "status": "success", "fired_at": "2026-08-03T22:00:00",
         "sweep_id": "a", "windows": {"period_a_start": "2023-07-26"},
         "result": {"period_a": {"cagr": 0.116}}},
        {"kind": "full_config", "status": "success", "fired_at": "2026-08-04T22:00:00",
         "sweep_id": "b", "windows": {}, "result": {"period_a": {"cagr": 0.09}}},
        {"kind": "full_config", "status": "running", "fired_at": "2026-08-05T22:00:00",
         "sweep_id": "c"},
        {"kind": "full_config", "status": "pending", "queued_at": "2026-08-05T10:00:00"},
    ]}
    path = tmp_path / "artifacts" / "bt" / "experiments.json"
    path.write_text(json.dumps(doc))

    r = subprocess.run(["bash", "-c", _void_step(src)], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    out = json.loads(path.read_text())["experiments"]
    assert not any("result" in e for e in out), "a void result survived the purge"
    assert not any("sweep_id" in e for e in out), "a pointer to deleted sweep rows survived"

    pending = [e for e in out if e["status"] == "pending"]
    assert len(pending) == 1, "a queued candidate that never ran is not void"

    # The STATUS must move too, not just the payload. The lane indexes
    # `e["result"]` directly when status == "success", so an entry left
    # "success" with its result stripped would KeyError on the next tick —
    # trading a misleading number for a crash. (Caught by mutation testing: the
    # assertions above all passed with the status change removed.)
    terminal = [e for e in out if e["status"] != "pending"]
    assert terminal and all(e["status"] == "void" for e in terminal)
    assert all(e.get("void_reason") for e in terminal), (
        "a voided entry must say WHY, or the next reader re-derives it wrongly")

    # The weekly budget is counted from kind + fired_at, so voiding must not
    # hand anyone free draws against the one shared history.
    sys.path.insert(0, os.path.join(ROOT, "services", "bt-scheduler"))
    from datetime import date

    from app.logic import baseline_is_valid, fired_this_week
    assert fired_this_week(out, date(2026, 8, 5)) == 2

    # And the baseline must now read as unusable, so the lane re-measures its
    # yardstick against the corrected corpus instead of gating on a void one.
    base = next(e for e in out if e["kind"] == "baseline")
    ok, _why = baseline_is_valid(base, None)
    assert ok is False


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


def test_the_epilogue_asserts_no_world_state(src):
    """It used to say "re-backfill SF1" and "sweeps will be refused with 422
    until SUE parity lands" — both true when written, both false within a day.
    A script that confidently restates a stale world is worse than one that says
    nothing, because it is read as current. Point at the checker instead."""
    # Only what the script PRINTS. The tail also contains a comment quoting the
    # removed text to explain why it went — matching that is the same
    # comment-vs-code trap the deploy-all tests hit.
    tail = "\n".join(ln for ln in src[src.index('echo "Done."'):].splitlines()
                      if ln.lstrip().startswith("echo"))
    for stale in ("422", "earnings_surprise", "re-backfill", "cannot compute"):
        assert stale not in tail, (
            f"the epilogue asserts {stale!r} — a state that can go out of date. "
            f"Reference scripts/deploy-all.sh --verify instead.")
    assert "deploy-all.sh --verify" in tail, (
        "the epilogue must point at something that reads the LIVE system")
