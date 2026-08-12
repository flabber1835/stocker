"""Adapter conformance (F, H) and the destructive restore drill (G).

Three separate claims, and keeping them separate is the point:

    F  Alpaca's transport MAPS onto the contract. The state machine is not
       re-litigated here — that was proved once against the simulator.
    G  a database restored from BEFORE an event converges without duplicating
       or inventing a trade.
    H  IBKR is NOT certified, and the refusal is at startup with reasons.

The drill in G is the one that cannot be replaced by a serialize/deserialize
test. It actually destroys state, restores a stale copy, and makes the appliance
reconcile against a broker that moved on without it.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from tests.support.postgres import _EphemeralPostgres  # noqa: E402

from sentinel import binding as B, schema  # noqa: E402
from sentinel.execution import (  # noqa: E402
    certification, executor, journal, reconcile as R)
from sentinel.execution import alpaca as A  # noqa: E402
from sentinel.execution.alpaca import (  # noqa: E402
    AlpacaExecutionBroker, UnmappedBrokerStatus, map_status)
from sentinel.execution.contract import (  # noqa: E402
    BrokerAccountIdentity, BrokerInstrument, Completeness, Side)
from sentinel.execution.identity import DeploymentIdentity  # noqa: E402
from sentinel.execution.plan import ExecutionPlan  # noqa: E402
from sentinel.execution.simulator import SimulatedBroker  # noqa: E402
from sentinel.execution.states import CommandState as S  # noqa: E402
from sentinel.feed import store as feed_store  # noqa: E402

DEPLOY = DeploymentIdentity("nas-1", "sim", "SIM-ACCOUNT", 1)
AAA = BrokerInstrument(security_id="SEC-AAA", symbol="AAA", broker_id="b-AAA")
TODAY = date(2026, 8, 11)


def run(coro):
    return asyncio.run(coro)


def D(x):
    return Decimal(str(x))


# ===========================================================================
# F — the Alpaca adapter maps onto the contract
# ===========================================================================

class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpx:
    """Scripted transport. Records calls so ORDERING can be asserted."""

    def __init__(self, routes, post=None, delete=None):
        self.routes = routes
        self.post_result = post
        self.delete_result = delete
        self.calls: list = []
        client = self

        class _Client:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None, params=None):
                path = "/v2" + url.split("/v2", 1)[1]
                client.calls.append(("GET", path))
                result = client.routes.get(path)
                if callable(result):
                    result = result(params or {})
                return FakeResponse(result if result is not None else [])

            async def post(self, url, headers=None, json=None):
                client.calls.append(("POST", url.split("/v2", 1)[1], json))
                if isinstance(client.post_result, Exception):
                    raise client.post_result
                return client.post_result

            async def delete(self, url, headers=None):
                client.calls.append(("DELETE", url))
                if isinstance(client.delete_result, Exception):
                    raise client.delete_result
                return client.delete_result

        self.AsyncClient = _Client


def alpaca(routes, **kw):
    http = FakeHttpx(routes, **kw)
    broker = AlpacaExecutionBroker(
        api_key="k", secret_key="s", base_url="https://paper-api.alpaca.markets",
        resolve_security_id=lambda symbol: f"SEC-{symbol}",
        http_provider=lambda: http)
    return broker, http


def order_payload(oid="o-1", status="new", qty="10", filled="0",
                  key="sntl-abc", symbol="AAA"):
    return {"id": oid, "client_order_id": key, "symbol": symbol, "side": "buy",
            "status": status, "qty": qty, "filled_qty": filled,
            "submitted_at": "2026-08-11T14:00:00Z", "asset_id": "asset-1"}


class TestAlpacaStatusMapping:
    @pytest.mark.parametrize("raw,expected", [
        ("new", S.ACKNOWLEDGED), ("accepted", S.ACKNOWLEDGED),
        ("partially_filled", S.PARTIALLY_FILLED), ("filled", S.FILLED),
        ("canceled", S.CANCELLED), ("expired", S.CANCELLED),
        ("pending_cancel", S.CANCEL_PENDING), ("rejected", S.REJECTED),
    ])
    def test_every_certified_spelling_maps(self, raw, expected):
        assert map_status(raw) is expected

    def test_an_UNKNOWN_status_RAISES_rather_than_defaulting(self):
        """Guessing 'probably still working' leaves a settled order live in the
        journal; guessing 'probably terminal' abandons one that is not. The two
        guesses fail in opposite directions, so neither is available."""
        with pytest.raises(UnmappedBrokerStatus):
            map_status("some_new_alpaca_state")

    def test_the_mapping_lives_in_ONE_place(self):
        """Stocker's `partial_fill` / `partially_filled` split-brain lived for
        months because two sites spelled it differently."""
        from sentinel.execution import alpaca as mod
        assert map_status("partially_filled") is mod._STATUS["partially_filled"]


class TestAlpacaObservation:
    def test_it_reads_orders_positions_orders(self):
        broker, http = alpaca({"/v2/orders": [order_payload()],
                               "/v2/positions": []})
        run(broker.observe())
        assert [c[1] for c in http.calls] == ["/v2/orders", "/v2/positions",
                                              "/v2/orders"]

    def test_a_consistent_read_is_COMPLETE(self):
        broker, _ = alpaca({"/v2/orders": [order_payload()],
                            "/v2/positions": []})
        assert run(broker.observe()).completeness is Completeness.COMPLETE

    def test_a_fill_between_the_reads_is_INCONSISTENT(self):
        state = {"n": 0}

        def orders(_params):
            state["n"] += 1
            # The third call is the re-read; by then the order has filled.
            return [order_payload(status="filled" if state["n"] > 1 else "new",
                                  filled="10" if state["n"] > 1 else "0")]

        broker, _ = alpaca({"/v2/orders": orders, "/v2/positions": []})
        assert run(broker.observe()).completeness is Completeness.INCONSISTENT

    def test_hitting_the_page_cap_reports_TRUNCATED_not_COMPLETE(self):
        """The Stocker adapter issued ONE unpaginated GET with limit=500 and
        direction=desc, so a busy account silently lost its OLDEST orders —
        exactly the stale resting ones that matter."""
        from sentinel.execution import alpaca as mod
        full_page = [order_payload(oid=f"o-{i}") for i in range(mod.PAGE_SIZE)]
        broker, _ = alpaca({"/v2/orders": full_page, "/v2/positions": []})
        assert run(broker.observe()).completeness is Completeness.TRUNCATED

    def test_positions_carry_DECIMAL_quantities_from_the_wire_string(self):
        broker, _ = alpaca({
            "/v2/orders": [],
            "/v2/positions": [{"symbol": "AAA", "qty": "0.1",
                               "asset_id": "asset-1"}]})
        observation = run(broker.observe())
        assert observation.positions[0].quantity == Decimal("0.1"), (
            "via Decimal(str), not Decimal(float) — the difference is what "
            "makes an exact-quantity exit fail for over-sell by 1e-17")


class TestAlpacaSubmit:
    def test_a_transport_exception_is_UNKNOWN_never_a_rejection(self):
        """The most important line in the adapter."""
        broker, _ = alpaca({}, post=TimeoutError("connection reset"))
        outcome = run(broker.submit(client_key="sntl-x", instrument=AAA,
                                    side=Side.BUY, quantity=D(10)))
        assert outcome.state is S.UNKNOWN

    def test_a_5xx_is_UNKNOWN_because_the_broker_may_have_recorded_it(self):
        broker, _ = alpaca({}, post=FakeResponse(status_code=503, text="oops"))
        assert run(broker.submit(client_key="k", instrument=AAA, side=Side.BUY,
                                 quantity=D(10))).state is S.UNKNOWN

    def test_a_4xx_IS_a_rejection_because_the_broker_said_so(self):
        broker, _ = alpaca({}, post=FakeResponse(status_code=400, text="bad qty"))
        assert run(broker.submit(client_key="k", instrument=AAA, side=Side.BUY,
                                 quantity=D(10))).state is S.REJECTED

    def test_a_DUPLICATE_key_is_UNKNOWN_not_rejected(self):
        """The key is already resting, which is exactly what makes a blind retry
        safe. Resolving it needs a lookup, not a guess."""
        broker, _ = alpaca({}, post=FakeResponse(
            status_code=422, text="client_order_id must be unique"))
        assert run(broker.submit(client_key="k", instrument=AAA, side=Side.BUY,
                                 quantity=D(10))).state is S.UNKNOWN

    def test_the_client_key_is_sent_verbatim(self):
        broker, http = alpaca({}, post=FakeResponse(
            {"id": "o-9", "status": "new"}, 200))
        run(broker.submit(client_key="sntl-deadbeef", instrument=AAA,
                          side=Side.BUY, quantity=D(10)))
        body = http.calls[0][2]
        assert body["client_order_id"] == "sntl-deadbeef"
        assert body["qty"] == "10", "quantity as a STRING, never a float"

    def test_the_symbol_is_translated_at_the_transport_boundary(self):
        broker, http = alpaca({}, post=FakeResponse({"id": "o", "status": "new"}))
        run(broker.submit(client_key="k",
                          instrument=BrokerInstrument("SEC-BRK-B", "BRK-B"),
                          side=Side.BUY, quantity=D(1)))
        assert http.calls[0][2]["symbol"] == "BRK.B"


class TestAlpacaCancel:
    def test_an_accepted_cancel_is_ACKNOWLEDGED_not_CANCELLED(self):
        """A broker can accept a cancel and cancel nothing — observed
        2026-08-09. Only an observation may advance the command."""
        broker, _ = alpaca({}, delete=FakeResponse(status_code=204))
        assert run(broker.cancel("o-1")).state is S.ACKNOWLEDGED


class TestAlpacaHasNoClosePosition:
    def test_the_adapter_exposes_no_close_position(self):
        """DELETE /v2/positions carries no client_order_id, so an order placed
        through it cannot hold Sentinel's identity and is unrecoverable."""
        assert not hasattr(AlpacaExecutionBroker, "close_position")

    def test_nor_a_cancel_all(self):
        assert not hasattr(AlpacaExecutionBroker, "cancel_all_orders")

    def test_capabilities_are_declared_CONSERVATIVELY(self):
        caps = AlpacaExecutionBroker.capabilities
        assert caps.stable_client_key and caps.single_order_cancel
        assert not caps.market_on_open, (
            "this adapter sends DAY orders; claiming MOO while sending DAY is "
            "the silent substitution the fail-closed rule exists to prevent")
        assert not caps.fractional_quantities, (
            "a capability is what has been PROVEN, not what the vendor's docs "
            "permit")


