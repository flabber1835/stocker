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
   +-- canonical: wealth_core_replay.load_bars
```

The SQL is deliberately not what is compared — the canonical loader is driven
through a stand-in cursor. The mapping is the thing: which domain each price is
in, whether the ratio was inverted, where the dividend came from, and whether the
bar is tradeable.

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
    """The same rows in the canonical loader's column names."""
    return [{"date": r["date"], "ticker": r["ticker"], "open": r["open"],
             "close": r["close"], "close_unadjusted": r["closeunadj"],
             "volume": r["volume"]} for r in sep_rows()]


SPLITS = {("BBB", "2024-06-05"): 1.5}
DIVIDENDS = {("AAA", "2024-06-04"): 0.37}
IDENTITY = {"AAA": "P:AAA", "BBB": "P:BBB"}


class _Resolver:
    """The canonical loader takes an object; Sentinel takes a callable."""

    def resolve(self, ticker, session):     # noqa: D401 - trivial
        return IDENTITY.get(str(ticker))


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


def sentinel_bars(conn):
    report = domains.NormalisationReport()
    bars = domains.normalise_sep_rows(
        sep_rows(), resolve_identity=lambda t, s: IDENTITY.get(str(t)),
        authoritative_splits=SPLITS, dividends=DIVIDENDS, report=report)
    S.write_bars(conn, bars)
    return loader.load_window(conn, start=START, end=END).bars_by_session


def canonical_bars():
    bt = canonical()
    return bt.load_bars(_FakeConn(bt_rows()), START, END,
                        authoritative_splits=SPLITS, dividends=DIVIDENDS,
                        identity=_Resolver())


def by_key(bars_by_session):
    return {(s, b.security_id): b
            for s, bars in bars_by_session.items() for b in bars}


# ── 1. the whole bar, field by field ─────────────────────────────────────────

class TestTheTwoPathsProduceTheSameBars:

    def test_the_SAME_securities_on_the_SAME_sessions(self, conn):
        assert set(by_key(sentinel_bars(conn))) == set(by_key(canonical_bars()))

    @pytest.mark.parametrize("field", [
        "raw_close", "raw_open", "volume", "split_ratio",
        "dividend_per_share", "ticker", "tradeable",
        "unresolved_corporate_action"])
    def test_every_field_agrees(self, conn, field):
        mine, theirs = by_key(sentinel_bars(conn)), by_key(canonical_bars())
        bad = {k: (getattr(mine[k], field), getattr(theirs[k], field))
               for k in sorted(mine)
               if getattr(mine[k], field) != getattr(theirs[k], field)}
        assert not bad, f"{field} differs (sentinel, canonical): {bad}"


# ── 2. the fields most likely to be wrong, asserted on their own ─────────────

class TestTheValuesThatArePlausibleWhenWrong:

    def test_the_split_is_1_point_5_on_BOTH_sides(self, conn):
        k = ("2024-06-05", "P:BBB")
        assert by_key(sentinel_bars(conn))[k].split_ratio == pytest.approx(1.5)
        assert by_key(canonical_bars())[k].split_ratio == pytest.approx(1.5)

    def test_the_dividend_lands_on_the_same_session_on_BOTH_sides(self, conn):
        mine, theirs = by_key(sentinel_bars(conn)), by_key(canonical_bars())
        paid = {k for k, b in mine.items() if b.dividend_per_share}
        assert paid == {("2024-06-04", "P:AAA")}
        assert paid == {k for k, b in theirs.items() if b.dividend_per_share}

    def test_a_ZERO_VOLUME_bar_is_NOT_tradeable_on_either_side(self, conn):
        """The one field with no visible consequence until an order is filled.
        A bar with no volume is a security nobody traded that day; treating it
        as fillable executes against a market that did not exist."""
        k = ("2024-06-04", "P:BBB")
        assert by_key(sentinel_bars(conn))[k].tradeable is False
        assert by_key(canonical_bars())[k].tradeable is False

    def test_a_NORMAL_bar_is_tradeable_on_either_side(self, conn):
        k = ("2024-06-03", "P:AAA")
        assert by_key(sentinel_bars(conn))[k].tradeable is True
        assert by_key(canonical_bars())[k].tradeable is True

    def test_the_as_traded_OPEN_is_reconstructed_identically(self, conn):
        """SEP's open is split-adjusted like its close, so it is scaled by
        raw/close. Passing it through raw would fill in one price domain and
        mark the position in another."""
        mine, theirs = by_key(sentinel_bars(conn)), by_key(canonical_bars())
        for k in sorted(mine):
            assert mine[k].raw_open == theirs[k].raw_open, k


# ── 3. the test can fail ─────────────────────────────────────────────────────

class TestThisComparisonIsNotVacuous:

    def test_it_compares_a_NONEMPTY_set(self, conn):
        assert len(by_key(sentinel_bars(conn))) == len(SESSIONS) * 2

    def test_a_DELIBERATE_divergence_is_caught(self, conn):
        """A parity test that cannot fail is decoration. Perturb one field on
        one bar and the comparison must find it."""
        from dataclasses import replace
        mine = by_key(sentinel_bars(conn))
        theirs = by_key(canonical_bars())
        k = ("2024-06-03", "P:AAA")
        theirs[k] = replace(theirs[k], split_ratio=2.0)
        assert any(mine[j].split_ratio != theirs[j].split_ratio for j in mine)
