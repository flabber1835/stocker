"""Private-only full production callbacks with a local Alpaca HTTP simulator.

The simulator is a software timing fixture, never native exchange evidence.
Every financial verifier and fresh broker guard runs unchanged. No transport
has a network fallback and no provider credentials are read from the process.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
import uuid
import sys
import re
from unittest.mock import patch

from tools.opening_latency_qualification import (
    QualificationRefused, connect, require_database, require_environment,
    require_target, reviewed_runtime,
)


class Response:
    def __init__(self, payload=None, *, text="", status=200):
        self.payload, self.text, self.status_code = payload, text, status
        self.headers = {}

    def json(self, **_kwargs):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            error = RuntimeError("local simulator HTTP refusal")
            error.response = self
            raise error


class LocalAlpaca:
    """Deterministic immediate fills through the real adapter's HTTP parser."""
    def __init__(self, *, account, cash, assets, window):
        self.account, self.cash, self.assets, self.window = account, Decimal(cash), assets, window
        self.account_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, "opening-latency:" + account))
        self.by_id = {row["id"]: row for row in assets.values()}
        self.positions, self.orders, self.events = {}, {}, []
        self.requests = Counter()
        self.started, self.first_order_seconds = None, None
        from sentinel.execution.opening_prices import FEED
        self.quote_feed = FEED
        owner = self

        class Client:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, url, headers=None, params=None):
                return owner.get(url, dict(params or {}))

            async def post(self, url, headers=None, json=None):
                return owner.post(url, dict(json or {}))

            async def delete(self, *_args, **_kwargs):
                raise QualificationRefused("SIMULATOR_UNEXPECTED_CANCELLATION")

        self.AsyncClient = Client

    def state(self):
        """Only simulated provider observations cross callback processes."""
        return {"cash": str(self.cash), "positions": {key: str(value) for key, value in self.positions.items()},
            "orders": self.orders, "events": self.events, "requests": dict(self.requests),
            "started": self.started, "first_order_seconds": self.first_order_seconds}

    def restore(self, value):
        if set(value) != {"cash", "positions", "orders", "events", "requests", "started", "first_order_seconds"}:
            raise QualificationRefused("INVALID_LOCAL_PROVIDER_STATE_ROUNDTRIP")
        self.cash = Decimal(value["cash"])
        self.positions = {key: Decimal(amount) for key, amount in value["positions"].items()}
        self.orders, self.events = value["orders"], value["events"]
        self.requests = Counter(value["requests"])
        self.started, self.first_order_seconds = value["started"], value["first_order_seconds"]

    @staticmethod
    def path(url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {
                "paper-api.alpaca.markets", "data.alpaca.markets"}:
            raise QualificationRefused("SIMULATOR_UNKNOWN_ENDPOINT")
        return unquote(parsed.path)

    def get(self, url, params):
        path = self.path(url)
        self.requests["GET " + path] += 1
        now = datetime.now(timezone.utc)
        if path == "/v2/account":
            equity = self.cash + sum((quantity * self.by_id[asset]["price"]
                                      for asset, quantity in self.positions.items()), Decimal(0))
            return Response({"id": self.account_uuid, "account_number": self.account,
                "cash": str(self.cash), "equity": str(equity), "last_equity": str(equity),
                "buying_power": str(self.cash), "multiplier": "1", "status": "ACTIVE",
                "trading_blocked": False, "account_blocked": False, "trade_suspended_by_user": False})
        if path.startswith("/v2/assets/"):
            asset = self.assets[path.rsplit("/", 1)[1]]
            return Response({key: asset[key] for key in ("id", "symbol")} |
                            {"status": "active", "tradable": True, "fractionable": False})
        if path == "/v2/clock":
            opened, closed = self.window()
            return Response({"timestamp": now.isoformat(), "is_open": opened <= now < closed,
                "next_open": (opened if now < opened else opened + timedelta(days=1)).isoformat(),
                "next_close": closed.isoformat()})
        if path == "/v2/stocks/quotes/latest":
            if params.get("feed") != self.quote_feed:
                raise QualificationRefused("SIMULATOR_QUOTE_FEED_POLICY_MISMATCH")
            return Response({"quotes": {symbol: {"ap": str(self.assets[symbol]["price"]),
                "bp": str(self.assets[symbol]["price"] * Decimal("0.9999")),
                "as": 1000, "bs": 1000, "t": now.isoformat()}
                for symbol in params["symbols"].split(",")}})
        if path == "/v2/positions":
            return Response([{"asset_id": asset, "symbol": self.by_id[asset]["symbol"], "qty": str(quantity)}
                             for asset, quantity in self.positions.items() if quantity])
        if path == "/v2/orders":
            rows = list(reversed(list(self.orders.values()))) if params.get("status") == "closed" else []
            before = params.get("before_order_id")
            if before:
                rows = rows[next(index + 1 for index, row in enumerate(rows) if row["id"] == before):]
            return Response(rows[:int(params.get("limit", 500))])
        if path == "/v2/orders:by_client_order_id":
            row = next((row for row in self.orders.values()
                        if row["client_order_id"] == params["client_order_id"]), None)
            return Response(row, status=200 if row else 404)
        if path.startswith("/v2/orders/"):
            return Response(self.orders[path.rsplit("/", 1)[1]])
        if path == "/v2beta1/events/activities":
            rows = self.events
            for field, comparison in (("since_id", lambda value, bound: value > bound),
                                      ("until_id", lambda value, bound: value <= bound)):
                if params.get(field):
                    rows = [row for row in rows if comparison(row["event_id"], params[field])]
            for field, comparison in (("since", lambda value, bound: value >= bound),
                                      ("until", lambda value, bound: value <= bound)):
                if params.get(field):
                    bound = datetime.fromisoformat(params[field].replace("Z", "+00:00"))
                    rows = [row for row in rows if comparison(datetime.fromisoformat(row["at"]), bound)]
            return Response(text="".join("data: " + json.dumps(row) + "\n\n" for row in rows))
        if path.startswith("/v2/account/activities"):
            return Response([])
        raise QualificationRefused("SIMULATOR_UNIMPLEMENTED_READ")

    def post(self, url, body):
        if self.path(url) != "/v2/orders" or self.started is None:
            raise QualificationRefused("SIMULATOR_UNEXPECTED_MUTATION")
        self.requests["POST /v2/orders"] += 1
        if any(row["client_order_id"] == body["client_order_id"] for row in self.orders.values()):
            raise QualificationRefused("SIMULATOR_DUPLICATE_POST")
        asset = self.by_id[body["symbol"]]
        quantity = Decimal(body["qty"])
        delta = quantity if body["side"] == "buy" else -quantity
        new_cash = self.cash - delta * asset["price"]
        new_shares = self.positions.get(asset["id"], Decimal(0)) + delta
        if quantity <= 0 or new_cash < 0 or new_shares < 0:
            raise QualificationRefused("SIMULATOR_LONG_ONLY_CASH_ENVELOPE")
        self.cash, self.positions[asset["id"]] = new_cash, new_shares
        stamp = datetime.now(timezone.utc).isoformat()
        index = len(self.orders) + 1
        order_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "opening-order:" + body["client_order_id"]))
        order = {**body, "id": order_id, "symbol": asset["symbol"], "asset_id": asset["id"],
            "status": "filled", "filled_qty": str(quantity), "filled_avg_price": str(asset["price"]),
            "submitted_at": stamp}
        self.orders[order_id] = order
        self.events.append({"account_id": self.account_uuid, "at": stamp,
            "event_id": f"01OPENING{index:018d}", "ref_id": str(uuid.uuid5(uuid.NAMESPACE_URL, order_id)),
            "status": "executed", "executed_at": stamp, "settle_date": stamp[:10],
            "activity_type": "TRD", "activity_subtype": None, "previous_id": None,
            "qty": str(quantity), "price": str(asset["price"]),
            "net_amount": str(-delta * asset["price"]), "currency": "USD",
            "details": {"execution_type": "fill", "order_id": order_id, "asset_id": asset["id"],
                "symbol": asset["symbol"], "side": body["side"], "client_order_id": body["client_order_id"]}})
        if self.first_order_seconds is None:
            self.first_order_seconds = time.monotonic() - self.started
            print(json.dumps({"stage": "FIRST_SIMULATED_POST", "seconds": round(self.first_order_seconds, 6),
                              "orders": len(self.orders)}), flush=True)
        return Response(order, status=201)