# ===========================================================================
# H — IBKR is not certified, and says why
# ===========================================================================

class TestAdapterCertification:
    def test_alpaca_and_the_simulator_are_certified(self):
        assert set(certification.certified_names()) == {"alpaca", "simulator"}

    def test_IBKR_is_refused_at_STARTUP_with_reasons(self):
        with pytest.raises(certification.AdapterNotCertified) as exc:
            certification.require_certified("ibkr")
        message = str(exc.value)
        assert "uuid4" in message, "the duplicate-identity defect"
        assert "holiday calendar" in message
        assert "confirmation" in message

    def test_an_UNLISTED_adapter_is_refused_too(self):
        """An unlisted adapter is not an untested one, it is an unknown one."""
        with pytest.raises(certification.AdapterNotCertified,
                           match="not in the certification registry"):
            certification.require_certified("some-new-broker")

    def test_the_IBKR_adapter_is_GONE_not_merely_uncertified(self):
        """Eradication, asserted rather than assumed.

        The registry used to say "prototype only", and a prototype sitting in
        the tree is a prototype somebody eventually wires up — carrying its
        uuid4-per-close, its Mon-Fri-no-holidays clock and its auto-confirmed
        broker prompts with it. It is now deleted and recoverable only from
        `stocker-legacy-2026-08`, which is where a design built against the
        retired surface belongs.
        """
        assert not (ROOT / "shared" / "stock_strategy_shared" / "broker"
                    / "ibkr.py").exists()
        entry = certification.REGISTRY["ibkr"]
        assert not entry.certified
        assert any("NO IMPLEMENTATION EXISTS" in r for r in entry.reasons)

    def test_the_broker_factory_is_gone_too(self):
        """Runtime BROKER-env dispatch is how a second broker gets selected by
        accident. One deployment, one broker, constructed directly."""
        assert not (ROOT / "shared" / "stock_strategy_shared" / "broker"
                    / "factory.py").exists()


