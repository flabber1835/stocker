"""bt_universe is keyed on PERMANENT IDENTITY, not on a symbol.

THE DEFECT. `bt_universe` was `PRIMARY KEY (snapshot_date, ticker)` while also
carrying a `permaticker` column — so it could not represent the thing that column
exists to express. Sharadar TICKERS returns one row per permanent security, and a
REUSED symbol means two companies with the same ticker in one snapshot. They
collided on the key, `ON CONFLICT ... DO UPDATE` overwrote one with the other, and
WHICH survived depended on the order the API returned rows in.

Observed: ticker BIOT carried BIOTECH ACQUISITION CO (a SPAC, priced
2021-01-26..2023-02-02, delisted) and INSTINCT BIO TECHNICAL CO INC (listed
2026-07-24). The SPAC's row lost its permaticker; `_META_SQL` and `_IDENTITY_SQL`
filter `permaticker IS NOT NULL`; the resolver therefore saw ONE owner for the
symbol, skipped the listing-window check BY DESIGN, and attributed three years of
SPAC prices to the 2026 ADR.

WHY IT SURVIVED SO LONG. `_upsert_universe` returned `len(rows)` — rows
ATTEMPTED. 49,834 attempted against 21,733 stored read as unremarkable for
months, because nothing ever reported the second number. A writer that cannot say
what it stored cannot be audited.

Two tiers here. The pure tests need no database and cover the partition rules.
The integration tests run against a REAL Postgres, because the defect was a
CONSTRAINT and no fake can express one — the whole bug is what the database did
with two rows, and a mock would have accepted both all along.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BT_DATA = ROOT / "services" / "bt-data"
sys.path.insert(0, str(BT_DATA))

os.environ.setdefault("BT_MOCK_DATA", "true")
os.environ.setdefault("BT_DATABASE_URL",
                      "postgresql+asyncpg://x:x@localhost/x")

from app.main import (partition_universe_rows,  # noqa: E402
                      valid_permaticker)


# ── the identity predicate ───────────────────────────────────────────────────

class TestValidPermaticker:
    """One definition, so the writer, the report and these tests cannot
    disagree about what a usable identity is."""

    def test_a_real_id_survives_and_is_stringified(self):
        assert valid_permaticker(6400922) == "6400922"
        assert valid_permaticker("  6400922 ") == "6400922"

    def test_absence_in_all_its_spellings_is_absence(self):
        for v in (None, "", "   "):
            assert valid_permaticker(v) is None

    def test_the_NA_SENTINEL_is_absence(self):
        """'N/A' is a REAL value in this vendor's data — it is what
        `contraticker` carries when an acquirer is private. The same sentinel
        reached a delivered-security field through an `or None` that looked
        total and was not (docs/data-sources.md, defect D1). It must never
        become an identity."""
        for v in ("N/A", "n/a", "NA", "none", "NULL"):
            assert valid_permaticker(v) is None, v


# ── the partition ────────────────────────────────────────────────────────────

def _row(ticker, permaticker, snap="2026-08-08", **over):
    r = {"snapshot_date": snap, "ticker": ticker, "permaticker": permaticker,
         "name": f"{ticker} INC", "sector": None, "category": "Domestic Common Stock",
         "related_tickers": None, "first_price_date": "2021-01-04",
         "last_price_date": "2026-08-05", "is_delisted": False}
    r.update(over)
    return r


class TestThePartition:

    def test_rows_without_an_identity_are_rejected_and_NAMED(self):
        keep, rejected, collapsed = partition_universe_rows(
            [_row("AAA", "111"), _row("BBB", None), _row("CCC", "N/A")])
        assert [r["ticker"] for r in keep] == ["AAA"]
        assert sorted(r["ticker"] for r in rejected) == ["BBB", "CCC"]
        assert collapsed == []

    def test_TWO_COMPANIES_SHARING_A_TICKER_BOTH_SURVIVE(self):
        """THE falsifier for the BIOT defect, at the partition layer.

        Under the old key these were one row. Nothing about a shared symbol may
        cause either company to be discarded.
        """
        keep, rejected, collapsed = partition_universe_rows([
            _row("BIOT", "111", name="BIOTECH ACQUISITION CO",
                 first_price_date="2021-01-26", last_price_date="2023-02-02",
                 is_delisted=True),
            _row("BIOT", "6400922", name="INSTINCT BIO TECHNICAL CO INC",
                 first_price_date="2026-07-24", last_price_date="2026-08-06"),
        ])
        assert len(keep) == 2, "a shared ticker must not collapse two companies"
        assert {r["permaticker"] for r in keep} == {"111", "6400922"}
        assert rejected == [] and collapsed == []

    def test_the_SAME_identity_twice_collapses_and_is_counted(self):
        """Sharadar TICKERS carries a row per source table, so one security can
        legitimately arrive several times in one fetch. That is a collapse, and
        it must be COUNTED rather than resolved by arrival order."""
        keep, rejected, collapsed = partition_universe_rows(
            [_row("AAA", "111"), _row("AAA", "111")])
        assert len(keep) == 1 and len(collapsed) == 1

    def test_the_survivor_of_a_collapse_is_the_RICHER_row(self):
        """A sparser duplicate overwriting a fuller one silently loses the
        point-in-time listing window."""
        sparse = _row("AAA", "111", first_price_date=None, last_price_date=None,
                      category=None)
        rich = _row("AAA", "111")
        for order in ([sparse, rich], [rich, sparse]):
            keep, _, _ = partition_universe_rows([dict(r) for r in order])
            assert keep[0]["first_price_date"] == "2021-01-04", (
                "the richer row must win regardless of arrival order")

    def test_the_collapse_is_DETERMINISTIC_on_equally_rich_rows(self):
        """Otherwise the non-determinism has merely moved from the database to
        the writer, which is not a fix."""
        a, b = _row("AAA", "111"), _row("ZZZ", "111")
        first, _, _ = partition_universe_rows([dict(a), dict(b)])
        second, _, _ = partition_universe_rows([dict(b), dict(a)])
        assert first[0]["ticker"] == second[0]["ticker"]

    def test_one_company_in_two_snapshots_is_two_rows(self):
        keep, _, collapsed = partition_universe_rows(
            [_row("AAA", "111", snap="2026-08-07"),
             _row("AAA", "111", snap="2026-08-08")])
        assert len(keep) == 2 and collapsed == []

    def test_the_counts_ALWAYS_reconcile(self):
        """attempted == kept + rejected + collapsed, on any input. The whole
        point of the report is that nothing vanishes unaccounted for."""
        rows = [_row("AAA", "111"), _row("AAA", "111"), _row("BBB", None),
                _row("BIOT", "222"), _row("BIOT", "333"), _row("CCC", "N/A")]
        keep, rejected, collapsed = partition_universe_rows(rows)
        assert len(keep) + len(rejected) + len(collapsed) == len(rows)


# ── against a real database, because the defect WAS a constraint ─────────────

from tests.integration.conftest import _EphemeralPostgres  # noqa: E402


@pytest.fixture(scope="module")
def bt_dsn():
    try:
        pg = _EphemeralPostgres()
        pg.start()
    except Exception as exc:
        pytest.skip(f"could not start ephemeral Postgres: {exc}")
    try:
        yield pg.async_dsn
    finally:
        pg.stop()


def _fresh_module(dsn):
    os.environ["BT_DATABASE_URL"] = dsn
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as btmain
    return btmain


class TestAgainstARealDatabase:

    def test_the_migration_applies_and_keys_on_permaticker(self, bt_dsn):
        m = _fresh_module(bt_dsn)
        from sqlalchemy import text

        async def run():
            assert await m._ensure_schema() == [], "init_bt.sql must apply cleanly"
            async with m.engine.begin() as c:
                idx = (await c.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE tablename='bt_universe'"
                ))).scalars().all()
                pk = (await c.execute(text(
                    "SELECT conname FROM pg_constraint WHERE conname='bt_universe_pkey'"
                ))).scalars().all()
            return idx, pk

        idx, pk = asyncio.run(run())
        assert "uq_bt_universe_snapshot_permaticker" in idx
        assert "idx_bt_universe_snapshot_ticker" in idx
        assert pk == [], "the ticker primary key must be gone"

    def test_BOTH_COMPANIES_SHARING_A_TICKER_PERSIST(self, bt_dsn):
        """THE falsifier the owner asked for, at the layer that actually failed.

        Two rows, one snapshot, one ticker, two permatickers. Under the old key
        the second silently replaced the first and BIOTECH ACQUISITION CO ceased
        to exist. Both must survive, with their own listing windows intact.
        """
        m = _fresh_module(bt_dsn)
        from sqlalchemy import text
        snap = "2026-08-08"

        async def run():
            await m._ensure_schema()
            report = await m._upsert_universe([
                _row("BIOT", "111", snap=snap, name="BIOTECH ACQUISITION CO",
                     first_price_date="2021-01-26", last_price_date="2023-02-02",
                     is_delisted=True),
                _row("BIOT", "6400922", snap=snap,
                     name="INSTINCT BIO TECHNICAL CO INC",
                     first_price_date="2026-07-24", last_price_date="2026-08-06"),
            ], snap)
            async with m.engine.begin() as c:
                rows = (await c.execute(text(
                    "SELECT permaticker, name, first_price_date, is_delisted "
                    "  FROM bt_universe WHERE snapshot_date=:d AND ticker='BIOT' "
                    " ORDER BY permaticker"), {"d": m._d(snap)})).mappings().all()
            return report, [dict(r) for r in rows]

        report, rows = asyncio.run(run())
        assert len(rows) == 2, (
            f"a reused ticker collapsed to {len(rows)} row(s) — this is the BIOT "
            f"defect: {rows}")
        assert {r["permaticker"] for r in rows} == {"111", "6400922"}
        spac = next(r for r in rows if r["permaticker"] == "111")
        assert str(spac["first_price_date"]) == "2021-01-26"
        assert spac["is_delisted"] is True, "the SPAC's own delisting must survive"
        assert report["persisted"] == 2

    def test_the_acceptance_identity_valid_distinct_EQUALS_persisted(self, bt_dsn):
        """The owner's acceptance criterion, stated as an equality.

        Valid distinct identities attempted must equal identities persisted.
        Before the migration those two differed by tens of thousands and nothing
        said so — `_upsert_universe` reported the input length.
        """
        m = _fresh_module(bt_dsn)
        snap = "2026-08-09"
        rows = ([_row(f"T{i}", str(1000 + i), snap=snap) for i in range(40)]
                + [_row("SHARED", "9001", snap=snap),
                   _row("SHARED", "9002", snap=snap)]      # reused ticker
                + [_row("DUP", "9003", snap=snap),
                   _row("DUP", "9003", snap=snap)]          # same identity twice
                + [_row("NOID", None, snap=snap),
                   _row("SENTINEL", "N/A", snap=snap)])     # unusable identity

        async def run():
            await m._ensure_schema()
            return await m._upsert_universe(rows, snap)

        r = asyncio.run(run())
        assert r["attempted"] == 46
        assert r["rejected_no_permaticker"] == 2
        assert r["duplicate_identity_collapsed"] == 1
        assert r["distinct_identities"] == 43
        assert r["persisted"] == r["distinct_identities"], (
            f"ACCEPTANCE FAILURE: {r['distinct_identities']} distinct identities "
            f"attempted, {r['persisted']} persisted — rows were lost silently")

    def test_a_ticker_CHANGE_updates_the_row_rather_than_forking_it(self, bt_dsn):
        """Identity is the key, so a security that changes symbol keeps its row.
        Under the old key it would have become two securities."""
        m = _fresh_module(bt_dsn)
        from sqlalchemy import text
        snap = "2026-08-10"

        async def run():
            await m._ensure_schema()
            await m._upsert_universe([_row("OLD", "555", snap=snap)], snap)
            await m._upsert_universe([_row("NEW", "555", snap=snap)], snap)
            async with m.engine.begin() as c:
                return (await c.execute(text(
                    "SELECT ticker FROM bt_universe "
                    " WHERE snapshot_date=:d AND permaticker='555'"),
                    {"d": m._d(snap)})).scalars().all()

        assert asyncio.run(run()) == ["NEW"]

    def test_the_report_is_MEASURED_not_echoed(self, bt_dsn):
        """`persisted` must come from the database. The defect being fixed is
        precisely a writer that reported its own input back."""
        m = _fresh_module(bt_dsn)
        snap = "2026-08-11"

        async def run():
            await m._ensure_schema()
            await m._upsert_universe([_row("AAA", "777", snap=snap)], snap)
            # Re-writing the SAME identity must not inflate the persisted count.
            return await m._upsert_universe([_row("AAA", "777", snap=snap)], snap)

        r = asyncio.run(run())
        assert r["attempted"] == 1 and r["persisted"] == 1
