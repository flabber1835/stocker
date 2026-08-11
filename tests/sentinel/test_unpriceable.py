"""P0 — a missing mark liquidated the position it could not price.

THE FAILURE, written before the fix. It is a direct contradiction between two
functions ten lines apart.

`project` states the rule and follows it:

    A security with no mark is OMITTED rather than sized at zero. Zero is a
    target — "hold none of this" — and it would liquidate a position because a
    price was missing.

`reproject` then sweeps up everything held that the target does not mention:

```python
for sid in held:
    remaining.setdefault(sid, -held[sid] - committed.get(sid, Decimal(0)))
```

which turns the omission straight back into the thing it was avoiding:

```text
held AAA = 100
AAA has no mark
project() omits AAA          <- correctly refuses to guess
setdefault(AAA, -100)        <- SELL ALL of it
```

And the plan is wrong too, not merely the arithmetic: `target_basket` omits AAA,
so `compute_delta` reads `desired = 0` and the executor liquidates on its own.

The sweep is not itself wrong — a security Wealth Core has genuinely DROPPED
must be sold, and selling needs no mark because the quantity is known exactly.
What is wrong is that two very different situations arrive at the same place:

```text
not in weights          Wealth Core no longer wants it   -> SELL ALL. Correct.
in weights, no mark     we cannot price it               -> HOLD. No decision.
```

THE PROPERTY BEING BOUGHT: **an unpriceable security that is still wanted holds
its current quantity.** "We cannot value this" and "we want none of this" are
different facts, and only one of them is a reason to sell.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel.core import catchup as CU  # noqa: E402
from sentinel.feed import store as S  # noqa: E402

D = Decimal


@pytest.fixture(scope="module")
def pg():
    try:
        server = _EphemeralPostgres()
        server.start()
    except Exception as exc:                                  # noqa: BLE001
        pytest.skip(f"ephemeral Postgres unavailable: {exc}")
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def conn(pg):
    c = S.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        for (t,) in cur.fetchall():
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    S.ensure_schema(c)
    from sentinel import schema as sentinel_schema
    sentinel_schema.ensure_schema(c)
    yield c
    c.close()


WEIGHTS = {"P-AAA": D("0.5"), "P-BBB": D("0.5")}
MARKS_OK = {"P-AAA": D("100"), "P-BBB": D("50")}
MARKS_BLIND = {"P-BBB": D("50")}          # AAA cannot be priced


class TestTheFailure:
    def test_an_unpriceable_HELD_security_is_not_sold(self, conn):
        """The headline. 100 shares of AAA, no price for AAA, and the account
        must still hold 100 shares of AAA afterwards."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"),
                           marks=MARKS_BLIND, held={"P-AAA": D("100")})

        assert out.remaining.get("P-AAA") == D("0"), (
            f"remaining {out.remaining.get('P-AAA')} for a security whose only "
            f"defect is that we could not price it")

    def test_the_PLAN_carries_the_held_quantity_not_zero(self, conn):
        """The other half, and the one the executor acts on. A basket that
        omits AAA is a basket whose target for AAA is zero — `compute_delta`
        reads it as SELL ALL without ever consulting `remaining`."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"),
                           marks=MARKS_BLIND, held={"P-AAA": D("100")})

        assert out.plan is not None
        assert out.plan.target_basket.get("P-AAA") == D("100"), (
            "an omitted security is a target of zero to the executor")

    def test_the_priceable_names_are_UNAFFECTED(self, conn):
        """One blind name must not stop the rest of the book converging. NAV
        was observed directly and every other mark is present, so their
        arithmetic is unchanged."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"),
                           marks=MARKS_BLIND, held={"P-AAA": D("100")})
        assert out.plan.target_basket["P-BBB"] == D("1000")

    def test_it_is_NAMED_not_silently_absorbed(self, conn):
        """Holding is the safe response and it is still a degraded one. An
        operator needs to know the book contains a position nothing can value."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"),
                           marks=MARKS_BLIND, held={"P-AAA": D("100")})
        assert any("P-AAA" in c for c in out.caveats)


    def test_a_ZERO_mark_is_unpriceable_too_not_a_price_of_zero(self, conn):
        """A present-but-useless mark, which is the form this arrives in more
        often than an absent key: a halted security, a vendor row with a null
        close, a corporate action mid-processing.

        `project` already skips it — dividing by it would raise — so
        `unpriceable` has to agree, or the two disagree about which securities
        got sized and the security falls into the liquidation sweep.
        """
        for bad in (D("0"), D("-1")):
            out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                               weights=WEIGHTS, exposure=D("1"),
                               marks={"P-AAA": bad, "P-BBB": D("50")},
                               held={"P-AAA": D("100")})
            assert out.plan.target_basket["P-AAA"] == D("100"), bad
            assert any("P-AAA" in c for c in out.caveats), bad


class TestTheSweepStillWorks:
    """The liquidation sweep exists for a real case and must survive."""

    def test_a_security_WEALTH_CORE_DROPPED_is_still_sold(self, conn):
        """Not in the target at all. Selling needs no mark — the quantity is
        known exactly — so a missing price is no reason to keep it."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights={"P-BBB": D("1.0")}, exposure=D("1"),
                           marks={"P-BBB": D("50")},
                           held={"P-ZZZ": D("40")})

        assert out.remaining["P-ZZZ"] == D("-40")
        assert out.plan.target_basket.get("P-ZZZ") == D("0")

    def test_a_dropped_security_with_NO_mark_is_ALSO_sold(self, conn):
        """The case the two rules could most easily be confused. Wealth Core
        does not want it, and not being able to price it changes nothing: the
        share count is what the sale needs."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights={"P-BBB": D("1.0")}, exposure=D("1"),
                           marks={"P-BBB": D("50")},
                           held={"P-ZZZ": D("40")})
        assert out.remaining["P-ZZZ"] == D("-40")

    def test_a_normal_reprojection_is_unchanged(self, conn):
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"), marks=MARKS_OK)
        assert out.plan.target_basket == {"P-AAA": D("500"), "P-BBB": D("1000")}


class TestTheBlindSecurityIsNotBOUGHT_EITHER:
    def test_an_unpriceable_security_that_is_NOT_held_is_omitted(self, conn):
        """Nothing to hold and no price to size a purchase with. Omitted, and
        named — not sized at some default."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"), marks=MARKS_BLIND)
        assert "P-AAA" not in out.plan.target_basket
        assert "P-AAA" not in out.remaining
        assert any("P-AAA" in c for c in out.caveats)

    def test_holding_is_a_HOLD_not_a_target_that_grows(self, conn):
        """`target = held` must track what is actually held, not a remembered
        number. A NAV change must move nothing for a blind security."""
        a = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                         weights=WEIGHTS, exposure=D("1"),
                         marks=MARKS_BLIND, held={"P-AAA": D("100")})
        b = CU.reproject(conn, session="2026-08-10", nav=D("500000"),
                         weights=WEIGHTS, exposure=D("1"),
                         marks=MARKS_BLIND, held={"P-AAA": D("100")})
        assert a.plan.target_basket["P-AAA"] == D("100")
        assert b.plan.target_basket["P-AAA"] == D("100")

    def test_a_committed_quantity_is_respected_for_a_blind_security(self, conn):
        """40 held, 60 working, and no price. The target is what EXISTS plus
        what is already coming — anything else either cancels a live order's
        worth of shares or orders them a second time."""
        out = CU.reproject(conn, session="2026-08-10", nav=D("100000"),
                           weights=WEIGHTS, exposure=D("1"),
                           marks=MARKS_BLIND, held={"P-AAA": D("40")},
                           committed={"P-AAA": D("60")})
        assert out.plan.target_basket["P-AAA"] == D("100")
        assert out.remaining["P-AAA"] == D("0")