# ===========================================================================
# G — the destructive stale-backup restore drill
# ===========================================================================

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


STATE_TABLES = ("sentinel_account_binding", "sentinel_ownership_events",
                "sentinel_commands", "sentinel_command_events",
                "sentinel_execution_plans", "sentinel_fills",
                "sentinel_observations")


@pytest.fixture()
def conn(pg):
    c = feed_store.connect(pg.sync_dsn)
    with c.cursor() as cur:
        for t in STATE_TABLES:
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    c.commit()
    schema.ensure_schema(c)
    B.bind(c, deployment_id="nas-1", broker="sim",
           broker_account_id="SIM-ACCOUNT")
    yield c
    c.close()


def backup(conn) -> dict:
    """A row-level snapshot of the behavioural state. Stands in for pg_dump."""
    out: dict = {}
    with conn.cursor() as cur:
        for table in STATE_TABLES:
            cur.execute(f"SELECT * FROM {table}")
            cols = [d[0] for d in cur.description]
            out[table] = (cols, cur.fetchall())
    return out


def restore(conn, snapshot: dict) -> None:
    """DESTRUCTIVE. Everything after the backup is gone, as it would be."""
    with conn.cursor() as cur:
        for table in STATE_TABLES:
            cur.execute(f"TRUNCATE {table} CASCADE")
        for table, (cols, rows) in snapshot.items():
            if not rows:
                continue
            placeholders = ",".join(["%s"] * len(cols))
            cur.executemany(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})",
                rows)
    conn.commit()


