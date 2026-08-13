"""A plan id must determine the plan.

Commands have had this since the command-identity work: rebuild a stored client
key with a different security, side or quantity and `CommandEconomicsChanged`
stops the appliance. Plans had no equivalent, and the gap was hidden by a
comment — `save_plan` said the divergence check lived in "load_plan's caller",
and the caller that matters never performed one.

```text
plan_id = P    basket {A: 100}          stored
restart, reconstruction defect
plan_id = P    basket {A: 50, B: 50}    INSERT ... DO NOTHING  -> no-op
                                        load_plan(P)           -> {A: 100}
```

`core.catchup.catch_up` then calls `supersede_all_but(P)` and proceeds with the
OLD basket as the newly calculated intent. Durable intent that silently is not
what was computed is a label, not intent.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: The image splits these: `tests/` is at /work, the package SOURCES at
#: /work/repo. Reading `sentinel/core/catchup.py` through ROOT works on a host
#: and raises FileNotFoundError in the certified image, where a skip is a
#: failure. `TestNoRepoFileIsReadThroughROOT` caught it here too.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
for p in (str(ROOT), str(ROOT / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import schema  # noqa: E402
from sentinel.execution import journal  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

D = Decimal
TODAY = dt.date(2026, 8, 11)


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
    c = feed_store.connect(pg.sync_dsn)
    with c.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS sentinel_execution_plans CASCADE")
    c.commit()
    schema.ensure_schema(c)
    yield c
    c.close()


def a_plan(pid="plan-P", basket=None, **over):
    kw = dict(plan_id=pid, decision_session=TODAY, effective_session=TODAY,
              target_exposure=D(1), data_version=1,
              target_basket={k: D(v) for k, v in (basket or {"A": 100}).items()})
    kw.update(over)
    return ExecutionPlan(**kw)


class TestAPlanIdDeterminesThePlan:
    def test_identical_content_is_idempotent(self, conn):
        """Re-deriving a plan after a restart is NORMAL, and two separate
        objects with equal content must not look like divergence. Without this
        the guard could pass by refusing every second save — breaking recovery,
        which is what the idempotent insert exists for."""
        journal.save_plan(conn, a_plan())
        journal.save_plan(conn, a_plan())
        assert journal.load_plan(conn, "plan-P").target_basket == {"A": D(100)}

    def test_a_DIFFERENT_BASKET_under_the_same_id_refuses(self, conn):
        """The review's scenario, verbatim."""
        journal.save_plan(conn, a_plan(basket={"A": 100}))
        with pytest.raises(journal.PlanEconomicsChanged) as e:
            journal.save_plan(conn, a_plan(basket={"A": 50, "B": 50}))
        assert "target_basket" in str(e.value)

    def test_the_STORED_basket_is_what_a_later_load_returns(self, conn):
        """Why silence was dangerous: the insert is a no-op, so the OLD basket
        is what every subsequent read — including catch-up's `load_plan` right
        after `supersede_all_but` — gets back."""
        journal.save_plan(conn, a_plan(basket={"A": 100}))
        with pytest.raises(journal.PlanEconomicsChanged):
            journal.save_plan(conn, a_plan(basket={"B": 999}))
        assert journal.load_plan(conn, "plan-P").target_basket == {"A": D(100)}

    @pytest.mark.parametrize("field,value", [
        ("target_exposure", D("0.55")),
        ("data_version", 2),
        ("decision_session", dt.date(2026, 8, 10)),
        ("effective_session", dt.date(2026, 8, 12)),
        ("shadow_snapshot_hash", "deadbeef"),
        ("sentinel_transition_hash", "cafef00d"),
        ("strategy_fingerprint", "other-strategy"),
        ("deployment_id", "replacement-appliance"),
        ("broker", "other-broker"),
        ("broker_account_id", "OTHER-ACCOUNT"),
        ("takeover_epoch", 2),
        ("publication_fingerprint", "other-publication"),
        ("account_nav", D("100001.25")),
        ("account_cash", D("87654.32")),
        ("cash_residual", D("123.45")),
        ("unpriced_securities", ("SEC-BLIND",)),
        ("defensive_security", "SENTINEL:BIL"),
    ])
    def test_every_economic_FIELD_is_covered(self, conn, field, value):
        """Not just the basket. A plan that keeps its holdings and changes its
        exposure from 1.00 to 0.55 is a different intention wearing one name —
        and that direction is a liquidation."""
        original = a_plan()
        changed = a_plan(**{field: value})
        assert changed.fingerprint() != original.fingerprint(), (
            f"changing {field} did not move the immutable plan fingerprint")
        journal.save_plan(conn, original)
        with pytest.raises(journal.PlanEconomicsChanged) as e:
            journal.save_plan(conn, changed)
        assert field in str(e.value)

    def test_a_QUANTITY_change_alone_refuses(self, conn):
        """Same names, different sizes — the case a membership comparison
        would miss."""
        journal.save_plan(conn, a_plan(basket={"A": 100}))
        with pytest.raises(journal.PlanEconomicsChanged):
            journal.save_plan(conn, a_plan(basket={"A": 101}))

    def test_SUPERSESSION_is_not_a_divergence(self, conn):
        """A lifecycle fact, not economics. Including `superseded_by` in the
        comparison would make re-saving an already-superseded plan look like a
        reconstruction defect — and catch-up re-saves plans routinely."""
        journal.save_plan(conn, a_plan("plan-P"))
        journal.save_plan(conn, a_plan("plan-Q"))
        journal.supersede_all_but(conn, "plan-Q")
        assert journal.load_plan(conn, "plan-P").is_superseded
        journal.save_plan(conn, a_plan("plan-P"))          # must not raise

    def test_the_error_NAMES_what_differed(self, conn):
        """An error that says only "divergence" leaves the operator diffing two
        baskets by hand at the moment they can least afford to."""
        journal.save_plan(conn, a_plan(basket={"A": 100}))
        with pytest.raises(journal.PlanEconomicsChanged) as e:
            journal.save_plan(conn, a_plan(basket={"A": 100, "B": 7},
                                           target_exposure=D("0.5")))
        msg = str(e.value)
        assert "target_basket" in msg and "target_exposure" in msg
        assert "stored" in msg and "incoming" in msg


class TestTheCatchUpCallerIsProtected:
    def test_catch_up_saves_through_the_guarded_path(self):
        """The finding was a gap between a comment and a caller. Pinned in the
        source so the protection cannot be routed around with a raw INSERT."""
        src = (REPO / "sentinel" / "core" / "catchup.py").read_text()
        assert "journal.save_plan" in src
        assert "INSERT INTO sentinel_execution_plans" not in src, (
            "catch-up writes plans directly, bypassing the divergence check")
