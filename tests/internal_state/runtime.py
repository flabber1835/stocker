"""One real SQL lifecycle composed with existing, process-external simulators.

This is a synthetic assembly lab. GO, signed deployment authority and candidate
Alpaca capability certification remain exercised by their existing safety suites.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
import json
import multiprocessing
import os
from pathlib import Path
import signal
import shutil
import subprocess
import traceback
from types import SimpleNamespace

from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runner import observed_corpus
from research.sharadar_replay.runtime import simulated_runtime
from scripts import sentinel_env
from sentinel import backup_runtime_authority, binding, schema
from sentinel.authority import RolloutMode, RolloutState, PAPER_OBSERVATION_ONLY
from sentinel.core import cashflow, catchup, production
from sentinel.core.decision import build_execution_plan
from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from sentinel.execution import alpaca, broker_cash, executor, journal, reconcile
from sentinel.feed import calendar, ingest, publication, readiness, sharadar, store
from sentinel.paper.preparation import _default_paper_strategy, _fresh_warmed_state, _load_marks_and_tickers

from . import broker, market, oracles
from .market import compare_corpus
from .contract import InvalidTrace, InvariantFailure, check, digest
from .physical import PhysicalCluster, ROOT


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (Decimal, date, Path)):
        return str(value)
    return value


def write(path, value):
    path.write_text(json.dumps(plain(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def environment(path, root):
    values = {
        "SENTINEL_BACKUP_DIR": str(root), "SENTINEL_POSTGRES_PASSWORD": "syntheticpassword",
        "SHARADAR_API_KEY": "synthetic-market-only", "ALPACA_API_KEY": "simulation-key",
        "ALPACA_SECRET_KEY": "simulation-secret", "ALPACA_BASE_URL": broker.PAPER_URL,
        "SENTINEL_AUTOMATION_ALERT_WEBHOOK_URL": "https://alerts.example.test/synthetic",
        "SENTINEL_PUBLICATION_RECEIPT_KEY": "synthetic-publication-receipt-" * 3,
    }
    content = ("\ufeff" + "\r\n".join(f"{k}={v}" for k, v in values.items()) + "\r\n").encode()
    path.write_bytes(content)
    return content


def startup(path):
    values = sentinel_env.load(path, required=True)
    sentinel_env.validate(values, profile="install", target="DUAL_RUN_OBSERVATION")


def command_dict(command):
    return plain(asdict(command)) | {"client_key": command.client_key}


async def execute(dsn, service, *, kill=False):
    adapter = broker.adapter(service, kill_after_accept=kill)
    with store.connect(dsn) as conn:
        bound = binding.require(conn)
        plan = journal.latest_plan(conn)
        if plan is None:
            raise InvalidTrace("execution requires a current plan")
        reverse = {sid: symbol for symbol, sid in market.SECURITIES.items()}
        instruments = {sid: await adapter.resolve_instrument(security_id=sid, symbol=reverse[sid])
                       for sid in plan.target_basket}
        return await executor.execute_session(broker=adapter, conn=conn,
            deployment=bound.identity, plan=plan, instruments=instruments,
            today=datetime.fromisoformat(service.now()).date(), settle_cycles=0)


def child_execute(dsn, service, base, wal, kill, result):
    # Spawn gets no parent's open SQL connections or monkeypatch state.
    from unittest.mock import patch
    from sentinel import backup_guard
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(backup_runtime_authority, "BASE_ROOT", base))
            stack.enter_context(patch.object(backup_runtime_authority, "WAL_ROOT", wal))
            stack.enter_context(patch.object(backup_guard, "BACKUP_WAL_MOUNT", wal))
            stack.enter_context(patch.dict(os.environ, {
                backup_runtime_authority.AUTHORITY_ENV: backup_runtime_authority.AUTHORITY_VALUE}))
            result.put({"result": plain(asyncio.run(execute(dsn, service, kill=kill)))})
    except Exception:
        result.put({"error": traceback.format_exc()})
        raise


def child_catchup(dsn, service, base, wal, missed, result):
    from unittest.mock import patch
    from sentinel import backup_guard
    lab = object.__new__(Lifecycle)
    lab.cluster = SimpleNamespace(dsn=dsn)
    lab.service = service
    lab.config, lab.identity = _default_paper_strategy()
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(backup_runtime_authority, "BASE_ROOT", base))
            stack.enter_context(patch.object(backup_runtime_authority, "WAL_ROOT", wal))
            stack.enter_context(patch.object(backup_guard, "BACKUP_WAL_MOUNT", wal))
            stack.enter_context(patch.dict(os.environ, {
                backup_runtime_authority.AUTHORITY_ENV: backup_runtime_authority.AUTHORITY_VALUE}))
            with store.connect(dsn) as conn:
                def advance(connection, day, prior):
                    if day == missed[1]:
                        # The previous loop iteration committed its progress.
                        # SIGKILL exercises the server's transaction cleanup.
                        os.kill(os.getpid(), signal.SIGKILL)
                    return lab.advance(connection, day, prior)
                catchup.catch_up(conn, through=missed[-1], missed=missed,
                    advance_state=advance, decide=lambda d, s: lab.decide(conn, d, s))
    except Exception:
        result.put({"error": traceback.format_exc()})
        raise


class Lifecycle:
    def __init__(self, trace, output):
        self.trace, self.output = trace, output
        self.cluster = None
        self.manager = None
        self.stack = ExitStack()
        self.provider = Provider(page_size=197, variation_seed=trace.seed)
        self.config, self.identity = _default_paper_strategy()
        self.commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        self.day = market.SEED
        self.last_state = None
        self.reference = None
        self.economics = {}
        self.coverage = set()
        self.saved = None
        self.media_saved = None
        self.wal_saved = None
        self.env_bad = False
        self.data_bad = False
        self.shocks = []
        self.restored = False
        self.records = []
        self.action_index = -1

    def __enter__(self):
        try:
            self.cluster = PhysicalCluster()
            self.cluster.start()
            self.stack.enter_context(self.cluster.runtime())
            self.manager, self.service = broker.manager(self.trace.profile)
            self.stack.enter_context(simulated_runtime(self.provider, commit=self.commit))
            self.env_path = self.cluster.root / "synthetic.env"
            self.env_bytes = environment(self.env_path, self.cluster.root)
            startup(self.env_path)
            self.provider.advance(market.step(self.day, self.trace.seed))
            with self.connection() as conn:
                schema.ensure_schema(conn)
                store.migrate_schema(conn)
                binding.bind(conn, deployment_id="integrated-state-lab", broker="alpaca",
                             broker_account_id="SIM-ALPACA-1", notes="synthetic test-only fixture")
                # Fixture ownership predates simulated broker history. This is
                # creation of the disposable model, not a production takeover.
                conn.execute("UPDATE sentinel_account_binding SET established_at=%s,updated_at=%s WHERE id=1",
                    (self.provider.step.at - timedelta(days=1), self.provider.step.at - timedelta(days=1)))
                conn.commit()
                # Record the actual physical DB identity before any populated
                # checkpoint, using the production incarnation recorder.
                alpaca.database_incarnation(conn)
                ingest.seed(conn, date_from=market.START, date_to=self.day,
                            fetch=lambda *a, **kw: sharadar.fetch_table(*a, **kw))
                compare_corpus(self.provider.step.expected, observed_corpus(conn))
                self.coverage.update({"startup", "production_seed", "physical_archive"})
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.cluster is not None and (self.cluster.root / "postgres.log").is_file():
            shutil.copy2(self.cluster.root / "postgres.log", self.output / "postgres.log")
        self.stack.close()
        if self.manager is not None:
            self.manager.shutdown()
        if self.cluster is not None:
            self.cluster.close()

    def connection(self):
        return store.connect(self.cluster.dsn, statement_timeout_ms=30000)

    def snapshot(self):
        with self.connection() as conn:
            row = conn.execute("SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name='catchup'").fetchone()
            raw = row[1] if row else None
            bound = binding.require(conn)
            plan = journal.latest_plan(conn)
            commands = journal.load_commands(conn, bound.identity)
            return {"state": raw, "cursor": str(row[0]) if row else None,
                "plan": plain(plan.to_dict()) if plan else None,
                "commands": [command_dict(c) for c in commands],
                "histories": plain({c.client_key: journal.command_history(conn, c.client_key) for c in commands}),
                "publication": publication.require_current(conn).version,
                "binding": bound.to_dict(), "broker": self.service.snapshot()}

    def invariants(self, snapshot):
        oracles.broker_accounting(snapshot["broker"])
        oracles.journal_contract(snapshot["commands"], snapshot["histories"], snapshot["broker"], self.economics)
        raw = snapshot["state"]
        if raw:
            oracles.canonical_state(raw, identity=self.identity, cursor=snapshot["cursor"])
            if snapshot["plan"]:
                oracles.plan_commitment(raw, snapshot["plan"], snapshot["cursor"])
            self.coverage.add("canonical_state")
            if any(slot["occupied_by"] for slot in raw["wealth_core"]["slots"].values()):
                self.coverage.add("populated_wealth_core")
            if raw["recent_leadership"]["session_history"]:
                self.coverage.add("populated_witness")
            self.coverage.add("persisted_ldrc")
            if raw["last_decision"]["target_core_exposure"] < 1:
                self.coverage.add("controller_reduced_exposure")
        if snapshot["commands"]:
            self.coverage.add("durable_commands")
        if snapshot["broker"]["fills"]:
            self.coverage.add("broker_fills")

    def decide(self, conn, day, raw):
        adapter = broker.adapter(self.service)
        account = asyncio.run(adapter.account_snapshot())
        observation = asyncio.run(adapter.observe())
        state = SessionState.from_dict(raw)
        with publication.pinned(conn, commit=False) as pub:
            marks, tickers = _load_marks_and_tickers(conn, state, day)
            # A model input to the pure assembler, never installed as signed
            # deployment authority and never passed to an operational GO path.
            result = build_execution_plan(state, binding.require(conn), pub, account,
                observation, marks, tickers, date.fromisoformat(day),
                date.fromisoformat(calendar.next_session(day)),
                rollout_state=RolloutState(RolloutMode.CONTROLLER, 1, "synthetic-test-only"))
        return result.plan

    def advance(self, conn, day, prior):
        return production.advance_and_persist(conn, day, prior,
            load_published=production.load_published_session, controller_config=self.config,
            strategy_identity=self.identity, commit_pin=False)

    def daily(self):
        startup(self.env_path)
        day = calendar.next_session(self.day)
        self.provider.advance(market.step(day, self.trace.seed, faulty=self.data_bad,
            shocks=self.shocks, observed_after=self.provider.step.at))
        before = self.snapshot()
        with self.connection() as conn:
            try:
                ingest.daily(conn, today=day)
            except sharadar.SharadarRequestError as exc:
                conn.rollback()
                if not self.data_bad:
                    raise
                check("scheduled_data_failure_reached", True, "HTTP 400" in str(exc))
                after = self.snapshot()
                check("failed_publication_is_atomic", before["publication"], after["publication"])
                oracles.unchanged("failed_publication_preserves_strategy", before["state"], after["state"])
                self.coverage.add("interrupted_publication")
                return
            check("bad_data_must_refuse", False, self.data_bad)
            compare_corpus(self.provider.step.expected, observed_corpus(conn))
            self.provider.assert_revisions_applied()
            report = readiness.check_readiness(conn, today=self.provider.step.at.isoformat())
            check("published_data_ready", [], [vars(c) for c in report.failures])
            self.day = day
            self.service.move(self.provider.step.at.isoformat())
            self.service.prices({row[2]: str(row[4]) for row in self.provider.step.expected.bars if row[1] == day}
                                | {"BIL": str(self.provider.step.expected.defensive[-1][-1])})
            prior = catchup.resume_state(conn)
            if prior is None:
                prior = _fresh_warmed_state(conn, through=day, count=127,
                    account=asyncio.run(broker.adapter(self.service).account_snapshot()),
                    controller_config=self.config, strategy_identity=self.identity,
                    publication_version=publication.require_current(conn).version,
                    authorization_mode=PAPER_OBSERVATION_ONLY).to_dict()
            published = production.load_published_session(conn, day,
                known_feed_security_ids=tuple(prior["feed"]["series"]))
            # Canonical differential replay is recorded separately from the
            # independent accounting and structural oracles above.
            reference = advance_session(SessionState.from_dict(prior), published,
                controller_config=self.config, strategy_identity=self.identity).to_dict()
            result = catchup.catch_up(conn, through=day, missed=[day], state=prior,
                advance_state=self.advance, decide=lambda d, s: self.decide(conn, d, s))
            oracles.unchanged("kernel_persistence_equivalence", reference, result.state)
            self.reference = reference
            self.coverage.update({"production_daily", "production_kernel", "production_plan", "kernel_differential"})

    def execution_window(self):
        with self.connection() as conn:
            plan = journal.latest_plan(conn)
        if plan is None:
            raise InvalidTrace("execution action needs a prepared plan")
        opened, _ = calendar.session_window(plan.effective_session)
        desired = opened + timedelta(minutes=1)
        if desired > datetime.fromisoformat(self.service.now()):
            self.service.move(desired.isoformat())

    def execute(self):
        startup(self.env_path)
        self.execution_window()
        before_orders = self.service.snapshot()["orders"]
        result = asyncio.run(execute(self.cluster.dsn, self.service))
        if self.restored:
            after_orders = self.service.snapshot()["orders"]
            check("restored_incarnation_cannot_increase", [], [key for key, order in after_orders.items()
                if key not in before_orders and order["side"] == "buy"])
            with self.connection() as conn:
                bound = binding.require(conn)
                reason = alpaca.execution_increase_fence_reason(conn=conn, deployment=bound.identity,
                    today=datetime.fromisoformat(self.service.now()).date())
            check("restore_requires_explicit_takeover", True, "incarnation/timeline changed" in reason)
            self.coverage.add("restore_increases_fenced")
        self.coverage.add("production_executor")
        return plain(result)

    def reconcile(self):
        with self.connection() as conn:
            with journal.writer_lock(conn, recovery_only=True):
                bound = binding.require(conn)
                result = asyncio.run(reconcile.reconcile(broker=broker.adapter(self.service),
                    conn=conn, binding=bound, deployment=bound.identity))
        self.coverage.add("production_reconciliation")
        return plain(result)

    def child(self, *, kill=False, compete=False):
        self.execution_window()
        context = multiprocessing.get_context("spawn")
        result = context.Queue()
        process = context.Process(target=child_execute,
            args=(self.cluster.dsn, self.service, str(self.cluster.base_root),
                  str(self.cluster.wal_root), kill, result))
        with self.connection() as conn, ExitStack() as held:
            if compete:
                held.enter_context(journal.writer_lock(conn))
            process.start()
            process.join(45)
            if process.is_alive():
                process.kill()
                process.join(5)
                raise InvariantFailure("worker_deadline", "exit within 45 seconds", "still running")
        if kill:
            check("process_death_after_acceptance", -signal.SIGKILL, process.exitcode)
            self.coverage.add("sigkill_after_acceptance")
        elif compete:
            check("competing_worker_refused", True, process.exitcode != 0)
            detail = result.get(timeout=2)
            check("competing_writer_reason", True, "WriterLockUnavailable" in detail.get("error", ""))
            self.coverage.add("competing_writer")
        else:
            check("worker_exit", 0, process.exitcode)
        result.close()

    def interrupted_catchup(self):
        if self.snapshot()["state"] is None:
            raise InvalidTrace("catch-up crash requires a committed production state")
        missed = []
        for _ in range(3):
            self.day = calendar.next_session(self.day)
            missed.append(self.day)
            self.provider.advance(market.step(self.day, self.trace.seed, shocks=self.shocks))
            with self.connection() as conn:
                ingest.daily(conn, today=self.day)
                compare_corpus(self.provider.step.expected, observed_corpus(conn))
        self.service.move(self.day + "T22:00:00+00:00")
        with self.connection() as conn:
            expected = catchup.resume_state(conn)
            intermediate = None
            for day in missed:
                expected = self.advance(conn, day, expected)
                if intermediate is None:
                    intermediate = expected
            conn.rollback()
        context = multiprocessing.get_context("spawn")
        result = context.Queue()
        process = context.Process(target=child_catchup,
            args=(self.cluster.dsn, self.service, str(self.cluster.base_root),
                  str(self.cluster.wal_root), missed, result))
        process.start()
        process.join(45)
        if process.is_alive():
            process.kill()
            process.join(5)
            raise InvariantFailure("catchup_worker_deadline", "exit within 45 seconds", "still running")
        if process.exitcode != -signal.SIGKILL:
            detail = result.get(timeout=2) if process.exitcode else {"error": "returned before injection"}
            raise InvariantFailure("catchup_death_reached", -signal.SIGKILL, detail)
        result.close()
        durable = self.snapshot()
        oracles.unchanged("catchup_intermediate_state_committed", intermediate, durable["state"])
        with self.connection() as conn:
            try:
                resumed = catchup.resume_state(conn)
            except catchup.StateCommitmentMismatch as exc:
                # Do not bless a refusal as successful recovery or bypass the
                # existing commitment guard to make the harness green.
                raise InvariantFailure("catchup_resume_after_intermediate_commit",
                    "validated committed intermediate state", str(exc)) from exc
            recovered = catchup.catch_up(conn, through=missed[-1], missed=missed,
                state=resumed, advance_state=self.advance,
                decide=lambda d, s: self.decide(conn, d, s))
        oracles.unchanged("catchup_restart_equivalence", expected, recovered.state)
        self.coverage.add("sigkill_between_catchup_sessions")

    def action(self, action):
        kind = action.kind
        before = self.snapshot()
        detail = None
        if kind == "daily":
            self.daily()
        elif kind == "restart":
            startup(self.env_path)
            with self.connection() as conn:
                state = catchup.resume_state(conn)
            oracles.unchanged("restart_preserves_state", before["state"], state)
            self.coverage.add("connection_restart")
        elif kind == "execute":
            detail = self.execute()
        elif kind == "kill_submit":
            self.child(kill=True)
        elif kind == "timeout_submit":
            self.service.timeout()
            detail = self.execute()
            check("lost_response_keeps_uncertainty", True,
                  any(c["state"] == "UNKNOWN" for c in self.snapshot()["commands"]))
            self.coverage.add("response_loss_after_acceptance")
        elif kind == "compete":
            self.child(compete=True)
            check("competing_writer_no_orders", before["broker"]["orders"], self.service.snapshot()["orders"])
        elif kind == "fill":
            count = self.service.fill(partial=action.value == 1)
            if not count and action.value != -1:
                raise InvalidTrace("fill requires a working broker order in its session")
        elif kind == "reconcile":
            detail = self.reconcile()
        elif kind == "cash":
            if before["state"] is None:
                raise InvalidTrace("cash perturbation requires an initialized shadow")
            if not action.value:
                raise InvalidTrace("cash action requires a nonzero amount")
            self.service.cash(action.value)
            with self.connection() as conn:
                first_rows = None
                through = datetime.fromisoformat(self.service.now())
                for _ in range(2):
                    asyncio.run(broker_cash.ingest_account_cash(conn,
                        broker_adapter=broker.adapter(self.service), broker="alpaca",
                        account_id="SIM-ALPACA-1", through=through))
                    conn.commit()
                    rows = plain(cashflow.flows_between(conn, market.SEED, through.date()))
                    if first_rows is not None:
                        oracles.unchanged("cash_event_deduplication", first_rows, rows)
                    first_rows = rows
                expected = sum(map(Decimal, self.service.snapshot()["movements"]), Decimal(0))
                check("external_cash_attribution", expected,
                      cashflow.net_external(conn, market.SEED, through.date()))
            self.coverage.add("cash_deduplication")
        elif kind == "checkpoint":
            if before["state"] is None:
                raise InvalidTrace("populated restore requires a committed strategy state")
            self.cluster.checkpoint("populated")
            self.saved = before
            self.coverage.add("populated_physical_backup")
        elif kind == "restore":
            if self.saved is None:
                raise InvalidTrace("restore requires a populated checkpoint")
            broker_before = self.service.snapshot()
            self.cluster.restore("populated")
            after = self.snapshot()
            for key in ("state", "cursor", "plan", "commands", "publication", "binding"):
                oracles.unchanged("physical_restore_" + key, self.saved[key], after[key])
            oracles.unchanged("restore_preserves_external_broker", broker_before, after["broker"])
            self.day = self.saved["cursor"]
            self.reference = self.saved["state"]
            self.restored = True
            self.coverage.add("stale_physical_restore")
        elif kind == "media_loss":
            marker = self.cluster.wal_root / ".sentinel-independent-durable-target-v1"
            self.media_saved = marker.read_bytes()
            marker.unlink()
            try:
                self.execute()
            except (backup_runtime_authority.BackupRuntimeRefused, backup_runtime_authority.BackupRuntimeUnavailable):
                self.coverage.add("backup_authority_refusal")
            else:
                raise InvariantFailure("missing_media_blocks_execution", "refusal", "executed")
            check("missing_media_no_orders", before["broker"]["orders"], self.service.snapshot()["orders"])
        elif kind == "media_repair":
            if self.media_saved is None:
                raise InvalidTrace("media repair requires loss")
            marker = self.cluster.wal_root / ".sentinel-independent-durable-target-v1"
            marker.write_bytes(self.media_saved)
            self.cluster.own(marker)
            self.media_saved = None
        elif kind == "wal_corrupt":
            if self.wal_saved is not None:
                raise InvalidTrace("nested WAL corruption")
            point = self.cluster.checkpoints[next(reversed(self.cluster.checkpoints))]
            path = self.cluster.wal_root / ("cluster-" + str(point["system_id"])) / point["wal"]
            data = path.read_bytes()
            self.wal_saved = (path, data)
            changed = bytearray(data)
            changed[1024] ^= 1
            path.write_bytes(changed)
            with self.connection() as conn:
                try:
                    backup_runtime_authority.require(conn, operation="integrated corruption proof")
                except backup_runtime_authority.BackupRuntimeRefused:
                    self.coverage.add("same_size_wal_corruption_refused")
                else:
                    raise InvariantFailure("corrupt_wal_blocks_mutation", "refusal", "accepted")
        elif kind == "wal_repair":
            if self.wal_saved is None:
                raise InvalidTrace("WAL repair requires corruption")
            self.wal_saved[0].write_bytes(self.wal_saved[1])
            self.wal_saved = None
        elif kind == "env_bad":
            self.env_path.write_bytes(self.env_bytes + b"ALPACA_BASE_URL=https://api.alpaca.markets\n")
            try:
                startup(self.env_path)
            except sentinel_env.EnvRefused:
                self.coverage.add("malformed_startup_refusal")
            else:
                raise InvariantFailure("malformed_env_blocks_startup", "refusal", "accepted")
            self.env_bad = True
        elif kind == "env_repair":
            if not self.env_bad:
                raise InvalidTrace("environment repair requires corruption")
            self.env_path.write_bytes(self.env_bytes)
            startup(self.env_path)
            self.env_bad = False
        elif kind == "data_bad":
            self.data_bad = True
        elif kind == "market_shock":
            if not -9000 <= action.value <= 10000 or not action.value:
                raise InvalidTrace("market shock must be a nonzero return in [-9000,10000] basis points")
            self.shocks.append((calendar.next_session(self.day), action.value))
            self.coverage.add("market_regime_change")
        elif kind == "data_repair":
            if not self.data_bad:
                raise InvalidTrace("data repair requires failure")
            self.data_bad = False
        elif kind == "corrupt_state":
            if before["state"] is None:
                raise InvalidTrace("state corruption requires a committed state")
            corrupt = dict(before["state"])
            corrupt["shadow_peak_nav"] += 1
            with self.connection() as conn:
                conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name='catchup'",
                    (json.dumps(corrupt),))
                conn.commit()
                try:
                    catchup.resume_state(conn)
                except catchup.StateCommitmentMismatch:
                    self.coverage.add("valid_json_corruption_refused")
                else:
                    raise InvariantFailure("state_commitment_refuses_corruption", "refusal", "accepted")
                # Fault reversal restores the exact previously committed bytes.
                conn.rollback()
                conn.execute("UPDATE sentinel_processed_sessions SET state=%s::jsonb WHERE cursor_name='catchup'",
                    (json.dumps(before["state"]),))
                conn.commit()
        elif kind == "cancel_race":
            self.service.fill(partial=True)
            self.reconcile()
            self.service.set_cancel_pending()
            with self.connection() as conn:
                with journal.writer_lock(conn):
                    from sentinel.execution.states import CommandState
                    commands = journal.in_flight_commands(conn, binding.require(conn).identity)
                    if not commands:
                        raise InvalidTrace("cancel race requires working commands")
                    for command in commands:
                        pending = command.transition(CommandState.CANCEL_PENDING)
                        journal.save_command(conn, pending, previous=command.state)
                        asyncio.run(broker.adapter(self.service).cancel(command.broker_order_id))
            self.service.fill()
            self.reconcile()
            self.coverage.add("partial_fill_cancel_race")
        elif kind == "kill_catchup":
            self.interrupted_catchup()
        else:
            raise InvalidTrace(f"unimplemented action: {kind}")
        after = self.snapshot()
        if kind not in {"daily", "restore", "kill_catchup"}:
            oracles.unchanged("broker_and_operations_cannot_change_strategy", before["state"], after["state"])
        if kind in {"restart", "reconcile", "cash", "execute", "compete", "kill_submit", "timeout_submit"}:
            oracles.unchanged("execution_cannot_rewrite_plan", before["plan"], after["plan"])
        self.invariants(after)
        return after | {"detail": detail}

    def run(self):
        for index, action in enumerate(self.trace.actions):
            self.action_index = index
            print(f"[internal-state] {self.trace.name} {index + 1}/{len(self.trace.actions)} {action.kind}", flush=True)
            try:
                snapshot = self.action(action)
            except BaseException as exc:
                if isinstance(exc, InvariantFailure):
                    exc.index = index
                try:
                    write(self.output / "failure-snapshot.json", self.snapshot())
                except Exception as snapshot_error:
                    write(self.output / "snapshot-error.json", {"error": repr(snapshot_error)})
                raise
            write(self.output / f"{index:03d}-{action.kind}.json", snapshot)
            self.records.append({"index": index, "action": action.model_dump(),
                                 "state_sha256": digest(snapshot["state"])})
        check("required_scenario_coverage", [], sorted(set(self.trace.required) - self.coverage))
        check("consumed_broker_faults", 0, self.service.snapshot()["remaining_faults"])
        return {"coverage": sorted(self.coverage), "actions": self.records}