def plan(plan_id="plan-1"):
    return ExecutionPlan(plan_id=plan_id, decision_session=date(2026, 8, 10),
                         effective_session=TODAY, target_exposure=D(1),
                         data_version=1)


class TestStaleBackupRestore:
    """A restored database is EXPECTED to be behind the broker. Not exceptional."""

    def _setup(self, conn):
        broker = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "SIM-ACCOUNT"))
        snapshot = backup(conn)              # taken BEFORE anything happened
        p = replace(plan(), target_basket={"SEC-AAA": D(10)})
        executor.adopt_plan(conn, p)
        result = run(executor.execute_session(
            broker=broker, conn=conn, deployment=DEPLOY, plan=p,
            instruments={"SEC-AAA": AAA}, today=TODAY))
        return broker, snapshot, result.submitted[0]

    def test_an_order_placed_after_the_backup_is_RECOVERED_not_duplicated(self, conn):
        broker, snapshot, command = self._setup(conn)
        assert journal.load_commands(conn, DEPLOY)

        restore(conn, snapshot)              # the disaster
        assert journal.load_commands(conn, DEPLOY) == (), "the journal forgot"

        rec = run(R.reconcile(broker=broker, conn=conn, binding=None,
                              deployment=DEPLOY))
        assert [o.client_key for o in rec.recovered_orders] == [command.client_key]
        assert rec.foreign_orders == (), (
            "an order carrying OUR key is history to adopt, never a stranger's")

    def test_the_restored_appliance_does_NOT_re_submit(self, conn):
        """The duplicate-position failure, in its most realistic form."""
        broker, snapshot, _ = self._setup(conn)
        submits_before = len([c for c in broker.calls if c.startswith("submit:")])
        restore(conn, snapshot)

        p2 = replace(plan("plan-2"), target_basket={"SEC-AAA": D(10)})
        executor.adopt_plan(conn, p2)
        run(executor.execute_session(
            broker=broker, conn=conn, deployment=DEPLOY, plan=p2,
            instruments={"SEC-AAA": AAA}, today=TODAY))

        submits_after = len([c for c in broker.calls if c.startswith("submit:")])
        assert submits_after == submits_before, (
            "the working order already covers the target; a second submit here "
            "is a doubled position")

    def test_a_fill_that_happened_while_down_is_ATTRIBUTED_after_restore(self, conn):
        """This assertion used to read FOREIGN_ACTIVITY, described as "correct
        and conservative ... until the recovered order is adopted" — and nothing
        adopted it, so the appliance stayed there forever: able to de-risk,
        never able to re-risk. The adversarial scenario surfaced that; recovery
        now ADOPTS the order, so the position is explained and the runtime
        converges.
        """
        broker, snapshot, command = self._setup(conn)
        broker.fill(command.client_key)      # filled while the appliance was gone
        restore(conn, snapshot)

        rec = run(R.reconcile(broker=broker, conn=conn, binding=None,
                              deployment=DEPLOY))
        assert rec.observed == {"SEC-AAA": D(10)}
        assert rec.expected == {"SEC-AAA": D(10)}, "attributed to OUR order"
        assert rec.runtime_state.value == "RUNNING"
        assert journal.load_commands(conn, DEPLOY)[0].is_recovered

    def test_the_binding_SURVIVES_the_restore_so_the_account_is_still_known(self, conn):
        broker, snapshot, _ = self._setup(conn)
        restore(conn, snapshot)
        assert B.require(conn).broker_account_id == "SIM-ACCOUNT"

    def test_a_restore_onto_the_WRONG_account_refuses_everything(self, conn):
        _broker, snapshot, _ = self._setup(conn)
        restore(conn, snapshot)
        elsewhere = SimulatedBroker(
            account=BrokerAccountIdentity("sim", "A-DIFFERENT-ACCOUNT"))
        with pytest.raises(B.AccountMismatch):
            run(R.reconcile(broker=elsewhere, conn=conn, binding=None,
                            deployment=DEPLOY))

    def test_a_takeover_epoch_bump_makes_stored_commands_UNRESUMABLE(self, conn):
        """Adoption fences the keyspace. Stored commands from the previous
        generation must be RECOVERED, not silently resumed as this one's."""
        self._setup(conn)
        B.adopt_restored(conn, notes="replacement host")
        adopted = B.require(conn).identity
        with pytest.raises(journal.StoredKeyMismatch):
            journal.load_commands(conn, adopted)


