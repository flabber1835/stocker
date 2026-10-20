"""Private persistent scheduler qualification with asynchronous broker evidence.

Run with the same arguments as opening_latency_qualification --mode gateway.
This is additional evidence; it never replaces the 120/300s immediate-fill gate.
Use --private-monitor in a separately bounded exact-image process concurrently.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import hashlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from tools import opening_gateway_qualification as gateway
from tools.opening_async_provider import SharedProvider
from tools.opening_latency_qualification import (
    QualificationRefused, Stages, connect, parser as common_parser,
    require_database, require_environment, require_target, reviewed_runtime,
    read_only_writer,
)


def assert_async_result(snapshot, *, expected_count, cutoff_seconds):
    """Validate observed transport and economics without inventing DAY fills."""
    orders = snapshot["orders"]
    keys = [row["client_order_id"] for row in orders]
    if (len(orders) != expected_count or len(keys) != len(set(keys))
            or snapshot["duplicate_posts"] or snapshot["late_posts"]
            or snapshot["zero_fill_acknowledgements"] != expected_count):
        raise QualificationRefused("ASYNC_INTENDED_ACKNOWLEDGEMENTS_OR_IDENTITY_FAILED")
    if (snapshot["first_order_seconds"] is None or snapshot["first_order_seconds"] > 120
            or snapshot["last_post_seconds"] is None
            or snapshot["last_post_seconds"] > cutoff_seconds):
        raise QualificationRefused("ASYNC_ORIGINAL_EXECUTION_CLOCK_EXCEEDED")
    rests = [row for row in orders if row["status"] == "new"]
    if (len(rests) != 2 or {row["client_order_id"] for row in rests}
            != set(snapshot["resting_client_keys"])
            or any(row["status"] not in {"new", "filled"} for row in orders)
            or snapshot["pending_visibility"]):
        raise QualificationRefused("ASYNC_EXPECTED_RESTING_AND_RECONCILED_FILL_STATE_FAILED")
    spent = sum((Decimal(row["filled_qty"]) * Decimal(row["filled_avg_price"])
                 for row in orders if row["filled_avg_price"] is not None), Decimal(0))
    reserved = sum((Decimal(row["qty"]) * Decimal(row["limit_price"]) for row in rests), Decimal(0))
    if (Decimal(snapshot["initial_cash"]) - spent != Decimal(snapshot["cash"])
            or Decimal(snapshot["reserved_cash"]) != reserved
            or Decimal(snapshot["buying_power"]) != max(Decimal(0), Decimal(snapshot["cash"])-reserved)
            or not snapshot["cash_ahead_observations"] or not snapshot["partial_order_observations"]):
        raise QualificationRefused("ASYNC_CASH_RESERVATION_OR_VISIBILITY_NOT_PROVEN")


def monitor_stamp(args):
    """Read identities only; expensive canonical observers run between stamps."""
    from sentinel.panel import sources
    from sentinel.automation import store
    with connect(args) as reader:
        current = store.latest_cycle(reader)
        cycle = current.model_dump(mode="json") if current is not None else None
        if cycle is not None:
            for key in ("retry_phase", "protected_day_wait", "continuation_reason", "original_execution_deadline_at"):
                cycle[key] = current.diagnostic.get(key)
        account = sources._latest_account_evidence(reader)
        reader.rollback()
    return cycle, account


def observation_stable(before, after):
    def encoded(value):
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return encoded(before) == encoded(after)


def monitor_row(row, observed_at):
    """Use the exact effective projection that colors the real dashboard."""
    return {"key": row.key, "status": row.effective_status(observed_at), "value": row.value,
            "raw_status": row.status}


def window_path(args):
    return (args.execution_window_evidence if args.execution_window_evidence is not None else
            args.monitor_evidence.with_name(args.monitor_evidence.stem + "-window.json"))


def write_window_evidence(args, *, session, window):
    value = {"schema": "sentinel.private-execution-window/1",
        "database": args.expected_database, "system_id": args.expected_system_id,
        "runtime_image_digest": args.runtime_image_digest,
        "source_revision": os.environ["SENTINEL_IMAGE_SOURCE_REVISION"],
        "effective_session": str(session), "opened": window[0].isoformat(), "closed": window[1].isoformat()}
    with window_path(args).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
    return value


def validate_window_evidence(args, value):
    expected = {"schema": "sentinel.private-execution-window/1",
        "database": args.expected_database, "system_id": args.expected_system_id,
        "runtime_image_digest": args.runtime_image_digest,
        "source_revision": os.environ["SENTINEL_IMAGE_SOURCE_REVISION"]}
    if (set(value) != set(expected) | {"effective_session", "opened", "closed"}
            or any(value.get(key) != item for key, item in expected.items())):
        raise QualificationRefused("CONCURRENT_MONITOR_WINDOW_IDENTITY_MISMATCH")
    opened, closed = datetime.fromisoformat(value["opened"]), datetime.fromisoformat(value["closed"])
    if (opened.tzinfo is None or closed.tzinfo is None
            or not timedelta(seconds=600) < closed-opened <= timedelta(hours=1)):
        raise QualificationRefused("CONCURRENT_MONITOR_WINDOW_INVALID")
    return opened, closed


def join_monitor_window(scope, args):
    from sentinel.execution import journal
    from sentinel.feed import calendar
    from zoneinfo import ZoneInfo
    deadline = time.monotonic() + 180
    while not window_path(args).exists():
        if args.stop_file.exists() or time.monotonic() >= deadline:
            raise QualificationRefused("CONCURRENT_MONITOR_WINDOW_UNAVAILABLE")
        time.sleep(1)
    value = json.loads(window_path(args).read_text(encoding="utf-8"))
    window = validate_window_evidence(args, value)
    with connect(args) as reader:
        plan = journal.latest_plan(reader)
        if (plan is None or value["effective_session"] != str(plan.effective_session)
                or plan.effective_session != datetime.now(timezone.utc).astimezone(ZoneInfo(calendar.EXCHANGE_TZ)).date()):
            raise QualificationRefused("CONCURRENT_MONITOR_WINDOW_SESSION_MISMATCH")
        gateway.require_source_frontier(plan)
    gateway.execution_window_fixture(scope, plan.effective_session, window)


@contextmanager
def persistent_reviewed_runtime(conn, args):
    """One fixed private process budget, independent of all trading deadlines."""
    from sentinel import retained_go, rolling_checkpoint
    deadline = datetime.now(timezone.utc) + timedelta(minutes=30)
    # Reuse every ordinary image/admission guard before applying the selected
    # private process budget. It is computed once and never renewed by a retry.
    with reviewed_runtime(conn, args) as context:
        checkpoint = rolling_checkpoint.read(conn)
        with retained_go.reviewed_process(context,
                data_publication_sha256=checkpoint.runtime_identity["validated_data_publication_sha256"],
                deadline=deadline):
            yield context


def require_positive_pending_health(observation):
    from sentinel.panel import model
    if not observation["stable_evidence"]:
        return False
    cycle = observation.get("cycle") or {}
    ready = (cycle.get("retry_phase") == "EXECUTE" and not cycle.get("failure_code")
             and not cycle.get("failure_detail")
             and (cycle.get("continuation_reason") or {}).get("code") == "PROTECTED_COHORT_READY")
    known = (ready or cycle.get("protected_day_wait") and not cycle.get("failure_code")
             and not cycle.get("failure_detail"))
    if not known:
        return False
    required = {"alpaca_account", "automation_cycle", "automation_step_transport"}
    relevant = [row for row in observation["rows"] if row["key"] in required]
    keys = [row["key"] for row in relevant]
    if set(keys) != required or len(keys) != len(required):
        raise QualificationRefused("ASYNC_POSITIVE_COHORT_HEALTH_ROWS_INCOMPLETE")
    allowed = {model.OK, model.WARN, model.PENDING}
    if any(row["status"] not in allowed for row in relevant):
        raise QualificationRefused("ASYNC_POSITIVE_COHORT_DISPLAYED_FAILED",
            failed_rows=[row["key"] for row in relevant if row["status"] not in allowed])
    return any(row["key"] == "alpaca_account" and row["status"] == model.OK
               for row in relevant)


def contention_fixture(stack, *, args, provider, expected_count):
    """Inject one independent owner exactly at the real recovery lock boundary."""
    from sentinel.execution import journal
    original = journal.writer_lock

    @contextmanager
    def observed(connection, **kwargs):
        caller = sys._getframe(2).f_globals.get("__name__")
        if (caller == "sentinel.paper.recovery" and kwargs.get("recovery_only")
                and provider.proxy.claim_contention(expected_count)):
            with connect(args) as holder, read_only_writer(holder, journal.WRITER_LOCK_KEY):
                with original(connection, **kwargs):
                    raise QualificationRefused("INJECTED_WRITER_COLLISION_WAS_NOT_REFUSED")
            raise QualificationRefused("INJECTED_WRITER_COLLISION_WAS_NOT_REFUSED")
        with original(connection, **kwargs):
            yield

    stack.enter_context(patch.object(journal, "writer_lock", observed))


def run_monitor(args):
    """Canonical panel reads in a separately resource-limited private sidecar."""
    import sentinel
    from sentinel.panel import sources, verification_monitor
    require_environment(os.environ, sentinel.__file__)
    require_target(args)
    if args.stop_file is None:
        raise QualificationRefused("PRIVATE_MONITOR_STOP_FILE_REQUIRED")
    monitor = verification_monitor.Monitor()
    scope = ExitStack()
    observations, history, started = 0, [], time.monotonic()
    try:
        reader = scope.enter_context(connect(args))
        scope.enter_context(persistent_reviewed_runtime(reader, args))
        reader.rollback()
        join_monitor_window(scope, args)
        monitor.start(args.database, include_paper=True)
        while not args.stop_file.exists():
            if time.monotonic() - started > 1800:
                raise QualificationRefused("PRIVATE_MONITOR_DEADLINE_EXCEEDED")
            before = monitor_stamp(args)
            observed_at = datetime.now(timezone.utc)
            operator, _ = sources._operator_evidence_rows(args.database, now=observed_at)
            automation, _ = sources._automation_rows(args.database)
            after = monitor_stamp(args)
            observations += 1
            value = {"schema": "sentinel.private-concurrent-monitor/1", "observations": observations,
                "observed_at": observed_at.isoformat(),
                "rows": [monitor_row(row, observed_at)
                         for row in [*operator, *automation]
                         if row.key in {"alpaca_account", "automation_cycle", "automation_step_transport"}],
                "background_monitor_running": monitor.thread is not None and monitor.thread.is_alive(),
                "stable_evidence": observation_stable(before, after),
                "cycle": {key: (after[0] or {}).get(key) for key in (
                    "cycle_id", "state", "failure_code", "failure_detail", "updated_at", "protected_day_wait",
                    "retry_phase", "continuation_reason", "original_execution_deadline_at")},
                "native_broker_calls": 0, "authority_effect": "NONE"}
            history.append({key: value[key] for key in (
                "observed_at", "rows", "stable_evidence", "cycle")})
            value["history"] = history[-160:]
            history = history[-160:]
            temporary = args.monitor_evidence.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, default=str), encoding="utf-8")
            temporary.replace(args.monitor_evidence)
            time.sleep(5)
    finally:
        monitor.stop()
        scope.close()
    return {"observations": observations, "native_broker_calls": 0, "authority_effect": "NONE"}


async def run_scheduler(campaign, *, args, expected_count, provider, original_cutoff, stages):
    """Observe the real persistent loop; never manually transition its cycle."""
    from sentinel.automation import store
    stop = asyncio.Event()
    evidence = {"cash_before_journal": False, "known_waits": 0, "after_cutoff_waits": 0,
                "monitor_observations": 0, "contention_injected": False, "pending_health_observed": False,
                "contention_failure_observed": False}
    stop_deadline = original_cutoff + timedelta(seconds=360)
    wait_observations, after_cutoff_observations = set(), set()
    previous_commands = {}
    fixed_basis = {}

    async def observe():
        while not stop.is_set():
            now = datetime.now(timezone.utc)
            current_pending_health = False
            snapshot = provider.proxy.snapshot()
            if snapshot.get("contention_started_at"):
                evidence["contention_injected"] = True
                evidence["contention_started_at"] = snapshot["contention_started_at"]
            with connect(args) as reader:
                cycle = store.latest_cycle(reader)
                commands = reader.execute("SELECT client_key,quantity::text,order_terms,filled_quantity::text "
                                          "FROM sentinel_commands ORDER BY client_key").fetchall()
                bases = reader.execute("SELECT cursor_name,state FROM sentinel_processed_sessions "
                                       "WHERE cursor_name LIKE 'protected-buy-funding:v1:%' ORDER BY cursor_name").fetchall()
                events = (reader.execute("SELECT detail FROM sentinel_automation_cycle_events WHERE cycle_id=%s",
                                         (cycle.cycle_id,)).fetchall() if cycle is not None else [])
                reader.rollback()
            if evidence["contention_injected"]:
                for (detail,) in events:
                    encoded = json.dumps(detail, sort_keys=True)
                    if "TransientInfrastructureFailure" in encoded and "lock" in encoded.lower():
                        evidence["contention_failure_observed"] = True
            for key, value in bases:
                encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
                if fixed_basis and (key not in fixed_basis or fixed_basis[key] != encoded):
                    raise QualificationRefused("ASYNC_FIXED_FUNDING_BASIS_CHANGED")
                fixed_basis[key] = encoded
            for key, quantity, terms, _filled in commands:
                immutable = (quantity, json.dumps(terms, sort_keys=True))
                if key in previous_commands and previous_commands[key] != immutable:
                    raise QualificationRefused("ASYNC_DURABLE_TERMS_CHANGED")
                previous_commands[key] = immutable
            if (Decimal(snapshot["cash"]) < Decimal(snapshot["initial_cash"])
                    and all(Decimal(row[3]) == 0 for row in commands)):
                evidence["cash_before_journal"] = True
            if cycle is not None:
                if cycle.state.value in {"BLOCKED", "SUPERSEDED", "MISSED_STATE_ONLY", "SUCCEEDED"}:
                    raise QualificationRefused("ASYNC_WORKING_ORDERS_BECAME_TERMINAL",
                        cycle_state=cycle.state.value, failure_code=cycle.failure_code)
                wait = cycle.diagnostic.get("protected_day_wait")
                if wait:
                    identity = (wait["observation_id"], wait["observed_at"])
                    wait_observations.add(identity)
                    evidence["known_waits"] = len(wait_observations)
                    if datetime.fromisoformat(wait["observed_at"]) >= original_cutoff:
                        after_cutoff_observations.add(identity)
                        evidence["after_cutoff_waits"] = len(after_cutoff_observations)
            if args.monitor_evidence.exists():
                monitor = json.loads(args.monitor_evidence.read_text(encoding="utf-8"))
                if (monitor.get("background_monitor_running")
                        and 0 <= (now-datetime.fromisoformat(monitor["observed_at"])).total_seconds() <= 30):
                    evidence["monitor_observations"] = max(evidence["monitor_observations"], monitor["observations"])
                    for observation in monitor.get("history", []):
                        require_positive_pending_health(observation)
                    current_pending_health = require_positive_pending_health(monitor)
                    if current_pending_health:
                        evidence["pending_health_observed"] = True
                        evidence["pending_health_evidence"] = monitor
            if (evidence["after_cutoff_waits"] >= 2 and evidence["known_waits"] >= 3
                    and len(snapshot["orders"]) == expected_count and not snapshot["pending_visibility"]
                    and current_pending_health
                    and cycle is not None and cycle.diagnostic.get("protected_day_wait")
                    and (not evidence.get("contention_started_at") or datetime.fromisoformat(
                        cycle.diagnostic["protected_day_wait"]["observed_at"]) > datetime.fromisoformat(
                            evidence["contention_started_at"]))):
                assert_async_result(snapshot, expected_count=expected_count,
                                    cutoff_seconds=campaign.automation_config.maximum_execution_lateness_seconds)
                if (not evidence["cash_before_journal"] or not evidence["monitor_observations"]
                        or not evidence["pending_health_observed"] or not evidence["contention_injected"]
                        or not evidence["contention_failure_observed"] or len(fixed_basis) != 1):
                    raise QualificationRefused("ASYNC_COMPOSED_EVIDENCE_INCOMPLETE", **evidence)
                evidence["provider"] = snapshot
                evidence["fixed_funding_state_sha256"] = hashlib.sha256(
                    next(iter(fixed_basis.values())).encode()).hexdigest()
                evidence["final_cycle"] = cycle.model_dump(mode="json")
                stop.set()
                return
            if now > stop_deadline:
                raise QualificationRefused("ASYNC_PERSISTENT_CAMPAIGN_DEADLINE_EXCEEDED", **evidence)
            await asyncio.sleep(1)

    scheduler = asyncio.create_task(campaign.run(stop=stop))
    observer = asyncio.create_task(observe())
    try:
        done, _ = await asyncio.wait({scheduler, observer}, return_when=asyncio.FIRST_COMPLETED)
        if observer in done:
            await observer
            await scheduler
        else:
            await scheduler
            raise QualificationRefused("ASYNC_PERSISTENT_SCHEDULER_ENDED_EARLY")
    finally:
        stop.set()
        for task in (observer, scheduler):
            if not task.done():
                task.cancel()
        await asyncio.gather(observer, scheduler, return_exceptions=True)
    return evidence


def qualify(args, stages):
    import sentinel
    from sentinel import automation_runtime, backup_runtime_authority, binding
    from sentinel import rolling_checkpoint, rolling_daily_checkpoint
    from sentinel.authority import load_rollout_state
    from sentinel.automation import schedule, store
    from sentinel.automation.model import ControlBinding
    from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
    from sentinel.execution import feed_inputs, journal, target_reprojection
    from sentinel.feed import calendar, rolling_store
    from sentinel.paper import execution, preparation, recovery, validation
    require_environment(os.environ, sentinel.__file__)
    require_target(args)
    policy = gateway.require_protected_policy()
    if args.profile or args.mode != "gateway" or args.monitor_evidence is None:
        raise QualificationRefused("PERSISTENT_PRIVATE_GATEWAY_AND_MONITOR_REQUIRED")
    with connect(args, read_only=False) as conn, persistent_reviewed_runtime(conn, args), ExitStack() as stack:
        if conn.execute("SELECT (SELECT count(*) FROM sentinel_commands),"
                        "(SELECT count(*) FROM sentinel_automation_cycles)").fetchone() != (0, 0):
            raise QualificationRefused("FRESH_PRIVATE_COMMAND_AND_CYCLE_NAMESPACE_REQUIRED")
        control = store.load_control(conn)
        if control.enabled or not control.kill_switch_engaged:
            raise QualificationRefused("PRIVATE_FIXTURE_MUST_START_DISABLED_AND_KILLED")
        config = gateway.scheduler_profile(args.scheduler_profile, control.config_sha256)
        bound, rollout, plan = binding.require(conn), load_rollout_state(conn), journal.latest_plan(conn)
        if plan is None or plan.effective_session != datetime.now(timezone.utc).astimezone(
                __import__("zoneinfo").ZoneInfo(calendar.EXCHANGE_TZ)).date():
            raise QualificationRefused("CURRENT_EFFECTIVE_DAY_RETAINED_PLAN_REQUIRED")
        gateway.require_source_frontier(plan)
        before = [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]
        with feed_inputs.pinned(conn, commit=False) as pub:
            manifest = rolling_store.manifest(conn, pub.evidence["rolling_snapshot"]["candidate_id"])
            if manifest.bar_count < args.minimum_bars:
                raise QualificationRefused("PRODUCTION_SIZE_INPUT_REQUIRED")
            resolver = feed_inputs.resolver(conn, pub, session=plan.effective_session.isoformat())
            proof = __import__("sentinel.dual_plan_authority", fromlist=["load_authority"]).load_authority(
                conn, plan_id=plan.plan_id)
            metadata, metadata_sha = gateway.provider_metadata(args.provider_asset_metadata)
            assets = gateway.fixture_assets(plan, proof, resolver, metadata)
        conn.rollback()
        backup_runtime_authority.require(conn, operation="private asynchronous qualification")
        begin = datetime.now(timezone.utc)
        window = (begin + timedelta(seconds=420), begin + timedelta(hours=1))
        write_window_evidence(args, session=plan.effective_session, window=window)
        gateway.execution_window_fixture(stack, plan.effective_session, window)
        provider, manager = SharedProvider.start(account=bound.broker_account_id, cash=plan.account_cash,
            assets=assets, opened=window[0], closed=window[1], latency_seconds=args.provider_latency_seconds)
        contention_fixture(stack, args=args, provider=provider, expected_count=len(assets))
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
                broker._http_provider = lambda: provider
                return broker

        campaign = Campaign(sentinel_config=SentinelConfig(database_url=args.database,
            alpaca_key="opening-latency-fixture", alpaca_secret="local-only", base_url=DEFAULT_BASE_URL,
            state_dir=Path("/tmp/opening-latency"), max_cycles=1, poll_seconds=0),
            automation_config=config, holder_id="opening-persistent-" + uuid.uuid4().hex)
        campaign._shadow_observation_id, campaign._shadow_starting_cash = args.observation_id, args.starting_cash
        binding_value = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
            broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
            certificate_sha256=fixture.certificate_sha256, rollout_mode=rollout.mode.value,
            rollout_version=rollout.version, config_sha256=config.fingerprint)
        store.activate(conn, binding=binding_value, actor="PRIVATE_SIMULATOR", reason="unsigned persistent fixture")
        store.release_kill(conn, expected_binding=binding_value, actor="PRIVATE_SIMULATOR", reason="local provider only")
        conn.rollback()
        timing = schedule.for_decision_session(plan.decision_session, config)
        cutoff = min(timing.execution_close_at, timing.execute_at + timedelta(seconds=config.maximum_execution_lateness_seconds))
        try:
            result = stages.run("ProductionAutomation.run:persistent_async", lambda: asyncio.run(run_scheduler(
                campaign, args=args, expected_count=len(assets), provider=provider,
                original_cutoff=cutoff, stages=stages)))
            final = store.latest_cycle(conn)
            projection = target_reprojection.load_projection(conn, plan_id=final.plan_id)
            expected = {key: value for key, value in projection.target_basket.items() if value}
            rows = result["provider"]["orders"]
            actual = {provider_id: Decimal(row["qty"]) for row in rows for provider_id in
                      [next(item["security_id"] for item in assets.values() if item["id"] == row["asset_id"])]}
            if actual != expected:
                raise QualificationRefused("ASYNC_INTENDED_ORDER_BASKET_DIFFERS")
            if before != [reader.read(conn) for reader in (rolling_checkpoint, rolling_daily_checkpoint)]:
                raise QualificationRefused("RETAINED_BOOK_CHANGED")
            if result["provider"]["requests"].get("GET /v2/stocks/quotes/latest", 0):
                raise QualificationRefused("ASYNC_PROTECTED_QUOTE_GET")
            return {"persistent_gateway_qualified": True, "immediate_fill_baseline_replaced": False,
                "scenario": "ZERO_FILL_ACK_CASH_AHEAD_PARTIAL_VISIBILITY_TWO_RESTING_DAY",
                "scheduler_sha256": config.fingerprint, "policy_sha256": policy.fingerprint(),
                "provider_response_latency_floor_seconds": provider.latency_seconds,
                "provider_latency_scope": "selected local response floor; no native latency guarantee",
                "private_reviewed_context_minutes": 30,
                "concurrency_scope": "canonical panel reads and verification monitor; explicit writer collision",
                "bar_count": manifest.bar_count, "provider_metadata_sha256": metadata_sha,
                "book_preserved": True, "native_broker_calls": 0, "production_admission": False,
                "substitutions": ["unsigned certificate fixture", "shared delayed local provider",
                    "one session-window fixture", "one independent writer collision at the actual recovery lock"],
                "runtime_identity_substituted": False,
                "persistent_scheduler": "unchanged ProductionAutomation.run and AutomationService.run/tick/_invoke",
                "fresh_broker_guard": "UNCHANGED",
                "authority_effect": "NONE", **result}
        finally:
            if args.stop_file is not None:
                args.stop_file.touch(exist_ok=True)
            manager.shutdown()
            gateway.cleanup_private(args, preserve_failure=sys.exc_info()[0] is not None)


def main(argv=None):
    parser = common_parser()
    parser.add_argument("--private-monitor", action="store_true")
    parser.add_argument("--monitor-evidence", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--provider-latency-seconds", type=float, default=0.5)
    parser.add_argument("--execution-window-evidence", type=Path)
    args = parser.parse_args(argv)
    stages, started = Stages(), time.monotonic()
    report = {"schema": "sentinel.opening-persistent-qualification/1", "result": "REFUSED",
              "observed_at": datetime.now(timezone.utc).isoformat()}
    with args.output.open("x", encoding="utf-8") as stream:
        try:
            if args.stop_file.exists():
                raise QualificationRefused("FRESH_PRIVATE_STOP_FILE_REQUIRED")
            report.update((run_monitor if args.private_monitor else lambda value: qualify(value, stages))(args))
            report["result"] = "PASS"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            if isinstance(exc, QualificationRefused):
                report.update(refusal=str(exc), **exc.metrics)
        finally:
            report.update(seconds=round(time.monotonic()-started, 6), stages=stages.rows)
            json.dump(report, stream, indent=2)
            stream.write("\n")
    print(json.dumps({key: report[key] for key in ("result", "seconds")}))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