def scheduler_profile(path, expected_sha256):
    from sentinel.automation.model import AutomationConfig
    if path is None:
        raise QualificationRefused("DEPLOYED_SCHEDULER_PROFILE_REQUIRED")
    value = json.loads(path.read_text())
    config = AutomationConfig.model_validate(value["scheduler"])
    if (set(value) != {"schema", "scheduler", "config_sha256"}
            or value["schema"] != "sentinel.attended-scheduler-profile/1"
            or value["config_sha256"] != config.fingerprint or config.fingerprint != expected_sha256
            or (config.lease_seconds, config.heartbeat_seconds, config.control_poll_seconds,
                config.execution_delay_seconds, config.maximum_execution_lateness_seconds) != (12, 3, 3, 60, 540)):
        raise QualificationRefused("DEPLOYED_SCHEDULER_PROFILE_MISMATCH")
    return config


def provider_metadata(path):
    """Read explicit broker asset metadata; it never supplies financial prices."""
    if path is None:
        return {}, None
    raw = path.read_bytes()
    value = json.loads(raw)
    try:
        rows = value["assets"]
        if (set(value) != {"schema", "method", "endpoint", "captured_at", "assets"}
                or value["schema"] != "sentinel.local-provider-asset-metadata/1"
                or value["method"] != "GET" or not rows
                or not value["endpoint"].startswith("https://paper-api.alpaca.markets/v2/assets/")
                or datetime.fromisoformat(value["captured_at"]).tzinfo is None):
            raise ValueError
        result = {}
        for row in rows:
            if (set(row) != {"security_id", "id", "symbol", "status", "tradable"}
                    or not isinstance(row["security_id"], str) or not row["security_id"]
                    or not isinstance(row["symbol"], str) or not row["symbol"]
                    or row["status"] != "active" or row["tradable"] is not True
                    or str(uuid.UUID(row["id"])) != row["id"]
                    or row["security_id"] in result):
                raise ValueError
            result[row["security_id"]] = dict(row)
        if len({row["id"] for row in result.values()}) != len(result):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise QualificationRefused("INVALID_PROVIDER_METADATA_FIXTURE") from exc
    return result, hashlib.sha256(raw).hexdigest()


