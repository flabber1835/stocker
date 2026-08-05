"""Coverage validation for the as-traded price domain.

MOST OF THESE ARE ABOUT COST, not correctness. The first version of this report
was correct and unusable: it scanned a 35M-row corpus, hit the statement timeout
after ten minutes and returned a 500 — a diagnostic that fails in a way
indistinguishable from the fault it exists to diagnose, called from the deploy
pre-flight. So the fast path is asserted to stay fast, structurally.
"""
from __future__ import annotations

import ast
import datetime
import pathlib

import pytest

from app.raw_close_coverage import (
    SAMPLE_SESSIONS,
    SESSION_USABLE_THRESHOLD,
    STATEMENT_TIMEOUT_MS,
    build_report,
    normalized_input_hash,
)

MODULE = pathlib.Path(__file__).resolve().parents[2] / "services" / "bt-data" \
    / "app" / "raw_close_coverage.py"

D0 = datetime.date(2003, 1, 2)
D1 = datetime.date(2026, 8, 1)


class FakeConn:
    """Records every statement so the tests can assert what was NOT run."""

    def __init__(self, *, column=True, approx=35_000_000, bounds=(D0, D1),
                 per_session=None, exact_row=None, uncovered=(), rows=()):
        self.column, self.approx, self.bounds = column, approx, bounds
        self.per_session = per_session or {}
        self.exact_row, self.uncovered, self.rows = exact_row, list(uncovered), list(rows)
        self.executed: list[str] = []

    def exec_driver_sql(self, sql):
        self.executed.append(" ".join(str(sql).split()))
        return _R([])

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.executed.append(sql)
        if "information_schema.columns" in sql:
            return _R([(1,)] if self.column else [])
        if "reltuples" in sql:
            return _R([(self.approx,)])
        if "MIN(date), MAX(date)" in sql:
            return _R([self.bounds])
        if "WHERE date >= :target" in sql:
            t = params["target"]
            later = [d for d in sorted(self.per_session) if d >= t]
            return _R([(later[0],)] if later else [])
        if "WHERE date = :d" in sql:
            n, n_raw = self.per_session.get(params["d"], (0, 0))
            return _R([{"n": n, "n_raw": n_raw}])
        if "COUNT(DISTINCT ticker)" in sql:
            return _R([self.exact_row or {}])
        if "HAVING" in sql:
            return _R([{"ticker": t} for t in self.uncovered])
        if "ORDER BY date, ticker" in sql:
            return _R(self.rows)
        return _R([])


class _R:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        r = self.rows[0] if self.rows else None
        return r[0] if isinstance(r, tuple) else r

    def __iter__(self):
        return iter(self.rows)


def sessions(share, n=3000, count=60):
    """`count` sessions spread across the range, each at the given coverage."""
    out = {}
    span = (D1 - D0).days
    for k in range(count):
        d = D0 + datetime.timedelta(days=round(span * k / (count - 1)))
        out[d] = (n, int(n * share))
    return out


class TestTheFastPathStaysFast:

    def test_the_default_path_never_runs_a_full_table_aggregate(self):
        """The exact query is the one that timed out on the NAS. It must not be
        reachable without asking for it."""
        c = FakeConn(per_session=sessions(1.0))
        build_report(c)
        joined = " ".join(c.executed)
        assert "COUNT(DISTINCT ticker)" not in joined
        assert "GROUP BY ticker" not in joined
        assert "COUNT(*) AS rows_total" not in joined

    def test_row_counts_come_from_planner_statistics(self):
        c = FakeConn(per_session=sessions(1.0))
        rep = build_report(c)
        assert any("reltuples" in q for q in c.executed)
        assert rep.rows_total_estimate == 35_000_000
        assert rep.exact is False and rep.rows_total is None

    def test_every_statement_is_time_bounded(self):
        """A diagnostic that hangs cannot be told apart from the outage."""
        c = FakeConn(per_session=sessions(1.0))
        build_report(c)
        assert any("statement_timeout" in q for q in c.executed)
        assert STATEMENT_TIMEOUT_MS > 0

    def test_the_timeout_is_set_through_the_DRIVER_not_the_orm(self):
        """`SET` is a utility statement PostgreSQL cannot PREPARE, and the
        asyncpg dialect prepares everything — so issuing it as text() can fail
        on the driver rather than the database."""
        c = FakeConn(per_session=sessions(1.0))
        build_report(c)
        assert any("statement_timeout" in q for q in c.executed)
        assert hasattr(c, "exec_driver_sql")

    def test_a_failure_to_set_the_timeout_does_not_kill_the_report(self):
        """The timeout is a safety margin on queries that are already
        index-bounded. Losing the margin is worth far less than losing the
        diagnostic — but it is RECORDED, since it changes how long a bad plan
        can hang."""
        class NoSet(FakeConn):
            def exec_driver_sql(self, sql):
                raise RuntimeError("cannot PREPARE a utility statement")
        rep = build_report(NoSet(per_session=sessions(1.0)))
        assert rep.operational is True
        assert any("statement_timeout could not be set" in n for n in rep.notes)

    def test_the_sample_is_bounded_and_spread(self):
        c = FakeConn(per_session=sessions(1.0))
        rep = build_report(c, sample_sessions=10)
        assert 0 < len(rep.sampled) <= 10
        assert rep.sampled[0]["date"] < rep.sampled[-1]["date"], "not spread"

    def test_exact_mode_is_opt_in_and_does_run_the_scan(self):
        c = FakeConn(per_session=sessions(1.0),
                     exact_row={"rows_total": 35_000_000,
                                "rows_with_raw": 35_000_000,
                                "first_covered": D0, "last_covered": D1,
                                "tickers_total": 21_000})
        rep = build_report(c, exact=True)
        assert rep.exact is True and rep.rows_total == 35_000_000
        assert any("COUNT(DISTINCT ticker)" in q for q in c.executed)


