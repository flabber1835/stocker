"""Economic bracket, immutable membership, replay and recovery boundary falsifiers."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal
import json
import weakref

import pytest

from sentinel import restore_validation
from sentinel.execution import activity_stream, alpaca, broker_cash, journal
from sentinel.execution.contract import BrokerPosition, Completeness
from tests.sentinel.test_alpaca_boundary_overlay import adapter, activity_event, Response, sse
from tests.sentinel.test_issue209_asset_identity import _order
from tests.sentinel.test_native_fee_plan_continuation import case, conn, pg, event, ingest, NOW


def test_brackets_compare_economics_instants_and_actual_changes():
    order = _order("asset-A")
    equivalent = replace(order, quantity=Decimal("2.0000"), filled_quantity=Decimal("0e-10"),
                         submitted_at=order.submitted_at.astimezone(timezone(timedelta(hours=-7))))
    assert alpaca._fingerprint([order]) == alpaca._fingerprint([equivalent])
    for changed in [replace(equivalent, quantity=Decimal("2.000000001")),
                    replace(equivalent, submitted_at=order.submitted_at + timedelta(microseconds=1)),
                    replace(equivalent, external_replacement=True),
                    replace(equivalent, instrument=replace(order.instrument, broker_id="asset-B"))]:
        assert alpaca._fingerprint([order]) != alpaca._fingerprint([changed])
    pos = BrokerPosition(order.instrument, Decimal("3"))
    assert alpaca._position_fingerprint([pos]) == alpaca._position_fingerprint([replace(pos, quantity=Decimal("3.00"))])
    assert alpaca._position_fingerprint([pos]) != alpaca._position_fingerprint([replace(pos, quantity=Decimal("3.01"))])


def test_concurrent_snapshots_isolate_clients_and_recheck_every_request(monkeypatch):
    broker, http = adapter(routes={"/v2beta1/events/activities": Response(text="")})
    broker.capabilities = replace(broker.capabilities, recent_fill_history=True)
    owners, closed, checks = {}, [], []
    class Client(http.AsyncClient):
        async def get(self, *args, **kwargs):
            owners.setdefault(self, set()).add(asyncio.current_task())
            await asyncio.sleep(0)
            return await super().get(*args, **kwargs)

        async def __aexit__(self, *args):
            closed.append(self)
            return await super().__aexit__(*args)
    http.AsyncClient = Client
    monkeypatch.setattr(broker, "_require_transport_authority", lambda: checks.append(1))
    async def observe():
        return await asyncio.gather(broker.observe(), broker.observe_with_terminal_recovery(
            submitted_after=NOW, processed_through=NOW))
    result = asyncio.run(observe())
    assert all(o.completeness is Completeness.COMPLETE for o in result)
    assert len(owners) == 2 and all(len(tasks) == 1 for tasks in owners.values())
    assert set(owners) == set(closed) and len(checks) == len(http.calls)


@pytest.mark.parametrize("interrupted_after_headers", [False, True])
def test_cash_discovery_transport_failure_preserves_original_cause(interrupted_after_headers):
    from httpx import ReadError
    broker, http = adapter()
    original = ReadError("interrupted activity transport")
    class Broken(http.AsyncClient):
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            if not interrupted_after_headers:
                raise original
            class Incomplete:
                status_code = 200
                async def aiter_lines(self):
                    yield ": connected"
                    raise original
            yield Incomplete()
    http.AsyncClient = Broken
    with pytest.raises(RuntimeError, match="Activity SSE transport failed") as caught:
        asyncio.run(broker.account_cash_activities(after=NOW - timedelta(days=2), through=NOW))
    assert caught.value.__cause__ is original


def test_retained_discovery_streams_and_discards_each_old_envelope(monkeypatch):
    broker, http = adapter()
    target = 400
    def wire(index):
        return activity_event(event_id=f"{index:026d}", ref_id=f"r-{index}")
    class StreamClient(http.AsyncClient):
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            assert method == "GET" and "since" in kwargs["params"]
            class Incremental:
                status_code = 200
                async def aiter_lines(self):
                    for n in range(1, target + 1):
                        yield "data: " + json.dumps(wire(n))
                        yield ""
            yield Incremental()
    http.AsyncClient = StreamClient
    parse = activity_stream.events
    active, peak = 0, 0
    class Tracked(dict):
        pass
    async def tracked(*args, **kwargs):
        nonlocal active, peak
        def released():
            nonlocal active
            active -= 1
        async for original in parse(*args, **kwargs):
            envelope = Tracked(original)
            active += 1
            peak = max(active, peak)
            weakref.finalize(envelope, released)
            yield envelope
    monkeypatch.setattr(activity_stream, "events", tracked)
    monkeypatch.setattr(activity_stream.UniqueReferences, "memory_limit", 8)
    batch = asyncio.run(broker.account_cash_activities(
        after=NOW - timedelta(days=2), through=NOW, since_event_id=f"{target:026d}"))
    assert batch.activities == () and peak <= 3 and active == 0
    with activity_stream.UniqueReferences() as refs:
        assert all(refs.add(str(i)) for i in range(target))
        assert not refs.add("0") and not refs.add(str(target - 1))


@pytest.mark.parametrize("fault", ["missing_cursor", "omitted_suffix", "changed_suffix"])
def test_cursor_replay_must_cover_exact_discovered_economics(fault):
    rows = [activity_event(event_id=f"{i:026d}", ref_id=f"r-{i}") for i in range(1, 4)]
    def route(params):
        if "since" in params:
            return Response(text=sse(*(rows[1:] if fault == "missing_cursor" else rows)))
        if fault == "omitted_suffix":
            return Response(text=sse(rows[0], rows[-1]))
        return Response(text=sse(rows[0], dict(rows[1], net_amount="99"), rows[2]))
    broker, _ = adapter(routes={"/v2beta1/events/activities": route})
    with pytest.raises(alpaca.MalformedBrokerPayload, match="omitted the retained|replay disagreed"):
        asyncio.run(broker.account_cash_activities(after=NOW - timedelta(days=2), through=NOW,
                                                  since_event_id=rows[0]["event_id"]))


def test_competing_current_plans_refused_by_execution_and_private_restore(conn, case):
    from sentinel.feed import runtime_schema
    runtime_schema.migrate_feed_schema(conn)
    second = replace(case["plan"], plan_id="other-stamped-plan")
    journal.save_plan(conn, second)
    with pytest.raises(journal.PlanAuthorityMissing, match="multiple stamped"):
        journal.latest_plan(conn)
    conn.commit()
    with pytest.raises(restore_validation.RestoreValidationRefused, match="multiple stamped"):
        restore_validation.validate_restored_database(conn)


def test_plans_share_authenticated_prefix_across_new_events_and_restart(conn, case):
    state = case["initial"]
    for i in range(12):
        plan_id = f"same-prefix-{i}"
        journal.save_plan(conn, replace(case["plan"], plan_id=plan_id))
        b = broker_cash.record_plan_baseline(conn, plan_id=plan_id, decision_session=NOW.date(), activity_state=state)
        assert b.activity_membership == case["baseline"].activity_membership
    next_state = ingest(conn, [case["old"], event(2, "FEE", "-0.07")], hours=1)
    assert next_state.membership_root != state.membership_root
    nodes = dict(conn.execute("SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                              (broker_cash.MEMBERSHIP_PREFIX + "%",)))
    assert len(nodes) == 2
    assert nodes[broker_cash.MEMBERSHIP_PREFIX + next_state.membership_root]["parent"] == state.membership_root
    assert all(len(node["members"]) == 1 for node in nodes.values())
    plans = list(conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                              (broker_cash.PLAN_BASELINE_PREFIX + "%",)))
    assert len(plans) == 13 and all(raw["membership_root"] == state.membership_root and
                                     "activity_membership" not in raw for (raw,) in plans)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
                    (broker_cash.MEMBERSHIP_PREFIX + state.membership_root,))
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="missing or altered"):
        broker_cash.load_plan_baseline(conn, plan_id="same-prefix-0")


def test_legacy_cursor_backfills_exact_rows_once_without_promoting_legacy_plan(conn, case):
    state = case["initial"]
    cursor = broker_cash.ACTIVITY_CURSOR_PREFIX + "alpaca:" + state.account_id
    raw = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (cursor,)).fetchone()[0]
    raw.pop("membership_root")
    raw["kind"] = "broker-cash-activity/v4" if "posting_kinds" in raw else "broker-cash-activity/v3"
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s", (json.dumps(raw), cursor))
    # Real legacy installations had inline plan memberships and no prefix nodes.
    plan_key = broker_cash.PLAN_BASELINE_PREFIX + case["plan"].plan_id
    inline = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s", (plan_key,)).fetchone()[0]
    del inline["membership_root"]
    inline.update(kind="broker-cash-plan/v4", activity_membership=dict(case["baseline"].activity_membership))
    conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name=%s",
                 (json.dumps(inline), plan_key))
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
                 (broker_cash.MEMBERSHIP_PREFIX + state.membership_root,))
    legacy = broker_cash.load_activity_state(conn, broker=state.broker, account_id=state.account_id)
    broker_cash.record_plan_baseline(conn, plan_id="legacy-cutover", decision_session=NOW.date(), activity_state=legacy)
    assert conn.execute("SELECT state->>'kind' FROM sentinel_processed_sessions WHERE cursor_name=%s",
                        (broker_cash.PLAN_BASELINE_PREFIX + "legacy-cutover",)).fetchone()[0] == "broker-cash-plan/v4"
    assert not conn.execute("SELECT 1 FROM sentinel_processed_sessions WHERE cursor_name LIKE %s",
                            (broker_cash.MEMBERSHIP_PREFIX + "%",)).fetchall()
    upgraded = ingest(conn, [case["old"], event(2, "FEE", "-0.07")], hours=1)
    node = conn.execute("SELECT state FROM sentinel_processed_sessions WHERE cursor_name=%s",
                        (broker_cash.MEMBERSHIP_PREFIX + upgraded.membership_root,)).fetchone()[0]
    assert node["parent"] is None and len(node["members"]) == 2
    assert broker_cash.load_plan_baseline(conn, plan_id=case["plan"].plan_id) == case["baseline"]

def test_large_cash_frontier_stamps_new_plan_without_enumerating_history(conn, case, monkeypatch):
    history = [case["old"]] + [event(i, "FEE", "-0.01") for i in range(2, 302)]
    state = ingest(conn, history, hours=1)
    roots = broker_cash.membership_prefixes(conn, state.broker, state.account_id, state.membership_root)
    assert len(roots) == 4
    assert len(roots[case["initial"].membership_root]) == 1
    assert len(roots[state.membership_root]) == 301
    tip = broker_cash._membership_tip(conn, state)
    assert len(tip) <= 128
    with monkeypatch.context() as patch:
        patch.setattr(broker_cash, "membership_prefixes", lambda *_: pytest.fail("read historical members"))
        patch.setattr(broker_cash, "_native_cash_ledger", lambda *a, **k: pytest.fail("rescanned cash ledger"))
        result = broker_cash.record_plan_baseline(conn, plan_id="cheap-plan", decision_session=NOW.date(),
                                                  activity_state=state, return_baseline=False)
        assert result is None
        assert broker_cash.record_plan_baseline(conn, plan_id="cheap-plan", decision_session=NOW.date(),
                                               activity_state=state, return_baseline=False) is None
    assert len(broker_cash.load_plan_baseline(conn, plan_id="cheap-plan").activity_membership) == 301
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
                 (broker_cash.MEMBERSHIP_PREFIX + state.membership_root,))
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="immutable native membership head"):
        broker_cash.record_plan_baseline(conn, plan_id="broken-tip", decision_session=NOW.date(),
                                         activity_state=state, return_baseline=False)
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="immutable native membership head"):
        ingest(conn, history, hours=2)

def test_disconnected_but_well_formed_plan_membership_refused_live_and_on_restore(conn, case):
    from sentinel.feed import runtime_schema
    runtime_schema.migrate_feed_schema(conn)
    state = case["initial"]
    native_id, _ = case["baseline"].activity_membership[0]
    orphan = broker_cash._write_membership_node(conn, state, None, {native_id: "f" * 64})
    assert orphan != state.membership_root
    conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state, '{membership_root}', to_jsonb(%s::text))"
                 " WHERE cursor_name=%s", (orphan, broker_cash.PLAN_BASELINE_PREFIX + case["plan"].plan_id))
    conn.commit()
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="outside the account cash chain"):
        broker_cash.load_plan_baseline(conn, plan_id=case["plan"].plan_id)
    with pytest.raises(broker_cash.BrokerCashAuthorityRefused, match="immutable"):
        broker_cash.record_plan_baseline(conn, plan_id=case["plan"].plan_id, decision_session=NOW.date(),
                                        activity_state=state, return_baseline=False)
    conn.rollback()
    with pytest.raises(restore_validation.RestoreValidationRefused, match="outside the account cash chain"):
        restore_validation.validate_restored_database(conn)