def fixture_assets(plan, proof, resolver, metadata=None):
    """Use source-bound stock IDs or explicit broker metadata, and retained marks."""
    from sentinel.execution.contract import BrokerObservation, Completeness
    from sentinel.paper.targets import _plan_deltas
    metadata = metadata or {}
    provider_ids = resolver.provider_asset_ids
    if resolver.source_provider not in {"ALPACA_OPENFIGI", "SHARADAR"}:
        raise QualificationRefused("UNSUPPORTED_FIXTURE_SOURCE_PROVIDER")
    flat = BrokerObservation(observed_at=datetime.now(timezone.utc), orders=(), positions=(),
                             completeness=Completeness.COMPLETE)
    needed = {delta.security_id for delta in _plan_deltas(target_basket=plan.target_basket,
        observation=flat, minimum_quantity_increment=Decimal(1)) if delta.remaining != 0}
    if plan.target_exposure != 0:
        needed.update(intent.security_id for intent in plan.opening_intents)
    if needed - set(proof["marks"]) or needed - set(proof["tickers"]):
        raise QualificationRefused("MISSING_NEEDED_AUTHENTICATED_FIXTURE_ASSET")
    assets = {}
    for sid in sorted(needed):
        symbol = proof["tickers"][sid]
        if resolver(symbol) != sid:
            raise QualificationRefused("FIXTURE_SYMBOL_SOURCE_IDENTITY_MISMATCH")
        if sid in provider_ids:
            broker_id, origin = provider_ids[sid], "authenticated-source"
        else:
            if resolver.source_provider == "ALPACA_OPENFIGI" and sid != "SENTINEL:BIL":
                raise QualificationRefused("MISSING_NEEDED_AUTHENTICATED_FIXTURE_ASSET")
            row = metadata.get(sid)
            if row is None or row["symbol"] != symbol:
                raise QualificationRefused("MISSING_NEEDED_PROVIDER_METADATA_FIXTURE")
            broker_id, origin = row["id"], "GET-only-provider-metadata"
        assets[symbol] = {"id": broker_id, "symbol": symbol, "security_id": sid,
                          "price": Decimal(proof["marks"][sid]), "identity_origin": origin}
    if (len(assets) != len(needed) or len({row["id"] for row in assets.values()}) != len(needed)
            or any(not row["price"].is_finite() or row["price"] <= 0 for row in assets.values())):
        raise QualificationRefused("AMBIGUOUS_OR_INVALID_NEEDED_FIXTURE_ASSET")
    return assets


