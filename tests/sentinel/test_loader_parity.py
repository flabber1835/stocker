"""Sentinel's corpus path and the CANONICAL Wealth Core data path agree, bar for bar.

The engine is imported intact, so the certified thing is `run_sessions`. What is
NOT certified is what gets handed to it, and Sentinel now assembles that from its
OWN tables through its OWN normaliser, while the canonical path
(`services/backtester/app/wealth_core_replay.py`) assembles it from the Sharadar
corpus in bt-postgres. Two roads to one input type is exactly where a silent
divergence lives: every value on a `VendorBar` is plausible when wrong.

So both paths are driven from the SAME raw vendor rows and the resulting
`VendorBar`s are compared field by field:

```text
SEP rows + ACTIONS
   |
   +-- sentinel:  normalise_sep_rows -> write_bars -> loader.load_window
   |
   +-- canonical: bt-data map_sep_row -> wealth_core_replay.load_bars
```

The SQL is deliberately not what is compared — the canonical loader is driven
through a stand-in cursor. The mapping is the thing: which domain each price and
volume is in, whether the ratio was inverted, where the dividend came from, and
whether the bar is tradeable.

WHY THIS TEST EXISTS NOW. Before review #4 it could not have passed and could not
have been written honestly: Sentinel's ingest never passed ACTIONS to its
normaliser, so every `dividend_per_share` on this side was 0.0 while the
canonical side carried the real distribution. The parity is only a meaningful
claim once both sides read the same authority.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import loader  # noqa: E402
from sentinel.feed import domains  # noqa: E402
from sentinel.feed import store as S  # noqa: E402
from stock_strategy_shared.wealth_core.sharadar_domains import (  # noqa: E402
    raw_compatible_volume,
)
from tools import corpus_parity as CP  # noqa: E402

SESSIONS = ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06"]
START, END = SESSIONS[0], SESSIONS[-1]


def canonical():
    sys.path.insert(0, str(ROOT / "services" / "backtester"))
    try:
        from app import wealth_core_replay as bt
        return bt
    except Exception:                                       # noqa: BLE001
        pytest.skip("backtester module not importable in this environment")


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in ("sentinel_action_generation_events",
                  "sentinel_action_observations", "sentinel_action_generations",
                  "sentinel_bars", "sentinel_actions", "sentinel_universe",
                  "feed_ingest_runs", "sentinel_ingest_rejections"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    yield c
    c.close()


# ── the shared inputs ────────────────────────────────────────────────────────

def sep_rows():
    """One ordinary security, one that splits 3:2, one with a zero-volume day.

    The zero-volume bar is not filler: it is the difference between a book that
    can fill an order and one that cannot, and it is invisible in every field
    except `tradeable`.
    """
    rows = []
    for i, d in enumerate(SESSIONS):
        rows.append({"date": d, "ticker": "AAA", "close": 100.0 + i,
                     "closeunadj": 100.0 + i, "open": 99.0 + i,
                     "volume": 1_000_000.0})
        # BBB trades at 150 and splits 3:2 on the third session, so the
        # adjusted series is rebased and the as-traded price halves-and-a-bit.
        after = i >= 2
        adj = 100.0
        raw = 100.0 if after else 150.0
        rows.append({"date": d, "ticker": "BBB", "close": adj,
                     "closeunadj": raw, "open": raw * 0.99,
                     "volume": 0.0 if i == 1 else 2_000_000.0})
    return rows


def bt_rows():
    """The same rows after bt-data's SEP provider-boundary mapping.

    `bt_prices.volume` is canonical raw-compatible shares, not the vendor's
    split-adjusted SEP field. Keeping that transformation explicit here makes
    this stand-in cursor model what the real backtester database stores.
    """
    return [
        {"date": r["date"], "ticker": r["ticker"], "open": r["open"],
         "close": r["close"], "close_unadjusted": r["closeunadj"],
         "volume": raw_compatible_volume(
             r["close"], r["closeunadj"], r["volume"])}
        for r in sep_rows()
    ]


SPLITS = {("BBB", "2024-06-05"): 1.5}
DIVIDENDS = {("AAA", "2024-06-04"): 0.37}
IDENTITY = {"AAA": "101", "BBB": "202"}


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return iter(self._rows)


class _FakeConn:
    """Stands in for the bt-postgres connection.

    The SQL is not what parity is about — both sides read the same vendor
    columns — and requiring a 35M-row corpus to compare a mapping would make
    this test something nobody runs.
    """

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **kw):
        return _FakeResult(self._rows)


def sentinel_normalised_bars():
    report = domains.NormalisationReport()
    return list(domains.normalise_sep_rows(
        sep_rows(), resolve_identity=lambda t, s: IDENTITY.get(str(t)),
        authoritative_splits=SPLITS, dividends=DIVIDENDS, report=report))


def sentinel_bars(conn):
    S.write_bars(conn, sentinel_normalised_bars())
    return loader.load_window(conn, start=START, end=END).bars_by_session


def canonical_bars():
    bt = canonical()
    # Production shape: Sentinel receives the bare Sharadar permaticker while
    # the retained canonical resolver owns its explicit P: namespace.  The old
    # fixture pre-prefixed both sides and therefore hid the real parity defect.
    identity = bt.IdentityResolver([
        {"permaticker": permaticker, "ticker": ticker,
         "first_price_date": START, "last_price_date": END}
        for ticker, permaticker in IDENTITY.items()
    ])
    return bt.load_bars(_FakeConn(bt_rows()), START, END,
                        authoritative_splits=SPLITS, dividends=DIVIDENDS,
                        identity=identity)


def by_key(bars_by_session, *, source):
    return {(s, CP.comparison_security_id(b.security_id, source=source)): b
            for s, bars in bars_by_session.items() for b in bars}


# ── 1. the whole bar, field by field ─────────────────────────────────────────

class TestTheTwoPathsProduceTheSameBars:

    def test_the_fixture_uses_the_two_production_identity_encodings(self):
        mine = {}
        for normalised in sentinel_normalised_bars():
            bar = normalised.vendor
            mine.setdefault(bar.session, []).append(bar)
        theirs = canonical_bars()

        assert {b.security_id for bars in mine.values() for b in bars} == {
            "101", "202"}
        assert {b.security_id for bars in theirs.values() for b in bars} == {
            "P:101", "P:202"}
        assert CP.compare(mine, theirs, window=(START, END)).agrees

    def test_the_SAME_securities_on_the_SAME_sessions(self, conn):
        assert set(by_key(sentinel_bars(conn), source="sentinel")) == set(
            by_key(canonical_bars(), source="canonical"))

    @pytest.mark.parametrize("field", [
        "raw_close", "raw_open", "volume", "split_ratio",
        "dividend_per_share", "ticker", "tradeable",
        "unresolved_corporate_action"])
    def test_every_field_agrees(self, conn, field):
        mine = by_key(sentinel_bars(conn), source="sentinel")
        theirs = by_key(canonical_bars(), source="canonical")
        bad = {k: (getattr(mine[k], field), getattr(theirs[k], field))
               for k in sorted(mine)
               if getattr(mine[k], field) != getattr(theirs[k], field)}
        assert not bad, f"{field} differs (sentinel, canonical): {bad}"


# ── 2. the fields most likely to be wrong, asserted on their own ─────────────

class TestTheValuesThatArePlausibleWhenWrong:

    def test_the_split_is_1_point_5_on_BOTH_sides(self, conn):
        k = ("2024-06-05", "P:202")
        assert by_key(sentinel_bars(conn), source="sentinel")[
            k].split_ratio == pytest.approx(1.5)
        assert by_key(canonical_bars(), source="canonical")[
            k].split_ratio == pytest.approx(1.5)

    def test_split_affected_liquidity_is_in_the_same_domain_on_BOTH_sides(self, conn):
        k = ("2024-06-03", "P:202")
        mine = by_key(sentinel_bars(conn), source="sentinel")
        theirs = by_key(canonical_bars(), source="canonical")
        # close=100, raw=150, reported adjusted volume=2m -> raw volume=1.333m.
        assert mine[k].volume == pytest.approx(2_000_000 * 100 / 150)
        assert mine[k].volume == pytest.approx(theirs[k].volume)
        assert mine[k].raw_close * mine[k].volume == pytest.approx(200_000_000)

    def test_the_dividend_lands_on_the_same_session_on_BOTH_sides(self, conn):
        mine = by_key(sentinel_bars(conn), source="sentinel")
        theirs = by_key(canonical_bars(), source="canonical")
        paid = {k for k, b in mine.items() if b.dividend_per_share}
        assert paid == {("2024-06-04", "P:101")}
        assert paid == {k for k, b in theirs.items() if b.dividend_per_share}

    def test_a_ZERO_VOLUME_bar_is_NOT_tradeable_on_either_side(self, conn):
        """The one field with no visible consequence until an order is filled.
        A bar with no volume is a security nobody traded that day; treating it
        as fillable executes against a market that did not exist."""
        k = ("2024-06-04", "P:202")
        assert by_key(sentinel_bars(conn), source="sentinel")[
            k].tradeable is False
        assert by_key(canonical_bars(), source="canonical")[
            k].tradeable is False

    def test_a_NORMAL_bar_is_tradeable_on_either_side(self, conn):
        k = ("2024-06-03", "P:101")
        assert by_key(sentinel_bars(conn), source="sentinel")[
            k].tradeable is True
        assert by_key(canonical_bars(), source="canonical")[
            k].tradeable is True

    def test_the_as_traded_OPEN_is_reconstructed_identically(self, conn):
        """SEP's open is split-adjusted like its close, so it is scaled by
        raw/close. Passing it through raw would fill in one price domain and
        mark the position in another."""
        mine = by_key(sentinel_bars(conn), source="sentinel")
        theirs = by_key(canonical_bars(), source="canonical")
        for k in sorted(mine):
            assert mine[k].raw_open == theirs[k].raw_open, k

    def test_split_agreement_boundary_is_identical_on_BOTH_paths(self):
        """ACTIONS 2.0 vs 2.03 used to double shares in the replay and apply
        no split in production because the adapters owned 2% and 1% thresholds.
        Pin both sides immediately inside and outside the one shared boundary.
        """
        from sentinel.feed import actions_map
        from stock_strategy_shared import split_reconciliation as shared

        bt = canonical()
        assert actions_map.resolve_split_orientation is \
            shared.resolve_split_orientation
        assert shared.SPLIT_AGREEMENT_TOLERANCE == 0.01

        assert actions_map.resolve_split_orientation(2.0, 2.02) == (
            2.0, shared.SPLIT_CORROBORATED_DIRECT)
        assert bt.reconcile_split(2.02, 2.0) == (2.0, "agreed")

        assert actions_map.resolve_split_orientation(2.0, 2.03) == (
            1.0, shared.SPLIT_UNRESOLVED)
        assert bt.reconcile_split(2.03, 2.0) == (1.0, "unresolved")

        # A quiet price-domain row is absence of orientation evidence, not a
        # synthetic ratio that may corroborate a nearby ACTIONS value.
        assert actions_map.resolve_split_orientation(1.005, None) == (
            1.0, shared.SPLIT_UNRESOLVED)
        assert bt.reconcile_split(None, 1.005) == (1.0, "unresolved")
        assert actions_map.resolve_split_orientation(
            1.005, 1 / 1.005) == (1.0, shared.SPLIT_UNRESOLVED)
        assert bt.reconcile_split(1 / 1.005, 1.005) == (
            1.0, "unresolved")

    @pytest.mark.parametrize("stated", [0.1, 0.5, 2.0, 10.0, 30.0])
    def test_direct_and_reciprocal_tolerance_matrix_matches(self, stated):
        from sentinel.feed import actions_map
        from stock_strategy_shared import split_reconciliation as shared

        bt = canonical()
        cases = [
            (stated * 1.009, shared.SPLIT_CORROBORATED_DIRECT, "agreed")]
        if stated > 1:
            cases.append(((1 / stated) * 1.009,
                          shared.SPLIT_CORROBORATED_RECIPROCAL,
                          "reciprocal"))
        for evidence, disposition, outcome in cases:
            expected_ratio, expected_disposition = \
                actions_map.resolve_split_orientation(stated, evidence)
            assert expected_disposition == disposition
            actual_ratio, actual_outcome = bt.reconcile_split(evidence, stated)
            assert actual_ratio == pytest.approx(expected_ratio)
            assert actual_outcome == outcome

        for evidence in (stated * 1.011, (1 / stated) * 1.011):
            expected = actions_map.resolve_split_orientation(stated, evidence)
            actual = bt.reconcile_split(evidence, stated)
            assert expected[1] == shared.SPLIT_UNRESOLVED
            assert actual == (1.0, "unresolved")

    @pytest.mark.parametrize("stated", [0.1, 0.5])
    def test_canonical_below_one_action_is_never_reciprocally_inverted(
            self, stated):
        from sentinel.feed import actions_map
        from stock_strategy_shared import split_reconciliation as shared

        bt = canonical()
        evidence = 1 / stated
        assert actions_map.resolve_split_orientation(stated, evidence) == (
            1.0, shared.SPLIT_UNRESOLVED)
        assert bt.reconcile_split(evidence, stated) == (1.0, "unresolved")

    def test_near_one_price_noise_is_absence_in_every_resolver(self):
        from sentinel.feed import actions_map
        from stock_strategy_shared import split_reconciliation as shared

        bt = canonical()
        assert shared.split_price_evidence(0.995) is None
        assert actions_map.resolve_split_orientation(0.995, 0.995) == (
            0.995, shared.SPLIT_AUTHORITATIVE_APPLIED)
        assert bt.reconcile_split(0.995, 0.995) == (0.995, "actions_only")

    def test_shared_resolver_and_replay_wrapper_agree_for_finite_ratios(self):
        from sentinel.feed import actions_map
        from stock_strategy_shared import split_reconciliation as shared

        bt = canonical()
        outcome_by_disposition = {
            shared.SPLIT_AUTHORITATIVE_APPLIED: "actions_only",
            shared.SPLIT_CORROBORATED_DIRECT: "agreed",
            shared.SPLIT_CORROBORATED_RECIPROCAL: "reciprocal",
            shared.SPLIT_UNRESOLVED: "unresolved",
        }
        # Keep this invariant inside the certified dependency-closed image.
        # The cross-product deliberately spans sub-unit canonical actions,
        # both sides of the near-one event boundary, direct and reciprocal
        # witnesses, tolerance edges, and noisy reverse denominators.
        ratios = (
            0.01, 1 / 30.003, 1 / 30, 0.1, 0.25, 0.5,
            0.979, 0.98, 0.99, 0.995, 1.0, 1.005, 1.01, 1.02, 1.021,
            1.5, 1.98, 2.0, 2.02, 3.0, 10.0, 30.0, 30.003, 100.0,
        )
        for stated in ratios:
            for evidence in ratios:
                normalized = None if evidence == 1.0 else evidence
                expected_ratio, disposition = \
                    actions_map.resolve_split_orientation(stated, normalized)
                actual_ratio, outcome = bt.reconcile_split(normalized, stated)
                assert actual_ratio == pytest.approx(expected_ratio), (
                    stated, evidence, disposition, outcome)
                assert outcome == outcome_by_disposition[disposition], (
                    stated, evidence, disposition, outcome)

    @pytest.mark.parametrize("raw_before,expected", [
        (199.9, 2.0),
        (50.025, 0.5),
    ])
    def test_no_actions_row_keeps_the_same_snapped_price_fallback(
            self, raw_before, expected):
        from sentinel.feed import actions_map

        source = [
            {"date": "2024-06-03", "ticker": "NOISY", "close": 100.0,
             "closeunadj": raw_before, "open": 100.0,
             "volume": 1_000_000.0},
            {"date": "2024-06-04", "ticker": "NOISY", "close": 100.0,
             "closeunadj": 100.0, "open": 100.0,
             "volume": 1_000_000.0},
        ]
        report = domains.NormalisationReport()
        mine = list(domains.normalise_sep_rows(
            source, resolve_identity=lambda *_: "303",
            authoritative_splits={}, dividends={}, report=report))
        bt = canonical()
        identity = bt.IdentityResolver([{
            "permaticker": "303", "ticker": "NOISY",
            "first_price_date": "2024-06-03",
            "last_price_date": "2024-06-04",
        }])
        canonical_rows = [{
            "date": row["date"], "ticker": row["ticker"],
            "open": row["open"], "close": row["close"],
            "close_unadjusted": row["closeunadj"],
            "volume": raw_compatible_volume(
                row["close"], row["closeunadj"], row["volume"]),
        } for row in source]
        theirs = bt.load_bars(
            _FakeConn(canonical_rows), "2024-06-03", "2024-06-04",
            authoritative_splits={}, dividends={}, identity=identity)

        assert mine[-1].vendor.split_ratio == pytest.approx(expected)
        assert theirs["2024-06-04"][0].split_ratio == pytest.approx(expected)
        assert actions_map.SPLIT_AGREEMENT_TOLERANCE == 0.01


# ── 3. the test can fail ─────────────────────────────────────────────────────

class TestThisComparisonIsNotVacuous:

    def test_it_compares_a_NONEMPTY_set(self, conn):
        assert len(by_key(sentinel_bars(conn), source="sentinel")) == \
            len(SESSIONS) * 2

    def test_a_DELIBERATE_divergence_is_caught(self, conn):
        """A parity test that cannot fail is decoration. Perturb one field on
        one bar and the comparison must find it."""
        from dataclasses import replace
        mine = by_key(sentinel_bars(conn), source="sentinel")
        theirs = by_key(canonical_bars(), source="canonical")
        k = ("2024-06-03", "P:101")
        theirs[k] = replace(theirs[k], split_ratio=2.0)
        assert any(mine[j].split_ratio != theirs[j].split_ratio for j in mine)