# ── malformed payloads are UNUSABLE, not defaulted ───────────────────────────

class TestCorruptBrokerEvidenceCannotLookComplete:
    """Unknown STATUS already refused to guess. Side and quantity did not.

    ```python
    side = Side.BUY if str(payload.get("side")) == "buy" else Side.SELL
    quantity = _dec(payload.get("qty"), Decimal(0)) or Decimal(0)
    ```

    So `{"side": null, "qty": "garbage"}` read as **SELL, quantity 0** — and
    the surrounding observation could still be labelled COMPLETE.

    The asymmetry was the wrong way round. A status is a hint about lifecycle;
    side and quantity ARE the trade. And a COMPLETE read of an apparently flat
    account is precisely what authorises increases, so corrupt evidence became
    indistinguishable from a quiet account at the moment that distinction
    matters most.
    """

    #: A real adapter, because `_to_order` is a method and the paper allowlist
    #: now gates construction — building one is also a small check that the two
    #: guards compose.
    ADAPTER = AlpacaExecutionBroker(
        api_key="k", secret_key="s",
        base_url="https://paper-api.alpaca.markets")

    def order(self, **over):
        p = {"id": "o1", "client_order_id": "k1", "symbol": "AAA",
             "side": "buy", "qty": "10", "filled_qty": "0", "status": "new"}
        p.update(over)
        return p

    def parse(self, payload):
        return self.ADAPTER._to_order(payload)

    def test_a_WELL_FORMED_order_still_parses(self):
        """Without this the guard could pass by refusing everything."""
        o = self.parse(self.order())
        assert o.side is Side.BUY and o.quantity == Decimal(10)

    #: `"BUY "` is deliberately NOT here: it strips to "buy". This list first
    #: contained it, contradicting the whitespace test two below — strict about
    #: MEANING, lenient about presentation, and a test set has to pick one.
    @pytest.mark.parametrize("bad", [None, "", "long", "b", 1, "sel", "buy sell"])
    def test_an_UNRECOGNISED_SIDE_refuses(self, bad):
        """Every one of these used to become a SELL."""
        with pytest.raises(A.MalformedBrokerPayload) as e:
            self.parse(self.order(side=bad))
        assert "side" in str(e.value)

    @pytest.mark.parametrize("good,want", [("buy", Side.BUY), ("sell", Side.SELL),
                                           ("BUY", Side.BUY), ("Sell", Side.SELL),
                                           ("BUY ", Side.BUY), (" sell", Side.SELL)])
    def test_case_and_whitespace_are_still_ACCEPTED(self, good, want):
        """Strict about meaning, not about presentation. Refusing "BUY" would
        be an outage dressed as rigour."""
        assert self.parse(self.order(side=good)).side is want

    @pytest.mark.parametrize("bad", [None, "", "garbage", "NaN", "Infinity",
                                     "1.2.3", "-5"])
    def test_an_UNREADABLE_QUANTITY_refuses(self, bad):
        """Zero is a CLAIM about the account — nothing filled, nothing held —
        so defaulting an unreadable field to it is a confident statement made
        from an absence of evidence."""
        with pytest.raises(A.MalformedBrokerPayload):
            self.parse(self.order(qty=bad))

    @pytest.mark.parametrize("bad", [None, "", "garbage", "-1"])
    def test_an_UNREADABLE_FILLED_QUANTITY_refuses(self, bad):
        with pytest.raises(A.MalformedBrokerPayload):
            self.parse(self.order(filled_qty=bad))

    def test_a_LEGITIMATE_zero_is_still_zero(self):
        """The distinction the fix rests on: an explicit "0" is evidence, an
        absent field is not."""
        assert self.parse(self.order(filled_qty="0")).filled_quantity == \
            Decimal(0)

    def test_the_error_names_the_ORDER(self):
        """An operator reading this at 3am needs to know which one."""
        with pytest.raises(A.MalformedBrokerPayload) as e:
            self.parse(self.order(id="o-42", qty="garbage"))
        assert "o-42" in str(e.value)

    def test_a_NEGATIVE_POSITION_is_read_faithfully_not_zeroed(self):
        """The one place a negative IS legitimate wire data. Sentinel's
        envelope forbids holding a short, so it must be SEEN and refused
        upstream — reading it as zero would make the short invisible, which is
        strictly worse than refusing the observation."""
        import inspect
        src = inspect.getsource(A.AlpacaExecutionBroker)
        assert "allow_negative=True" in src, (
            "position quantities are not allowed to be negative, so a short "
            "at the broker would either raise or read as something it is not")

    def test_it_matches_the_UNKNOWN_STATUS_discipline(self):
        """Stated as one assertion because the finding was an ASYMMETRY: the
        adapter was already strict in one half of the payload and lenient in
        the other."""
        with pytest.raises(A.UnmappedBrokerStatus):
            A.map_status("teleported")
        with pytest.raises(A.MalformedBrokerPayload):
            self.parse(self.order(side="teleported"))
