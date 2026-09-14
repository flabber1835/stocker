"""Production worker/process/SQL/recovery assembly with explicit external fixtures.

The source is HTTP and the simulator lives in a separate process, so neither
can accidentally heal when the worker or a callback is restarted. Strategy,
certificate and readiness fixtures retain the scope documented in
docs/automation-composition-regressions.md.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
import json
import multiprocessing as mp
from multiprocessing.managers import BaseManager
import os
from pathlib import Path
import shutil
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from sentinel import automation_recovery, automation_runtime, automation_worker
from sentinel.automation import store
from sentinel.automation.model import CycleState
from sentinel.execution import certification, journal, preopen_authority
from sentinel.execution.contract import ExecutionBroker
from sentinel.execution.simulator import SimulatedBroker, FaultKind
from sentinel.feed import (calendar, domains, publication, seed_capture,
                           sharadar, source_authority, store as feed_store, universe)
from test_automation_composition import assembly, pg, fixture  # shared explicit inputs

REAL_LATEST = feed_store.latest_visible_session
REAL_SESSIONS = calendar.sessions_in_range
REAL_NEXT = calendar.next_session


def _enable_fixture_archive(server):
    """Exercise the real runtime WAL fence with a private PostgreSQL archiver."""
    from tests.support.postgres import _as_pg_user, _find_pg_bin, _run
    destination = Path(server.datadir) / "worker-archive"
    destination.mkdir(exist_ok=True)
    if os.geteuid() == 0:
        shutil.chown(destination, user="postgres", group="postgres")
    with feed_store.connect(server.sync_dsn) as conn:
        conn.autocommit = True
        conn.execute("ALTER SYSTEM SET archive_mode='on'")
        command = f"test ! -f {destination}/%f && cp %p {destination}/%f"
        conn.execute("ALTER SYSTEM SET archive_command='" + command + "'")
    result = _run(_as_pg_user([_find_pg_bin("pg_ctl"), "-D", server.datadir,
                               "-l", str(Path(server.datadir) / "server.log"),
                               "-m", "fast", "-w", "restart"]))
    assert result.returncode == 0, result.stderr
    with feed_store.connect(server.sync_dsn) as conn:
        conn.execute("SELECT pg_create_restore_point('worker-fixture')")
        conn.execute("SELECT pg_switch_wal()")
        conn.commit()
    from sentinel import backup_guard
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with feed_store.connect(server.sync_dsn) as conn:
            if backup_guard.status(conn).writes_permitted:
                return
        time.sleep(0.1)
    pytest.fail("fixture WAL did not archive")


class BrokerHost:
    def __init__(self):
        self.broker = fixture._broker()
        self.broker.schedule_submit(FaultKind.ACCEPT_THEN_TIMEOUT)

    def call(self, name, args, kwargs):
        return asyncio.run(getattr(self.broker, name)(*args, **kwargs))

    def mutations(self):
        return fixture._mutations(self.broker)

    def fill(self, key):
        self.broker.fill(key)


class BrokerManager(BaseManager):
    pass


BrokerManager.register("BrokerHost", BrokerHost)


class RemoteBroker(SimulatedBroker):
    def __init__(self, remote, clock):
        super().__init__(account=fixture._broker().account,
                         equity=fixture.D(1000), cash=fixture.D(1000))
        self.remote = remote
        self.clock = clock
        certification.certify_adapter(self, name="simulator", mode="SIMULATION")

    def _now(self):
        return dt.datetime.fromtimestamp(self.clock.value, dt.timezone.utc)

    async def market_clock(self):
        now = self._now()
        opened, closed = calendar.session_window(now.date())
        return SimpleNamespace(timestamp=now, is_open=opened <= now < closed,
                               next_open=opened, next_close=closed)


def _remote_method(name):
    async def method(self, *args, **kwargs):
        return self.remote.call(name, args, kwargs)
    return method


for _name in dir(SimulatedBroker):
    if (inspect.iscoroutinefunction(getattr(SimulatedBroker, _name))
            and getattr(SimulatedBroker, _name) is not getattr(ExecutionBroker, _name, None)):
        setattr(RemoteBroker, _name, _remote_method(_name))


def _eventually(read, predicate, *, timeout=40):
    deadline, last = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        last = read()
        if predicate(last):
            return last
        if last is not None and last.state is CycleState.BLOCKED:
            pytest.fail(f"worker blocked: {last.failure_code}: {last.failure_detail}")
        time.sleep(0.1)
    pytest.fail(f"worker did not converge: {last!r}")


@pytest.mark.skipif(os.name != "posix", reason="production requires Linux callback supervision")
@pytest.mark.parametrize("finish", ["recover", "expired", "killed"])
def test_worker_wait_restart_source_healing_and_transport(assembly, monkeypatch, finish):
    _enable_fixture_archive(assembly.pg)
    context = mp.get_context("fork")
    clock = context.Value("d", assembly.clock[0].timestamp())
    healed = threading.Event()
    calls = []
    days = ["2026-08-10", "2026-08-11"]
    listings = [dict(table="SEP", ticker=f"T{i}", permaticker=str(i),
                     category="Domestic Common Stock", sector="Technology", exchange="NASDAQ",
                     isdelisted="N", relatedtickers="", firstpricedate=days[0],
                     lastpricedate=days[-1]) for i in range(4000)]
    listings[0].update(ticker=fixture.AAA.symbol, permaticker=fixture.AAA.security_id)
    listings.append(dict(listings[0], ticker="OLD", permaticker="111101"))
    bars = [dict(ticker=row["ticker"], date=day, open=100, close=100,
                 closeunadj=100, volume=100000, lastupdated=days[-1])
            for day in days for row in listings[:-1]]
    rename = [dict(date=days[-1], action=kind, ticker="NEW", name="Example",
                   value=None, contraticker=contra, contraname="N/A")
              for kind, contra in (("tickerchangeto", "NEW"), ("tickerchangefrom", "OLD"))]
    # The earlier pair is restated with the latest primary label too. Healing
    # must survive a complete multi-hop history in the real callback process.
    rename += [dict(date=days[0], action=kind, ticker="NEW", name="Example",
                    value=None, contraticker=contra, contraname="N/A")
               for kind, contra in (("tickerchangeto", "OLD"), ("tickerchangefrom", "EARLIER"))]
    # A separate business reuses the old spelling. Neither a reduced retry
    # metadata set nor an undated ACTIONS component may splice these identities.
    reused = dict(listings[-1], ticker="EARLIER", permaticker="2222026",
                  category="Domestic Common Stock Secondary Class", firstpricedate=days[-1])
    rename += [dict(date=days[-1], action=kind, ticker="ELSE", name="Different company",
                    value=None, contraticker=contra, contraname="N/A")
               for kind, contra in (("tickerchangeto", "ELSE"), ("tickerchangefrom", "EARLIER"))]

    class Source(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            table = url.path.rsplit("/", 1)[-1].split(".")[0]
            params = {key: value[0] for key, value in parse_qs(url.query).items()}
            calls.append((table, {k: v for k, v in params.items() if k != "api_key"}))
            rows = {sharadar.TICKERS: listings + [reused], sharadar.ACTIONS: rename if healed.is_set() else [],
                    sharadar.SFP: [dict(ticker=t, date=day, open=100, close=100,
                                       closeadj=100, closeunadj=100)
                                   for day in days for t in ("SPY", "BIL")],
                    sharadar.SEP: bars + [dict(bars[0], ticker="NEW", date=day) for day in days]
                                  + [dict(bars[0], ticker="EARLIER", date=days[-1])]}[table]
            for key in ("ticker", "contraticker", "permaticker", "action"):
                if key in params:
                    rows = [r for r in rows if str(r.get(key)) in params[key].split(",")]
            rows = [r for r in rows if "date" not in r or
                    params.get("date.gte", "1900-01-01") <= r["date"] <= params.get("date.lte", "9999-01-01")]
            columns = sorted(sharadar._REQUIRED_COLUMNS[table])
            data = json.dumps({"datatable": {"columns": [{"name": key} for key in columns],
                                            "data": [[r.get(key) for key in columns] for r in rows]},
                               "meta": {"next_cursor_id": None}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Source)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    manager = BrokerManager(ctx=context)
    manager.start()
    remote = manager.BrokerHost()
    workers = []
    try:
        monkeypatch.setattr(sharadar, "NDL_BASE", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setattr(sharadar, "ALLOW_INSECURE_BASE_URL", True)
        monkeypatch.setenv("SHARADAR_API_KEY", "synthetic-worker-test-key")
        monkeypatch.setenv("SENTINEL_AUTOMATION_HOLDER_ID", "actual-worker-entrypoint")
        monkeypatch.setattr(feed_store, "latest_visible_session", REAL_LATEST)
        monkeypatch.setattr(calendar, "sessions_in_range", REAL_SESSIONS)
        monkeypatch.setattr(calendar, "next_session", REAL_NEXT)

        class Clock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime.fromtimestamp(clock.value, tz or dt.timezone.utc)

        for owner in (automation_worker, automation_runtime, fixture.paper_preparation,
                      fixture.paper_execution, fixture.paper_recovery):
            monkeypatch.setattr(owner, "datetime", Clock)
        cfg = assembly.create().automation_config.model_copy(update={
            "lease_seconds": 3, "heartbeat_seconds": 1, "control_poll_seconds": 1,
            "retry_base_seconds": 1, "retry_max_seconds": 1,
            "refresh_max_attempts": 2, "maximum_clock_skew_seconds": 100_000_000})
        scfg = assembly.create().sentinel_config
        monkeypatch.setattr(automation_worker, "config_from_env", lambda: cfg)
        monkeypatch.setattr(automation_worker.SentinelConfig, "from_env", lambda: scfg)
        # Explicit simulator transport fixture registration. Production's
        # registry remains unchanged and still validates each wrapper instance.
        implementations = dict(certification._IMPLEMENTATIONS)
        implementations["simulator"] |= {f"{RemoteBroker.__module__}.{RemoteBroker.__qualname__}"}
        monkeypatch.setattr(certification, "_IMPLEMENTATIONS", implementations)
        monkeypatch.setattr(automation_runtime, "build_execution_broker", lambda *a, **k: RemoteBroker(remote, clock))

        def advance_fixture(conn, session, prior, **kwargs):
            state = fixture._advance_stub(conn, session, prior, **kwargs)
            state["data_version"] = publication.require_current(conn).version
            return state

        monkeypatch.setattr(fixture.paper_preparation, "advance_and_persist", advance_fixture)

        def capture_and_publish(conn, *, target_session):
            # The full source membrane and SQL publication run in the callback
            # child. Historical strategy/readiness and exporter proofs remain
            # explicit external fixtures, as in the existing paper assembly.
            guarded = source_authority.StableSharadarFetch(sharadar.fetch_table, seed_mode=True)
            params = sharadar.date_params(days[0], target_session)
            from sentinel.feed import ingest
            with seed_capture.CapturedRows() as captured:
                captured.capture(guarded, sharadar.TICKERS)
                action_start, _ = calendar.action_date_window(days[0], target_session)
                captured.capture(guarded, sharadar.ACTIONS, sharadar.date_params(action_start, target_session))
                captured.capture(guarded, sharadar.SFP, {"ticker": ingest.SFP_REFERENCE_TICKERS, **params})
                captured.capture(guarded, sharadar.SEP, params)
                with feed_store.corpus_write_lock(conn):
                    return ingest._ordinary_seed_generation(
                        conn, date_from=days[0], date_to=target_session,
                        fetch=captured, resolve_identity=None,
                        seed_authority=ingest._InjectedSeedAuthority())

        from sentinel.feed import outage_recovery
        monkeypatch.setattr(outage_recovery, "catch_up", capture_and_publish)
        with feed_store.connect(assembly.pg.sync_dsn) as conn:
            conn.execute("UPDATE sentinel_bars SET session=%s", (fixture.PRIOR,))
            conn.commit()
            baseline = publication.require_current(conn).version
            binding = assembly.control.model_copy(update={"config_sha256": cfg.fingerprint})
            store.activate(conn, binding=binding, actor="fixture", reason="worker start")
            store.release_kill(conn, expected_binding=binding, actor="fixture", reason="worker start")

        def read():
            with feed_store.connect(assembly.pg.sync_dsn) as conn:
                return store.latest_cycle(conn)

        def launch():
            process = context.Process(target=automation_worker.main)
            process.start()
            workers.append(process)
            return process

        first = launch()
        pending = _eventually(read, lambda c: c is not None and c.state is CycleState.RETRY_WAIT)
        assert pending.diagnostic["callback_failure"] == "SOURCE_DATA_PENDING"
        assert pending.diagnostic["source_probe"]["identities"] == ["111101"]
        # Advance scheduling time while keeping provider state unchanged. The
        # production worker must survive well beyond its former attempt budget.
        for count in (2, 3, 4):
            clock.value += 2
            _eventually(read, lambda c: c.diagnostic.get("phase_attempt_count", 0) >= count)
        full_sep = lambda: sum(table == "SEP" and "ticker" not in params for table, params in calls)
        assert full_sep() == 2
        assert remote.mutations() == []
        with feed_store.connect(assembly.pg.sync_dsn) as conn:
            assert publication.require_current(conn).version == baseline
        first.kill()
        first.join(10)
        second = launch()
        clock.value += 2
        _eventually(read, lambda c: c.diagnostic.get("phase_attempt_count", 0) >= 5)
        assert second.is_alive()
        assert full_sep() == 2
        if finish == "killed":
            with feed_store.connect(assembly.pg.sync_dsn) as conn:
                store.engage_kill(conn, actor="fixture", reason="source wait revoked")
            healed.set()
            clock.value += 10
            time.sleep(2)
            assert remote.mutations() == []
            assert full_sep() == 2
            return
        if finish == "expired":
            clock.value = dt.datetime(2026, 8, 12, 13, 33, tzinfo=dt.timezone.utc).timestamp()
        healed.set()
        clock.value += 2
        ready = _eventually(read, lambda c: c.state in {CycleState.PLAN_READY, CycleState.WAITING_OPEN,
                                                       CycleState.SUPERSEDED, CycleState.MISSED_STATE_ONLY})
        assert ready.cycle_id == pending.cycle_id
        if finish == "expired":
            _eventually(read, lambda c: c.state in {CycleState.SUPERSEDED, CycleState.MISSED_STATE_ONLY})
            assert remote.mutations() == []
            return
        with feed_store.connect(assembly.pg.sync_dsn) as conn:
            resolver = universe.load_resolver(conn)
            assert resolver.resolve("NEW", days[0]) == "111101"
            assert resolver.resolve("EARLIER", days[0]) == "111101"
            assert resolver.resolve("EARLIER", days[-1]) == "2222026"
            plan = journal.latest_plan(conn)
            cutoff = fixture.paper_targets._official_preopen_cutoff(plan)
            preopen_authority.record_authority(conn, preopen_authority.PreOpenShareUnitAuthority(
                plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint(), effective_session=plan.effective_session,
                provider="worker-fixture", publication_id="worker-fixture", as_of=cutoff,
                cutoff_at=cutoff, complete=True,
                coverage=(preopen_authority.ShareUnitCoverage.no_event(fixture.AAA.security_id),)))
        clock.value = dt.datetime(2026, 8, 12, 13, 31, tzinfo=dt.timezone.utc).timestamp()
        _eventually(read, lambda c: c.state is CycleState.RECONCILING)
        mutations = remote.mutations()
        assert len(mutations) == 1 and mutations[0].startswith("submit:")
        key = mutations[0].split(":", 1)[1]
        second.kill()
        second.join(10)
        remote.fill(key)
        launch()
        clock.value += 3
        _eventually(read, lambda c: c.state is CycleState.SUCCEEDED)
        assert remote.mutations() == mutations
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.kill()
            worker.join(10)
        server.shutdown()
        server.server_close()
        manager.shutdown()