class CallbackMetrics:
    """Bounded timing observers; arguments, values and exceptions stay private."""
    MAX_FUNCTIONS, MAX_CALL_LOGS, MAX_SLOTS = 32, 192, 16

    def __init__(self, phase, *, clock=time.monotonic, cpu=time.process_time):
        self.phase, self.clock, self.cpu = phase, clock, cpu
        self.started, self.cpu_started = clock(), cpu()
        self.rows, self.slots, self.logged = {}, {}, 0

    def completed(self, name, started, cpu_started, error):
        row = self.rows[name]
        elapsed, cpu = self.clock() - started, self.cpu() - cpu_started
        row["seconds"] += elapsed
        row["cpu_seconds"] += cpu
        row["failures"] += int(error is not None)
        count = row["calls"]
        if self.logged < self.MAX_CALL_LOGS and (count <= 3 or count & (count - 1) == 0):
            value = {"stage": "PURE_METHOD", "phase": self.phase, "function": name,
                "calls": count, "seconds": round(elapsed, 6), "cpu_seconds": round(cpu, 6),
                "result": "PASS" if error is None else "REFUSED"}
            if error is not None:
                value["error_type"] = error
            print(json.dumps(value), flush=True)
            self.logged += 1

    def observe(self, stack, owner, attribute, *, name=None):
        original = getattr(owner, attribute, None)
        if original is None:
            return
        label = name or owner.__name__ + "." + attribute
        if label in self.rows or len(self.rows) >= self.MAX_FUNCTIONS:
            raise QualificationRefused("INVALID_CALLBACK_METRIC_REGISTRATION")
        self.rows[label] = {"calls": 0, "seconds": 0.0, "cpu_seconds": 0.0, "failures": 0}

        def begin():
            self.rows[label]["calls"] += 1
            return self.clock(), self.cpu()

        if inspect.isgeneratorfunction(original):
            @wraps(original)
            def observed(*args, **kwargs):
                started, cpu_started = begin()
                error = None
                try:
                    yield from original(*args, **kwargs)
                except BaseException as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    self.completed(label, started, cpu_started, error)
        else:
            @wraps(original)
            def observed(*args, **kwargs):
                started, cpu_started = begin()
                error = None
                try:
                    return original(*args, **kwargs)
                except BaseException as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    self.completed(label, started, cpu_started, error)
        stack.enter_context(patch.object(owner, attribute, observed))

    def observe_material(self, stack, structural):
        original = structural.material
        def observed(conn, *, slot, key, load):
            label = slot if isinstance(slot, str) and re.fullmatch(r"[a-z0-9_-]{1,64}", slot) else "OTHER"
            if label not in self.slots and len(self.slots) >= self.MAX_SLOTS - 1:
                label = "OTHER"
            row = self.slots.setdefault(label, {"calls": 0, "loads": 0})
            row["calls"] += 1
            def measured_load():
                row["loads"] += 1
                return load()
            return original(conn, slot=slot, key=key, load=measured_load)
        stack.enter_context(patch.object(structural, "material", observed))

    def install(self, stack):
        from sentinel import (dual_plan_authority, dual_reconciliation, identity, rolling_checkpoint,
            rolling_daily_checkpoint, rolling_runtime, runtime_admission, shadow_runtime, strategy,
            structural_verification)
        from sentinel.core import rolling_inputs
        from sentinel.feed import readiness_scope, rolling_store
        from sentinel.paper import validation
        for owner, names in (
            (runtime_admission, ("_retained_checkpoint", "_retained_checkpoint_uncached", "current_context",
                "bind_context", "retained_publication_strategy", "require_retained_state")),
            (rolling_checkpoint, ("read", "_signature")), (rolling_daily_checkpoint, ("read", "signature")),
            (rolling_inputs, ("readiness_inputs", "_mapped_bars")),
            (rolling_store, ("_verify_content_uncached",)),
            (rolling_runtime, ("_load_closure", "_guard_status", "_guard_projection")),
            (dual_plan_authority, ("rederive_plan", "_rederive_plan", "_rederive_guard_plan")),
            (shadow_runtime, ("verified_shadow_status",)),
            (dual_reconciliation, ("verified_shadow_intent", "_verified_guard_intent")),
            (identity, ("rehearsal_identity",)),
            (validation, ("_validate_broker_grant", "_assert_plan_authorities")),
            (strategy, ("production_strategy", "runtime_strategy_identity")),
            (readiness_scope, ("material", "verified_snapshot")),
        ):
            for name in names:
                self.observe(stack, owner, name)
        self.observe(stack, rolling_inputs.SnapshotReferences, "__init__",
                     name="sentinel.core.rolling_inputs.SnapshotReferences.__init__")
        self.observe_material(stack, structural_verification)

    def finish(self, http, counts, result, error):
        print(json.dumps({"stage": "CALLBACK_FINALLY", "phase": self.phase,
            "result": result, "error_type": error, "seconds": round(self.clock() - self.started, 6),
            "cpu_seconds": round(self.cpu() - self.cpu_started, 6), "invocations": dict(counts),
            "orders": len(http.orders), "first_order_seconds": http.first_order_seconds,
            "http_requests": dict(http.requests), "structural_slots": self.slots,
            "pure_methods": {name: {key: round(value, 6) if isinstance(value, float) else value
                                     for key, value in row.items()} for name, row in self.rows.items()},
            "call_logs_emitted": self.logged, "call_log_cap": self.MAX_CALL_LOGS}), flush=True)


