"""The backtester's Wealth Core wiring: domain mapping and the refusal.

These tests are about the ADAPTER, not the strategy. The strategy is pinned by
tests/wealth_core/test_golden_fixture.py; what can go wrong here is that real
Sharadar columns are attached to the wrong canonical domain, which produces a
complete backtest of something else.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.wealth_core_replay import (  # noqa: E402
    CAVEATS,
    MIN_RAW_CLOSE_COVERAGE,
    RawPriceDomainUnavailable,
    assert_raw_price_domain,
    load_bars,
    load_identity,
    load_meta,
    split_ratio_from_domains,
)

MODULE = pathlib.Path(__file__).resolve().parents[2] / \
    "services" / "backtester" / "app" / "wealth_core_replay.py"


class FakeConn:
    """Just enough of a connection to drive the loaders. A real DB would make
    these tests a bt-postgres integration suite, and the thing under test is the
    column-to-domain mapping, which needs no server."""

    def __init__(self, rows_by_sql):
        self.rows_by_sql = rows_by_sql
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        key = next(k for k in self.rows_by_sql if k in str(stmt))
        return _Result(self.rows_by_sql[key])


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


# ── the refusal ─────────────────────────────────────────────────────────────

class TestItRefusesWithoutTheAsTradedDomain:

    def test_an_unbackfilled_corpus_is_refused_not_approximated(self):
        conn = FakeConn({"COUNT(close_unadjusted)": [{"n": 1000, "n_raw": 0}]})
        with pytest.raises(RawPriceDomainUnavailable) as e:
            assert_raw_price_domain(conn, "2020-01-01", "2021-01-01")
        assert "closeunadj" in str(e.value), "the error must name the remedy"

    def test_a_partly_backfilled_corpus_is_also_refused(self):
        conn = FakeConn({"COUNT(close_unadjusted)": [{"n": 1000, "n_raw": 500}]})
        with pytest.raises(RawPriceDomainUnavailable):
            assert_raw_price_domain(conn, "2020-01-01", "2021-01-01")

    def test_ordinary_vendor_gaps_are_tolerated(self):
        """A handful of missing prints is what "no print, no fill" is for. Only
        a corpus that is mostly NULL is a deployment state."""
        conn = FakeConn({"COUNT(close_unadjusted)": [{"n": 1000, "n_raw": 995}]})
        assert assert_raw_price_domain(conn, "a", "b") == pytest.approx(0.995)

    def test_an_empty_range_is_refused_rather_than_run_as_zero_sessions(self):
        conn = FakeConn({"COUNT(close_unadjusted)": [{"n": 0, "n_raw": 0}]})
        with pytest.raises(RawPriceDomainUnavailable):
            assert_raw_price_domain(conn, "a", "b")

    def test_the_floor_is_a_real_threshold(self):
        assert 0.0 < MIN_RAW_CLOSE_COVERAGE <= 1.0


# ── the domain mapping ──────────────────────────────────────────────────────

class TestTheDomainMapping:

    class Resolver:
        unresolved = {}

        @staticmethod
        def resolve(ticker, _session):
            return f"P:{ticker}"

    def rows(self):
        # A 2:1 split between the two sessions. The corpus is a snapshot under
        # the vendor's CURRENT adjustment, so the pre-split row carries
        # closeunadj/close = 2 and the post-split row carries 1 — the adjustment
        # factor FALLS through a forward split.
        return [
            {"ticker": "AAA", "date": "2020-01-02", "open": 49.0, "close": 50.0,
             "close_unadjusted": 100.0, "volume": 1_000_000.0},
            {"ticker": "AAA", "date": "2020-01-03", "open": 50.0, "close": 51.0,
             "close_unadjusted": 51.0, "volume": 1_000_000.0},
        ]

    def test_the_mark_is_the_as_traded_close_never_the_adjusted_one(self):
        bars = load_bars(FakeConn({"close_unadjusted": self.rows()}), "a", "b",
                         identity=self.Resolver())
        first = bars["2020-01-02"][0]
        assert first.raw_close == 100.0, (
            "raw_close must be SEP.closeunadj. Taking SEP.close would mark a "
            "post-split holding at the adjusted level and misweight it forever")

    def test_the_open_is_rescaled_into_the_as_traded_domain(self):
        bars = load_bars(FakeConn({"close_unadjusted": self.rows()}), "a", "b",
                         identity=self.Resolver())
        first = bars["2020-01-02"][0]
        # 49 x (100/50) = 98: SEP's open is split-adjusted like its close, so it
        # has to be scaled or orders fill in a different domain than they mark.
        assert first.raw_open == pytest.approx(98.0)

    def test_a_split_is_recovered_from_the_two_domains_diverging(self):
        bars = load_bars(FakeConn({"close_unadjusted": self.rows()}), "a", "b",
                         identity=self.Resolver())
        assert bars["2020-01-02"][0].split_ratio == 1.0     # no prior session
        assert bars["2020-01-03"][0].split_ratio == 2.0

    def test_the_total_return_series_is_never_read(self):
        """`closeadj` is dividend-reinvested. Reading it into ANY domain is
        wrong, so the safest guarantee is that the module never names it.

        Checked over the module's CODE with comments and docstrings stripped —
        the prose above explains exactly why closeadj is dangerous, and a naive
        string search would match that explanation and fail.

        ORDINARY STRING CONSTANTS ARE NOT STRIPPED, and deliberately: the SQL
        queries are string constants, so a query that selected the total-return
        column has to be caught here. The cost is that no other string in the
        module may name it either — which is why the dividend caveat describes
        the column instead of naming it. That is the right way round: a caveat
        losing a column name is cheap, a SQL guard losing its teeth is not.
        """
        tree = ast.parse(MODULE.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                node.value.value = ""
        code = ast.unparse(tree)
        assert "closeadj" not in code
        assert "adjusted_close" not in code


class TestSplitRecovery:

    @pytest.mark.parametrize("before_adj,before_raw,adj,raw,expected", [
        (50.0, 100.0, 51.0, 51.0, 2.0),        # 2:1
        (50.0, 150.0, 51.0, 51.0, 3.0),        # 3:1
        (150.0, 50.0, 51.0, 51.0, 1.0 / 3.0),  # 1:3 reverse
        (50.0, 100.0, 51.0, 102.0, 1.0),       # no event
        (None, None, 51.0, 51.0, 1.0),         # first session
        (50.0, 100.0, 51.0, None, 1.0),        # missing raw -> no event
    ])
    def test_ratios(self, before_adj, before_raw, adj, raw, expected):
        assert split_ratio_from_domains(before_adj, before_raw, adj, raw) == \
            pytest.approx(expected)

    def test_vendor_rounding_never_becomes_a_fractional_split(self):
        """A 1.003 ratio is rounding, not a corporate action. Reporting it as a
        split would multiply a share count by 1.003 and leave a position nobody
        can reconcile against the broker."""
        assert split_ratio_from_domains(50.0, 100.0, 51.0, 102.3) == 1.0


class TestMeta:

    def test_reference_data_takes_the_latest_NON_NULL_label(self):
        """Not "the newest snapshot" — a fresh universe snapshot writes NULL
        categories that a later fetch backfills, so keying on the newest
        snapshot goes blind the first time one lands."""
        conn = FakeConn({"bt_universe": [
            {"ticker": "AAA", "category": "Domestic Common Stock",
             "permaticker": 123, "related_tickers": "AAA AAAB",
             "first_price_date": "2010-01-04"}]})
        # Keyed on the PERMANENT id, not the ticker: meta is now one row per
        # security rather than one per symbol, which is what stops a rename
        # moving the issuer key and a reuse merging two companies.
        meta = load_meta(conn, as_of="2020-12-31")["P:123"]
        assert meta.security_id == "P:123"
        assert meta.ticker == "AAA", "the ticker survives as the display label"
        assert meta.category == "Domestic Common Stock"
        assert meta.permaticker == "123"
        assert meta.related_tickers == ("AAA", "AAAB")
        key, source = meta.issuer_key()
        assert key == "AAA|AAAB" and source == "RELATEDTICKERS"

    def test_a_security_with_NO_permaticker_is_excluded_rather_than_guessed(self):
        """Identity cannot be established, and the alternative is inventing
        one. Same rule as strict issuer identity: a guess merges unrelated
        companies and splits related ones, in opposite directions, silently."""
        conn = FakeConn({"bt_universe": [
            {"ticker": "AAA", "category": "Domestic Common Stock",
             "permaticker": None, "related_tickers": None,
             "first_price_date": "2010-01-04"}]})
        assert load_meta(conn, as_of="2020-12-31") == {}

    def test_decision_metadata_is_session_effective_but_identity_uses_intervals(self):
        rows = [{"ticker": "AAA", "category": "Domestic Common Stock",
                 "permaticker": 123, "related_tickers": "AAA",
                 "first_price_date": "2010-01-04",
                 "last_price_date": "2020-12-31"}]
        meta_conn = FakeConn({"bt_universe": rows})
        load_meta(meta_conn, as_of="2020-12-31")
        meta_sql, meta_params = meta_conn.calls[-1]
        assert "snapshot_date <= :as_of" in meta_sql
        assert meta_params == {"as_of": "2020-12-31"}

        identity_conn = FakeConn({"bt_universe": rows})
        load_identity(identity_conn, as_of="2020-12-31")
        identity_sql, identity_params = identity_conn.calls[-1]
        assert "snapshot_date <= :as_of" not in identity_sql
        assert "first_price_date" in identity_sql
        assert identity_params is None

        replay = MODULE.read_text()
        body = replay[replay.index("def run_wealth_core_replay"):]
        assert "load_meta_timeline(conn, sessions=sessions)" in body
        assert "metadata_timeline=metadata_timeline" in body
        assert "load_meta(conn, as_of=req.start_date)" not in body


def test_the_unmodelled_parts_travel_with_the_result():
    """Caveats are part of the output, not the documentation. This result feeds
    an evaluator that compares configs, and an unmodelled dividend stream reads
    as a strategy difference when it is a data one.

    The caveats are now SOURCE-DEPENDENT: splits and terminal actions mean
    different things depending on whether SHARADAR/ACTIONS drove the run, so
    those two moved into the per-source sets. What is asserted here is that the
    UNION still covers every topic — a caveat that fell out of both sets during
    the split would otherwise be invisible.
    """
    from app.wealth_core_replay import ACTIONS_CAVEATS, DERIVED_SPLIT_CAVEATS

    always = " ".join(CAVEATS).lower()
    assert "ticker" in always, (
        "ticker identity holds on BOTH paths, so it belongs in the "
        "unconditional set")

    for source in (DERIVED_SPLIT_CAVEATS, ACTIONS_CAVEATS):
        joined = " ".join(CAVEATS + source).lower()
        for topic in ("dividend", "split", "terminal", "ticker"):
            assert topic in joined, f"{topic!r} is uncovered on one source path"


class TestTheBenchmarkIsSeparate:
    """The total-return series has exactly one legitimate use — a hurdle — and it
    lives in its own module so the loader's "never names it" guard stays
    absolute. A guard that permits one blessed exception is not checkable."""

    BENCH = MODULE.parent / "wealth_core_benchmark.py"

    def test_the_benchmark_module_exists_and_reads_the_total_return_series(self):
        src = self.BENCH.read_text()
        assert "adjusted_close" in src
        assert "bt_prices" in src

    def test_it_reads_NOTHING_but_the_benchmark(self):
        """It must not become a second corpus reader. The strategy's tables and
        price domains belong to the loader alone."""
        import ast
        tree = ast.parse(self.BENCH.read_text())
        sql = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "SELECT" in n.value.upper()]
        assert sql, "no SQL found — the scan is not looking at anything"
        for stmt in sql:
            for banned in ("bt_universe", "bt_actions", "bt_fundamentals",
                           "close_unadjusted", "closeunadj"):
                assert banned not in stmt, f"{banned!r} does not belong here: {stmt!r}"
            assert "ticker = :ticker" in stmt, (
                "the benchmark query must be scoped to ONE ticker; an unscoped "
                "bt_prices read is a corpus loader by another name")

    def test_the_image_carries_it(self):
        df = (MODULE.parents[2] / "bt-engine" / "Dockerfile").read_text()
        assert "services/backtester/app/wealth_core_benchmark.py ./app/live/" in df