class TestTheOperationalGate:

    def test_a_missing_column_is_reported_and_short_circuits(self):
        c = FakeConn(column=False)
        rep = build_report(c)
        assert rep.column_present is False and rep.operational is False
        assert any("init_bt.sql" in n for n in rep.notes)
        assert not rep.sampled, "nothing should be sampled without the column"

    def test_an_unpopulated_column_is_not_operational(self):
        """The state right after the ALTER and before the replay."""
        rep = build_report(FakeConn(per_session=sessions(0.0)))
        assert rep.column_present is True
        assert rep.coverage == 0.0 and rep.operational is False

    def test_a_fully_populated_corpus_is_operational(self):
        rep = build_report(FakeConn(per_session=sessions(1.0)))
        assert rep.coverage == 1.0 and rep.operational is True

    def test_ONE_unusable_SAMPLED_session_blocks_an_otherwise_full_corpus(self):
        """A run cannot mark its book on a day most securities have no
        as-traded price for, however good the average looks.

        The bad session is placed on the FIRST date, which the sampler always
        probes. Placing it on an arbitrary date made this pass or fail depending
        on whether the sample happened to land there — see the limitation test
        below, which states that honestly instead of hiding it in a fixture.
        """
        s = sessions(1.0)
        s[min(s)] = (3000, 10)
        rep = build_report(FakeConn(per_session=s))
        assert rep.operational is False
        assert len(rep.sessions_unusable) == 1

    def test_an_ISOLATED_unsampled_bad_session_is_NOT_detected(self):
        """The honest limit of the fast path, asserted so nobody mistakes it
        for exhaustive.

        Sampling finds contiguous gaps — which is what a partial backfill
        produces, since it writes chunk by chunk — and cannot find one bad day
        between two probes. That residual case is already handled downstream:
        the engine refuses to trade a security with no print, and `exact=1`
        exists for a caller who needs certainty.
        """
        s = sessions(1.0, count=4000)          # far denser than the sample
        probed = {p["date"] for p in build_report(FakeConn(per_session=s)).sampled}
        victim = next(d for d in sorted(s) if str(d) not in probed)
        s[victim] = (3000, 0)
        rep = build_report(FakeConn(per_session=s))
        assert rep.operational is True, (
            "if this now fails, sampling got denser and the limitation "
            "narrowed — update the claim rather than deleting the test")
        assert str(victim) not in rep.sessions_unusable

    def test_a_HALF_finished_backfill_is_caught_by_the_spread(self):
        """The realistic partial state: the replay stopped part-way, so early
        dates are covered and later ones are not. Sampling across the range is
        what makes this visible without a full scan."""
        s = sessions(1.0)
        for d in sorted(s)[30:]:
            s[d] = (3000, 0)
        rep = build_report(FakeConn(per_session=s))
        assert rep.operational is False
        assert rep.sessions_unusable, "the empty half was not detected"

    def test_no_sample_at_all_is_not_operational(self):
        """An unknown must never read as full coverage."""
        rep = build_report(FakeConn(per_session={}))
        assert rep.coverage == 0.0 and rep.operational is False

    def test_the_session_threshold_is_a_real_number(self):
        assert 0.0 < SESSION_USABLE_THRESHOLD <= 1.0
        assert SAMPLE_SESSIONS >= 10


class TestTheInputHash:

    def rows(self):
        return [{"ticker": "AAA", "date": "2020-01-02", "open": 49.0,
                 "close": 50.0, "close_unadjusted": 100.0, "volume": 1e6}]

    def test_it_changes_when_a_price_changes(self):
        r2 = self.rows()
        r2[0]["close_unadjusted"] = 100.01
        assert normalized_input_hash(FakeConn(rows=self.rows()), "a", "b") \
            != normalized_input_hash(FakeConn(rows=r2), "a", "b")

    def test_it_does_NOT_change_on_a_rewrite_with_identical_values(self):
        """A row rewritten with the same numbers is not a data change, and a
        hash that moved on it would train everyone to ignore it."""
        r2 = self.rows()
        r2[0]["close_unadjusted"] = 100.0000000001    # below the 6dp rounding
        assert normalized_input_hash(FakeConn(rows=self.rows()), "a", "b") \
            == normalized_input_hash(FakeConn(rows=r2), "a", "b")

    def test_it_is_not_computed_unless_asked_for(self):
        """It reads every row of a 35M-row corpus."""
        rep = build_report(FakeConn(per_session=sessions(1.0)))
        assert rep.normalized_input_hash is None


def test_the_report_says_when_it_is_sampling():
    """A number nobody knows is an estimate gets treated as exact."""
    rep = build_report(FakeConn(per_session=sessions(1.0)))
    d = rep.to_dict()
    assert d["exact"] is False
    assert any("SAMPLED" in n for n in d["notes"])
    assert d["sampled_sessions"], "the sampled dates must be visible"


def test_the_expensive_queries_are_confined_to_the_exact_branch():
    """Checked over the AST rather than the text: the module docstring names
    every expensive construct while explaining why they are avoided, so a string
    search would match the explanation."""
    tree = ast.parse(MODULE.read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_report")
    exact_only = {"_EXACT_SQL", "_UNCOVERED_TICKERS_SQL"}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id in exact_only:
            parents = [p for p in ast.walk(fn)
                       if isinstance(p, ast.If) and node in ast.walk(p)]
            assert parents, f"{node.id} is used outside any conditional"