def supervised_callback(args, config, context, phase, body, http, counts):
    """Use the actual process supervisor; exchange only provider fixture state."""
    from sentinel.automation import store
    from sentinel.automation.model import ExecuteResult, PrepareResult
    from sentinel.automation.service import AutomationService
    async def callback(child_context):
        metrics, outcome, error = CallbackMetrics(phase), "REFUSED", None
        print(json.dumps({"stage": "CALLBACK_STARTED", "phase": phase}), flush=True)
        try:
            with ExitStack() as observers:
                metrics.install(observers)
                result = await body(child_context)
                outcome = "PASS"
                return {"result": result.model_dump(mode="json"), "provider": http.state(), "counts": dict(counts)}
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            metrics.finish(http, counts, outcome, error)
    supervisor = AutomationService(config=config, holder_id=context.permit.holder_id,
        refresh=callback, prepare=callback, execute=callback, recover=callback)
    try:
        value = asyncio.run(supervisor._invoke(callback, context, permit=context.permit, phase=phase,
            heartbeat_conn_factory=lambda: connect(args, read_only=False, heartbeat=True)))
        if set(value) != {"result", "provider", "counts"}:
            raise QualificationRefused("INVALID_CALLBACK_FIXTURE_ROUNDTRIP")
        http.restore(value["provider"])
        counts.clear()
        counts.update(value["counts"])
        return (PrepareResult if phase == "PREPARE" else ExecuteResult).model_validate(value["result"])
    finally:
        with connect(args, read_only=False, heartbeat=True) as reader:
            store.register_instance(reader, instance_id=context.permit.holder_id, state="IDLE")


def transition_for_callback(conn, **values):
    """Leave the parent idle while the actual child owns its transactions."""
    from sentinel.automation import store
    cycle = store.transition_cycle(conn, **values)
    conn.rollback()
    return cycle


def cleanup_private(args, *, preserve_failure=False):
    """Fence only this target through a fresh, independently checked connection."""
    from sentinel.automation import store
    try:
        with connect(args, read_only=False, heartbeat=True) as reader:
            control = store.load_control(reader)
            if not control.kill_switch_engaged:
                control = store.engage_kill(reader, actor="PRIVATE_SIMULATOR", reason="qualification ended")
            if control.enabled:
                store.deactivate(reader, actor="PRIVATE_SIMULATOR", reason="qualification ended")
        print(json.dumps({"stage": "PRIVATE_CLEANUP", "result": "PASS"}), flush=True)
    except BaseException as exc:
        print(json.dumps({"stage": "PRIVATE_CLEANUP", "result": "REFUSED",
                          "error_type": type(exc).__name__}), flush=True)
        if not preserve_failure:
            raise


EXECUTION_CALENDAR_OWNERS = (
    "sentinel.automation.schedule", "sentinel.paper.execution", "sentinel.paper.validation",
    "sentinel.execution.alpaca", "sentinel.execution.guarded", "sentinel.execution.opening_prices",
)


def execution_window_fixture(stack, session, window):
    """Bind execution windows without changing immutable source timing authority."""
    from importlib import import_module
    import sentinel.feed as feed
    original = import_module("sentinel.feed.calendar")
    owners = [import_module(name) for name in EXECUTION_CALENDAR_OWNERS]
    class ExecutionCalendar:
        def __getattr__(self, name):
            return getattr(original, name)

        def session_window(self, value):
            caller = sys._getframe(1).f_globals.get("__name__")
            if caller in EXECUTION_CALENDAR_OWNERS and str(value) == str(session):
                return window
            return original.session_window(value)
    proxy = ExecutionCalendar()
    for owner in owners:
        stack.enter_context(patch.object(owner, "calendar", proxy, create=True))
    stack.enter_context(patch.object(feed, "calendar", proxy))
    return proxy


def require_quote_policy(feed):
    if feed != "sip":
        raise QualificationRefused("CANONICAL_SIP_QUOTE_POLICY_REQUIRED")


def qualify(args, stages):
    import sentinel
    require_environment(os.environ, sentinel.__file__)
    require_target(args)
    from sentinel import automation_runtime, backup_runtime_authority, binding
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint, rolling_runtime
    from sentinel.automation import schedule, store
    from sentinel.automation.model import ControlBinding, CycleContext, CycleSpec, CycleState
    from sentinel.authority import load_rollout_state
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
    from sentinel.execution import feed_inputs, journal, target_reprojection
    from sentinel.feed import calendar, rolling_store
    from sentinel.paper import execution, preparation, recovery, validation
    from sentinel.execution.opening_prices import FEED
    require_quote_policy(FEED)

    with connect(args, read_only=False) as conn, reviewed_runtime(conn, args), ExitStack() as stack:
        if conn.execute("SELECT (SELECT count(*) FROM sentinel_commands),"
                        "(SELECT count(*) FROM sentinel_automation_cycles)").fetchone() != (0, 0):
            raise QualificationRefused("FRESH_PRIVATE_COMMAND_AND_CYCLE_NAMESPACE_REQUIRED")
        control = store.load_control(conn)
        if control.enabled or not control.kill_switch_engaged:
            raise QualificationRefused("PRIVATE_FIXTURE_MUST_START_DISABLED_AND_KILLED")
        config = scheduler_profile(args.scheduler_profile, control.config_sha256)
        bound, rollout, plan = binding.require(conn), load_rollout_state(conn), journal.latest_plan(conn)
        if plan is None or plan.effective_session != datetime.now(timezone.utc).astimezone(
                __import__("zoneinfo").ZoneInfo(calendar.EXCHANGE_TZ)).date():
            raise QualificationRefused("CURRENT_EFFECTIVE_DAY_RETAINED_PLAN_REQUIRED")
        before = [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]
        with feed_inputs.pinned(conn, commit=False) as pub:
            evidence = pub.evidence["rolling_snapshot"]
            manifest = rolling_store.manifest(conn, evidence["candidate_id"])
            if manifest.bar_count < args.minimum_bars:
                raise QualificationRefused("PRODUCTION_SIZE_INPUT_REQUIRED")
            resolver = feed_inputs.resolver(conn, pub, session=plan.effective_session.isoformat())
            proof = __import__("sentinel.dual_plan_authority", fromlist=["load_authority"]).load_authority(
                conn, plan_id=plan.plan_id)
            metadata, metadata_sha = provider_metadata(args.provider_asset_metadata)
            assets = fixture_assets(plan, proof, resolver, metadata)
        conn.rollback()
        backup_runtime_authority.require(conn, operation="private opening qualification fixture")
        # This is the sole calendar substitution. All timestamps remain real,
        # including PostgreSQL lease and durable send/recovery checkpoints.
        begin = datetime.now(timezone.utc)
        window = (begin + timedelta(seconds=300), begin + timedelta(hours=1))
        execution_window_fixture(stack, plan.effective_session, window)
        http = LocalAlpaca(account=bound.broker_account_id, cash=plan.account_cash, assets=assets, window=lambda: window)
        fixture = SimpleNamespace(certificate_sha256=rollout.certificate_sha256,
            authorization_mode="PAPER_OBSERVATION_ONLY", maximum_exposure=Decimal(1))

        def authority(reader, **_kwargs):
            require_database(reader, args, read_only=False)
            return fixture

        for owner in (automation_runtime, preparation, execution, recovery, validation):
            stack.enter_context(patch.object(owner, "require_current_authority", authority))
        stack.enter_context(patch.dict(os.environ, SENTINEL_SHADOW_OBSERVATION_ENABLED="0",
            SENTINEL_REVIEWED_DEPLOYMENT_MODE="dual", SENTINEL_FEED_SERVICE_MODE="AUTOMATION"))

        class Campaign(automation_runtime.ProductionAutomation):
            def _broker(self, reader, session):
                broker = super()._broker(reader, session)
                broker._http_provider = lambda: http
                return broker

        campaign = Campaign(sentinel_config=SentinelConfig(database_url=args.database,
            alpaca_key="opening-latency-fixture", alpaca_secret="local-only", base_url=DEFAULT_BASE_URL,
            state_dir=Path("/tmp/opening-latency"), max_cycles=1, poll_seconds=0),
            automation_config=config, holder_id="opening-latency-" + uuid.uuid4().hex)
        campaign._shadow_observation_id, campaign._shadow_starting_cash = args.observation_id, args.starting_cash
        binding_value = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
            certificate_sha256=fixture.certificate_sha256, rollout_mode=rollout.mode.value,
            rollout_version=rollout.version, config_sha256=config.fingerprint)
        store.activate(conn, binding=binding_value, actor="PRIVATE_SIMULATOR", reason="unsigned latency fixture")
        store.release_kill(conn, expected_binding=binding_value, actor="PRIVATE_SIMULATOR", reason="local HTTP only")
        permit = store.acquire_lease(conn, holder_id=campaign.holder_id, lease_seconds=config.lease_seconds)
        timing = schedule.for_decision_session(plan.decision_session, config)
        spec = CycleSpec(**timing.model_dump(), **binding_value.model_dump(), control_generation=permit.control_generation)
        cycle = store.create_cycle(conn, permit=permit, spec=spec, now=begin)
        conn.rollback()
        counts = Counter()
        for owner, name in ((rolling_runtime, "_load_closure"), (rolling_store, "_verify_content_uncached")):
            original = getattr(owner, name)
            def observed(*values, _name=name, _original=original, **kwargs):
                counts[_name] += 1
                return _original(*values, **kwargs)
            stack.enter_context(patch.object(owner, name, observed))
        try:
            def context():
                return CycleContext(cycle=cycle, permit=permit)

            def callback(phase, stage, body):
                return stages.run(stage, lambda: supervised_callback(args, config, context(), phase, body, http, counts))

            callback("RECOVER", "ProductionAutomation.recover:preflight", campaign.recover)
            cycle = transition_for_callback(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=CycleState.PREPARING)
            prepared = callback("PREPARE", "ProductionAutomation.prepare", campaign.prepare)
            cycle = transition_for_callback(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=CycleState.PLAN_READY,
                plan_id=prepared.plan_id, plan_fingerprint=prepared.plan_fingerprint,
                state_fingerprint=prepared.state_fingerprint)
            def wait_for_open():
                next_report = time.monotonic()
                next_heartbeat = time.monotonic()
                while True:
                    remaining = (cycle.execute_at - datetime.now(timezone.utc)).total_seconds()
                    if remaining <= 0:
                        break
                    if time.monotonic() >= next_heartbeat:
                        with connect(args, read_only=False, heartbeat=True) as reader:
                            store.heartbeat_lease(reader, permit=permit, lease_seconds=config.lease_seconds)
                        next_heartbeat = time.monotonic() + config.heartbeat_seconds
                    if time.monotonic() >= next_report:
                        print(json.dumps({"stage": "WAITING_OPEN", "remaining_seconds": round(remaining, 1)}), flush=True)
                        next_report = time.monotonic() + 30
                    time.sleep(min(1, remaining))
            stages.run("scheduled_open_wait:no_database_locks", wait_for_open)
            cycle = transition_for_callback(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=CycleState.EXECUTING)
            preparation_counts = dict(counts)
            counts.clear()
            http.started = time.monotonic()
            remaining_budget = (cycle.execute_at + timedelta(seconds=config.maximum_execution_lateness_seconds)
                                - datetime.now(timezone.utc)).total_seconds()
            if not 0 < remaining_budget <= config.maximum_execution_lateness_seconds:
                raise QualificationRefused("SIMULATED_EXECUTION_DID_NOT_START_IN_FRESH_WINDOW")
            sent = callback("EXECUTE", "ProductionAutomation.execute", campaign.execute)
            cycle = transition_for_callback(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=CycleState.RECONCILING)
            recovered = callback("RECOVER", "ProductionAutomation.recover:terminal", campaign.recover)
            elapsed = time.monotonic() - http.started
            projection = target_reprojection.load_projection(conn, plan_id=prepared.plan_id)
            if projection is None:
                raise QualificationRefused("SIMULATED_BASKET_HAS_NO_DURABLE_PROJECTION")
            expected = {sid: value for sid, value in projection.target_basket.items() if value}
            actual = {http.by_id[asset]["security_id"]: quantity for asset, quantity in http.positions.items() if quantity}
            commands = journal.load_commands(conn, bound.identity, plan_id=prepared.plan_id)
            if (not expected or actual != expected or recovered.disposition.value != "SUCCEEDED"
                    or not commands or len(commands) != len(http.orders)
                    or any(command.state.value != "FILLED" for command in commands)
                    or http.first_order_seconds is None):
                raise QualificationRefused("SIMULATED_GATEWAY_DID_NOT_COMPLETE_EXACT_BASKET",
                    first_order_seconds=http.first_order_seconds, complete_basket_seconds=elapsed,
                    orders=len(http.orders), expected_legs=len(expected))
            if http.first_order_seconds > 120 or elapsed > 300 or elapsed > config.maximum_execution_lateness_seconds:
                raise QualificationRefused("SIMULATED_GATEWAY_LATENCY_MARGIN_EXCEEDED",
                    first_order_seconds=http.first_order_seconds, complete_basket_seconds=elapsed,
                    orders=len(http.orders), invocations=dict(counts))
            if before != [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]:
                raise QualificationRefused("RETAINED_BOOK_CHANGED")
            cycle = store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=CycleState.SUCCEEDED,
                last_clean_reconciliation_id=recovered.last_clean_reconciliation_id)
            return {"gateway_qualified": True, "first_order_seconds": round(http.first_order_seconds, 6),
                "complete_basket_seconds": round(elapsed, 6), "legs": len(expected), "orders": len(http.orders),
                "bar_count": manifest.bar_count, "scheduler_sha256": config.fingerprint,
                "source_provider": resolver.source_provider, "provider_metadata_sha256": metadata_sha,
                "simulated_quote_feed": http.quote_feed,
                "fixture_identity_origins": {row["security_id"]: row["identity_origin"] for row in assets.values()},
                "invocations": dict(counts), "preparation_invocations": preparation_counts,
                "execution_start_remaining_budget_seconds": round(remaining_budget, 6),
                "http_methods": dict(http.requests), "book_preserved": True,
                "production_admission": False, "native_broker_calls": 0, "authority_effect": "NONE",
                "substitutions": ["unsigned certificate fixture", "local HTTP provider", "one session-window fixture"],
                "callbacks": "actual ProductionAutomation.prepare/execute/recover and public paper gateways",
                "fresh_broker_guard": "UNCHANGED", "runtime_identity_substituted": False,
                "callback_supervision": "UNCHANGED AutomationService._invoke",
                "limit": "persistent scheduler run loop qualified separately; no native transport"}
        finally:
            cleanup_private(args, preserve_failure=sys.exc_info()[0] is not None)
