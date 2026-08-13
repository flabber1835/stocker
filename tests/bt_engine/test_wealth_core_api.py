"""Wealth Core, REACHABLE. The endpoint that turns three tested-but-uncallable
engines into something an experiment can actually start.

WHAT THESE TESTS ARE ABOUT. The strategy is pinned elsewhere — the golden
fixture, the cross-engine parity suite, the chain rehearsal. What can go wrong
HERE is different in kind:

  * the router exists but is not mounted, so everything stays unreachable and
    every unit test stays green;
  * the endpoint grows its own opinion about the corpus, and two readers of the
    same Sharadar tables agree until they quietly do not — the exact failure the
    factor-coverage contract was written after;
  * a refusal is missing, and the run returns a NUMBER that looks like an answer
    to a question nobody asked.

Each of the three has a test below, and the refusals have falsifiers: a
`_validate` that accepted everything would fail them.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import pathlib

import pytest

os.environ.setdefault(
    "BT_DATABASE_URL", "postgresql+asyncpg://smoke:smoke@localhost/smoke")

from fastapi import HTTPException  # noqa: E402
from fastapi import BackgroundTasks  # noqa: E402

from app import wealth_core_api as api  # noqa: E402
from app import jobs_busy  # noqa: E402
from app.wealth_core_chain import STATEFUL_MODEL  # noqa: E402
from stock_strategy_shared.wealth_core.golden import golden_scenario  # noqa: E402
from stock_strategy_shared.wealth_core.hashes import HASH_ORDER  # noqa: E402
from stock_strategy_shared.wealth_core.risk_profile import (  # noqa: E402
    PROFILE_NAME,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
SLICE = 160


def req(**over):
    base = dict(mode="chain_rehearsal", start_date="2020-01-01",
                end_date="2020-12-31")
    base.update(over)
    return api.WealthCoreJobRequest(**base)


@pytest.fixture(scope="module")
def corpus():
    """The golden stream in the shape `_load_corpus` returns.

    Substituting it here is what lets the DISPATCH be tested without a Sharadar
    corpus — and the substitution is legitimate because the loader is tested on
    its own side, in tests/backtester.
    """
    g = golden_scenario()
    return {"sessions": list(g.sessions[:SLICE]),
            "bars_by_session": g.bars_by_session, "meta": g.meta,
            "terminal_events": list(g.terminal_events),
            "provenance": {"split_source": "actions"}}


# ── 1. it is actually reachable ─────────────────────────────────────────────

class TestItIsMounted:
    """The failure this catches is the whole reason the endpoint was written:
    `wealth_core_tunnel` and `wealth_core_chain` were complete, tested, and
    called by nothing. A router that exists but is not included repeats it."""

    def test_the_routes_are_on_the_APP(self):
        import app.main as main
        paths = set(main.app.openapi()["paths"])
        assert "/wealth-core/jobs/run" in paths
        assert "/wealth-core/runs/latest" in paths
        assert "/wealth-core/runs/{run_id}" in paths

    def test_the_router_is_CONFIGURED_with_the_engine(self):
        """Unconfigured, every call 503s — which is a working service that can
        do nothing, the state this test exists to rule out."""
        import app.main as main  # noqa: F401  (import wires configure())
        assert api._state["engine"] is not None

    def test_the_table_is_created_at_STARTUP(self):
        """The run row is the only durable record of a multi-hour job. A DDL
        list that is never executed makes every run 500 on its first write."""
        src = (REPO / "services" / "bt-engine" / "app" / "main.py").read_text()
        assert "wealth_core_api.WEALTH_CORE_DDL" in src
        assert any("bt_wealth_core_runs" in d for d in api.WEALTH_CORE_DDL)


# ── 2. one corpus reader, not two ───────────────────────────────────────────

class TestTheCorpusIsReadThroughTheOwNER:

    def test_the_loader_module_is_COPYed_into_the_image(self):
        df = (REPO / "services" / "bt-engine" / "Dockerfile").read_text()
        assert "services/backtester/app/wealth_core_replay.py ./app/live/" in df

    def test_this_module_writes_NO_corpus_SQL_of_its_own(self):
        """The falsifiable form of "there is one loader". Every SQL literal in
        the module is collected and checked: a bt_prices / bt_actions /
        bt_universe query written here would be a second opinion about what the
        Sharadar columns mean, and the two would drift with nothing comparing
        them.

        Checked against the SQL, not the whole file, because an error message
        may legitimately NAME `bt_actions` — telling the operator which table is
        empty and which job fills it is the point of that message."""
        tree = ast.parse((REPO / "services" / "bt-engine" / "app" /
                          "wealth_core_api.py").read_text())
        sql = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and any(kw in n.value.upper()
                       for kw in ("SELECT ", "INSERT ", "UPDATE ", "CREATE "))]
        assert sql, "no SQL found at all — the scan is not looking at anything"
        for stmt in sql:
            for table in ("bt_prices", "bt_actions", "bt_universe",
                          "closeunadj", "close_unadjusted"):
                assert table not in stmt, (
                    f"{table!r} is queried in wealth_core_api.py — the corpus "
                    f"mapping belongs to wealth_core_replay.py alone: {stmt!r}")

    def test_the_only_tables_it_touches_are_its_OWN_result_rows(self):
        src = (REPO / "services" / "bt-engine" / "app" /
               "wealth_core_api.py").read_text()
        # bt_runs / bt_sweeps appear only in the busy check, which reads status.
        assert src.count("bt_wealth_core_runs") >= 4
        assert "INSERT INTO bt_runs" not in src

    def test_the_session_calendar_comes_from_the_shared_loader(self):
        """Both engines must agree about which days exist. A second session
        query is the cheapest possible way for them not to.

        `app.live.wealth_core_replay` only exists inside the IMAGE (the COPY
        above puts it there), so this asserts the import site and the presence
        of the symbol on the owning side; tests/smoke proves the image layout
        actually resolves it."""
        src = (REPO / "services" / "bt-engine" / "app" /
               "wealth_core_api.py").read_text()
        assert "from app.live.wealth_core_replay import" in src
        # `warmup_from`, not `start`: the calendar is queried back far enough to
        # give the signal its pre-start window (see test_wealth_core_warmup.py).
        # Pinning the argument as well as the call keeps this test's original
        # property — one shared loader — and additionally fails if the widening
        # is reverted.
        assert "load_sessions(conn, warmup_from, end)" in src
        owner = (REPO / "services" / "backtester" / "app" /
                 "wealth_core_replay.py").read_text()
        assert "def load_sessions(" in owner
        assert "load_sessions(conn, req.start_date, req.end_date)" in owner, (
            "the owner must USE its own loader, or the two callers can still "
            "disagree about the calendar")


# ── 3. the refusals, each with its falsifier ────────────────────────────────

class TestBaselineReplayRefusals:

    def test_it_will_not_RECOMPUTE_the_expectation(self):
        """A parity check whose expectation it derived itself proves only that
        the tunnel agrees with the tunnel."""
        with pytest.raises(HTTPException) as e:
            api._validate(req(mode="baseline_replay"))
        assert e.value.status_code == 422
        assert "agrees with itself" in str(e.value.detail)

    def test_a_PARTIAL_hash_set_is_refused(self):
        """Seven ordered layers; accepting three silently narrows the check to
        whichever ones the caller happened to send."""
        partial = {k: "x" for k in HASH_ORDER[:3]}
        with pytest.raises(HTTPException) as e:
            api._validate(req(mode="baseline_replay", expected_hashes=partial))
        assert "missing" in str(e.value.detail)

    def test_a_COMPLETE_hash_set_is_accepted(self):
        api._validate(req(mode="baseline_replay",
                          expected_hashes={k: "x" for k in HASH_ORDER}))

    def test_a_baseline_replay_carrying_a_CHANGE_is_refused(self):
        with pytest.raises(HTTPException):
            api._validate(req(mode="baseline_replay",
                              expected_hashes={k: "x" for k in HASH_ORDER},
                              change={"n_slots": 20}))


class TestExperimentRefusals:

    def _ok(self, **over):
        base = dict(mode="experiment", change={"n_slots": 20},
                    config={"n_slots": 20},
                    baseline_hashes={k: "x" for k in HASH_ORDER})
        base.update(over)
        return req(**base)

    def test_the_happy_path_validates(self):
        api._validate(self._ok())

    def test_an_experiment_with_NO_change_is_refused(self):
        with pytest.raises(HTTPException) as e:
            api._validate(self._ok(change={}))
        assert "must record its change" in str(e.value.detail)

    def test_an_experiment_with_NO_baseline_is_refused(self):
        with pytest.raises(HTTPException) as e:
            api._validate(self._ok(baseline_hashes=None))
        assert "baseline" in str(e.value.detail)

    def test_a_change_the_run_DOES_NOT_MAKE_is_refused(self):
        """The subtle one. `change` is free text destined for the audit row, so
        nothing else checks that the run actually made it — and a result
        attributed to a modification that never happened is worse than no
        result, because it is citable."""
        with pytest.raises(HTTPException) as e:
            api._validate(self._ok(change={"n_slots": 20}, config={}))
        assert "never happened" in str(e.value.detail)

    def test_a_change_delivered_via_ELIGIBILITY_is_accepted(self):
        api._validate(self._ok(change={"min_dollar_volume_20d": 1.0},
                               config={},
                               eligibility={"min_dollar_volume_20d": 1.0}))

    def test_free_text_annotation_does_not_have_to_be_a_config_field(self):
        api._validate(self._ok(change={"n_slots": 20, "note": "why"},
                               config={"n_slots": 20}))


class TestGeneralRefusals:

    def test_a_reversed_date_range_is_refused(self):
        with pytest.raises(HTTPException):
            api._validate(req(start_date="2021-01-01", end_date="2020-01-01"))

    def test_a_rehearsal_is_not_a_VARIANT(self):
        with pytest.raises(HTTPException) as e:
            api._validate(req(change={"n_slots": 20}))
        assert "not a variant" in str(e.value.detail)

    def test_an_UNKNOWN_config_field_is_named_rather_than_ignored(self):
        from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
        with pytest.raises(HTTPException) as e:
            api._apply(WealthCoreConfig(), {"n_slotz": 20}, "WealthCoreConfig")
        assert "n_slotz" in str(e.value.detail)
        assert "n_slots" in str(e.value.detail), "the error must list what exists"


# ── 4. dispatch, on the golden stream ───────────────────────────────────────

class TestDispatch:

    def test_a_chain_rehearsal_runs_the_LIVE_path_and_reports_risk(self, corpus):
        out = api._execute(req(), corpus)
        s = out["summary"]
        assert s["execution_model"] == STATEFUL_MODEL
        assert s["risk_profile"] == PROFILE_NAME
        assert s["final_positions"] > 0
        assert out["parity_hashes"].keys() >= set(HASH_ORDER)

    def test_a_baseline_replay_PASSES_against_its_own_hashes(self, corpus):
        """Run once to obtain the seven hashes, then feed them back as the
        expectation. Circular as a parity check — which is why the endpoint
        refuses to do this for a caller — but it is the only way to show the
        pass path works without standing up the backtester."""
        first = api._execute(req(mode="chain_rehearsal"), corpus)
        out = api._execute(
            req(mode="baseline_replay", expected_hashes=first["parity_hashes"]),
            corpus)
        assert out["summary"]["divergence"]["identical"] is True

    def test_a_baseline_replay_RAISES_on_a_real_divergence(self, corpus):
        from app.wealth_core_tunnel import ParityViolation
        bogus = {k: "0" * 64 for k in HASH_ORDER}
        with pytest.raises(ParityViolation):
            api._execute(req(mode="baseline_replay", expected_hashes=bogus),
                         corpus)

    def test_an_experiment_records_its_parent_and_its_divergence(self, corpus):
        base = api._execute(req(mode="chain_rehearsal"), corpus)["parity_hashes"]
        out = api._execute(
            req(mode="experiment", change={"n_slots": 12},
                config={"n_slots": 12}, baseline_hashes=base), corpus)
        s = out["summary"]
        assert s["change"] == {"n_slots": 12}
        assert s["baseline_parent"] == base
        # 12 slots instead of 25 must change what was DECIDED, not what was fed
        # in — a divergence at normalized_input would mean the data moved.
        assert s["divergence"]["first_divergence"] == "decision"

    def test_a_LONG_rehearsal_elides_its_per_session_detail(self, corpus):
        """One row per trading day is the point of a rehearsal and unusable as a
        jsonb column over twenty years; the verdict and the counts always stay."""
        long_corpus = dict(corpus)
        out = api._execute(req(), long_corpus)
        assert isinstance(out["summary"]["sessions"], list), "160 fits"

        import app.wealth_core_api as mod
        real = mod.rehearse_chain

        class _Fat:
            def to_dict(self):
                d = real(sessions=corpus["sessions"],
                         bars_by_session=corpus["bars_by_session"],
                         meta=corpus["meta"], starting_cash=1_000_000.0,
                         terminal_events=corpus["terminal_events"],
                         config={"execution_model": STATEFUL_MODEL}).to_dict()
                d["sessions"] = d["sessions"] * 5   # 800 > 400
                return d
            bulk_hashes: dict = {}

        mod.rehearse_chain = lambda **kw: _Fat()
        try:
            out = api._execute(req(), corpus)
        finally:
            mod.rehearse_chain = real
        assert out["summary"]["sessions"] == "800 sessions elided"


# ── 5. the async/sync bridge ────────────────────────────────────────────────

class TestTheThreadBridge:
    """The loader is written against a SYNC connection and bt-engine's engine is
    async. The bridge exists so the loader is not forked — the alternative being
    a second corpus reader, which is what section 2 is about."""

    @staticmethod
    def _chunks(*batches):
        """A fake fetch: each call returns the next batch, then empties."""
        pending = list(batches)

        def fetch():
            return pending.pop(0) if pending else []
        return fetch

    def test_rows_reach_the_thread_as_PLAIN_LISTS_not_a_live_cursor(self):
        """A cursor bound to the loop's connection, iterated in the worker
        thread, is a use-after-free that shows up as intermittent corruption
        rather than an error. Each CHUNK is materialised before it crosses."""
        r = api._Rows(self._chunks([{"a": 1}], [{"a": 2}]))
        assert list(r.mappings()) == [{"a": 1}, {"a": 2}]
        assert r._exhausted

    def test_a_result_is_SINGLE_PASS(self):
        """The change that came with chunking, pinned rather than assumed. The
        old bridge held every row and was re-iterable; a server-side cursor is
        consumed once. Safe only because no loader reads a result twice — if one
        ever does, it gets nothing rather than an error, so this test is the
        record of why that is allowed."""
        r = api._Rows(self._chunks([{"a": 1}, {"a": 2}]))
        assert list(r) == [{"a": 1}, {"a": 2}]
        assert list(r) == [], "a consumed cursor yields nothing on a second pass"

    def test_first_replays_into_a_later_iteration(self):
        """`first()` must pull a chunk to answer, and that chunk is still owed
        to the iterator. Dropping it would silently skip the head of the corpus
        — a shorter history, not an error."""
        r = api._Rows(self._chunks([{"a": 1}, {"a": 2}], [{"a": 3}]))
        assert r.first() == {"a": 1}
        assert list(r) == [{"a": 1}, {"a": 2}, {"a": 3}]

    def test_an_empty_result_first_is_None_not_an_IndexError(self):
        assert api._Rows(self._chunks()).first() is None
        assert list(api._Rows(self._chunks())) == []

    def test_the_bridge_streams_rather_than_materialising(self):
        """`stream()` is load-bearing: with `execute()` the driver buffers the
        whole result before the first row is handed over, so chunking on this
        side would bound nothing. This is the OOM that killed a 2021-2023
        rehearsal at 4.1 GB."""
        src = (REPO / "services" / "bt-engine" / "app" /
               "wealth_core_api.py").read_text()
        bridge = src[src.index("class _ThreadConn"):src.index("# ── request")]
        assert ".stream(" in bridge
        assert "fetchmany" in bridge
        assert "_conn.execute(" not in bridge, (
            "execute() buffers the entire result driver-side — the defect")

    def test_the_bridge_marshals_back_to_the_LOOP(self):
        """`asyncio.run_coroutine_threadsafe` is load-bearing: calling the async
        connection from the worker thread directly would silently return a
        coroutine object the loader would then treat as rows."""
        src = ast.parse((REPO / "services" / "bt-engine" / "app" /
                         "wealth_core_api.py").read_text())
        names = {n.attr for n in ast.walk(src) if isinstance(n, ast.Attribute)}
        assert "run_coroutine_threadsafe" in names


class TestTheCorpusRangeIsDatesNotStrings:
    """The defect that killed the first real corpus run, minutes into a
    three-hour job, on the very first query.

    `_load_corpus` derived `start, end = str(req.start_date), str(...)` and bound
    those against DATE columns. The backtester's own path uses psycopg2, which
    coerces a string silently; bt-engine reaches Postgres through ASYNCPG, which
    type-checks bind parameters and raises "'str' object has no attribute
    'toordinal'". So the conversion was correct everywhere it had ever been
    exercised — every unit test here drives a FAKE connection, and a fake accepts
    anything.

    That is the general lesson these two tests encode: a fake connection cannot
    catch a driver's type contract, so the contract has to be asserted on the
    values themselves, before they reach any connection at all.
    """

    def _req(self):
        return api.WealthCoreJobRequest(
            mode="chain_rehearsal", start_date="2021-01-01", end_date="2023-12-31")

    def test_the_range_is_date_objects(self):
        import datetime
        start, end = api.corpus_date_range(self._req())
        assert isinstance(start, datetime.date) and not isinstance(start, str)
        assert isinstance(end, datetime.date) and not isinstance(end, str)
        assert (start, end) == (datetime.date(2021, 1, 1), datetime.date(2023, 12, 31))

    def test_asyncpg_would_reject_what_the_old_code_produced(self):
        """The other half: proof that the type actually matters. asyncpg's date
        codec calls `.toordinal()` on the bound value, which is exactly the
        AttributeError the production run reported — a str has no such method
        and a date does."""
        start, _ = api.corpus_date_range(self._req())
        assert hasattr(start, "toordinal")
        assert not hasattr(str(start), "toordinal")

    def test_no_caller_stringifies_the_range_back(self):
        """A `str(...)` reintroduced anywhere in the corpus load puts the defect
        straight back, and it would again pass every fake-driven test here."""
        src = (REPO / "services" / "bt-engine" / "app" /
               "wealth_core_api.py").read_text()
        body = src[src.index("async def _load_corpus"):src.index("def _execute(")]
        assert "str(req.start_date)" not in body
        assert "str(req.end_date)" not in body
        assert "corpus_date_range(req)" in body


class TestTheCorpusSnapshotIsIdentifiedAndStable:
    SRC = pathlib.Path(api.__file__).read_text()

    class _Result:
        def __init__(self, row):
            self.row = row

        def first(self):
            return self.row

        def scalar_one(self):
            return self.row[0]

    class _Conn:
        def __init__(self, row=None, error=None):
            self.row, self.error = row, error

        async def execute(self, stmt, params=None):
            if self.error:
                raise self.error
            return TestTheCorpusSnapshotIsIdentifiedAndStable._Result(self.row)

    def test_every_loader_query_runs_in_one_repeatable_read_read_only_snapshot(self):
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        tx = body.index(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        lock = body.index("acquire_corpus_read_lock(aconn)")
        identity = body.index("load_ready_data_generation(aconn)")
        first_loader = body.index("assert_raw_price_domain(conn")
        assert tx < lock < identity < first_loader

    def test_identity_and_meta_are_bounded_by_the_requested_end(self):
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        assert "load_meta(conn, as_of=end)" in body
        assert "load_identity(conn, as_of=end)" in body

    def test_READY_generation_is_preserved_for_run_provenance(self):
        async def scenario():
            conn = self._Conn(("version-7", "READY", "sharadar",
                               "2026-08-12T00:00:00Z", "daily"))
            generation = await jobs_busy.load_ready_data_generation(conn)
            assert generation.version == "version-7"
            assert generation.source_mode == "sharadar"

        asyncio.run(scenario())
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        for field in ("bt_data_version", "bt_data_status",
                      "bt_data_source_mode", "bt_data_updated_at"):
            assert field in body

    def test_an_active_writer_is_refused_instead_of_queued(self):
        async def scenario():
            conn = self._Conn((False,))
            with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                               match="publication is in progress"):
                await jobs_busy.acquire_corpus_read_lock(conn)

        asyncio.run(scenario())
        assert "pg_try_advisory_xact_lock_shared" in inspect.getsource(
            jobs_busy.acquire_corpus_read_lock)

    @pytest.mark.parametrize("status", ["PUBLISHING", "FAILED"])
    def test_non_READY_generation_is_refused(self, status):
        async def scenario():
            conn = self._Conn(("version-6", status, "sharadar",
                               "2026-08-12T00:00:00Z", None))
            with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                               match="not READY"):
                await jobs_busy.load_ready_data_generation(conn)

        asyncio.run(scenario())

    def test_pre_generation_schema_is_refused_not_treated_as_unversioned(self):
        async def scenario():
            conn = self._Conn(error=RuntimeError("column status does not exist"))
            with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                               match="schema migration"):
                await jobs_busy.load_ready_data_generation(conn)

        asyncio.run(scenario())


class TestJobAdmissionIsTransactional:
    """Two requests must not both pass the empty-running-row observation.

    The fake transaction deliberately allows requests to overlap.  Its busy
    SELECT snapshots the row set before yielding, so removing the advisory
    admission gate makes both requests observe "empty" and insert a run.  With
    the gate, the second transaction cannot reach that snapshot until the first
    committed its durable running row.
    """

    class _Result:
        def __init__(self, row=None):
            self._row = row

        def first(self):
            return self._row

    class _Conn:
        def __init__(self, engine):
            self.engine = engine
            self.holds_gate = False

        async def execute(self, stmt, params=None):
            sql = str(stmt)
            if "pg_advisory_xact_lock" in sql:
                await self.engine.gate.acquire()
                self.holds_gate = True
                return TestJobAdmissionIsTransactional._Result((None,))
            if "SELECT kind FROM" in sql:
                # Snapshot BEFORE yielding.  Without the gate both requests
                # take the empty snapshot and then proceed together.
                row = ("Wealth Core run",) if self.engine.rows else None
                await asyncio.sleep(0)
                return TestJobAdmissionIsTransactional._Result(row)
            if "INSERT INTO bt_wealth_core_runs" in sql:
                await asyncio.sleep(0)
                self.engine.rows.append(dict(params or {}))
                return TestJobAdmissionIsTransactional._Result()
            raise AssertionError(f"unexpected SQL: {sql}")

    class _Begin:
        def __init__(self, engine):
            self.conn = TestJobAdmissionIsTransactional._Conn(engine)

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, typ, value, tb):
            if self.conn.holds_gate:
                self.conn.engine.gate.release()

    class _Engine:
        def __init__(self):
            self.rows = []
            self.gate = asyncio.Lock()

        def begin(self):
            return TestJobAdmissionIsTransactional._Begin(self)

    def test_two_concurrent_starts_create_exactly_one_running_row(self,
                                                                  monkeypatch):
        async def scenario():
            engine = self._Engine()
            monkeypatch.setitem(api._state, "engine", engine)
            monkeypatch.setitem(api._state, "lock", asyncio.Lock())
            monkeypatch.setattr(api, "_engine_identity", lambda: {"test": True})

            calls = [api.start_wealth_core_job(req(), BackgroundTasks())
                     for _ in range(2)]
            outcomes = await asyncio.gather(*calls, return_exceptions=True)
            accepted = [x for x in outcomes if isinstance(x, dict)]
            refused = [x for x in outcomes if isinstance(x, HTTPException)]
            assert len(accepted) == 1
            assert len(refused) == 1 and refused[0].status_code == 409
            assert len(engine.rows) == 1

        asyncio.run(scenario())


class TestProgressBelongsOnlyToTheRunningRun:
    def teardown_method(self):
        api._progress = {}
        api._progress_run_id = None

    def test_a_terminal_durable_row_cannot_return_running_progress(self,
                                                                  monkeypatch):
        run_id = "00000000-0000-0000-0000-000000000071"
        api._begin_progress(run_id)
        api._publish_progress({"sessions_completed": 17})

        async def terminal(where, params):
            assert params == {"r": run_id}
            return {"run_id": run_id, "status": "success"}

        monkeypatch.setattr(api, "_fetch", terminal)
        result = asyncio.run(api.wealth_core_progress())
        assert result["running"] is False
        assert api._progress == {}
        assert api._progress_run_id is None

    def test_a_matching_running_row_returns_its_provisional_snapshot(self,
                                                                     monkeypatch):
        run_id = "00000000-0000-0000-0000-000000000072"
        api._begin_progress(run_id)
        api._publish_progress({"sessions_completed": 9})

        async def running(where, params):
            return {"run_id": run_id, "status": "running"}

        monkeypatch.setattr(api, "_fetch", running)
        result = asyncio.run(api.wealth_core_progress())
        assert result == {"running": True, "run_id": run_id,
                          "sessions_completed": 9}

    def test_both_terminal_paths_clear_before_their_status_update(self):
        body = inspect.getsource(api._run_bg)
        success = body.index("UPDATE bt_wealth_core_runs SET status='success'")
        failed = body.index("UPDATE bt_wealth_core_runs SET status='failed'")
        clears = [i for i in range(len(body))
                  if body.startswith("_finish_progress(run_id)", i)]
        assert any(i < success for i in clears)
        assert any(success < i < failed for i in clears)
        assert "finally:" in body and clears[-1] > failed

    def test_delayed_cleanup_cannot_erase_a_new_runs_progress(self):
        api._begin_progress("new-run")
        api._publish_progress({"sessions_completed": 1})
        api._finish_progress("old-run")
        assert api._progress == {"run_id": "new-run", "sessions_completed": 1}

    def test_a_late_callback_from_an_old_run_cannot_overwrite_the_new_one(self):
        api._begin_progress("new-run")
        api._publish_progress_for("new-run", {"sessions_completed": 3})
        api._publish_progress_for("old-run", {"sessions_completed": 999})
        assert api._progress == {"run_id": "new-run", "sessions_completed": 3}


class TestARestartDoesNotLeaveARunLying:
    """A Wealth Core run lives in a background task. When the engine restarts the
    task is gone and nothing updates its row — so without a startup reclaim it
    reads `running` forever.

    That is not merely untidy. `running` + "/progress has nothing yet" is exactly
    what a HEALTHY run looks like during its corpus load, so the operator has no
    way to tell a dead job from a working one. It cost a real three-year
    rehearsal: killed 16 minutes in by a container restart, then waited on for
    half an hour with no query running and no process behind it.
    """

    LIFESPAN = (REPO / "services" / "bt-engine" / "app" / "main.py").read_text()

    def test_process_lease_is_acquired_before_any_reclaim_write(self):
        lease = self.LIFESPAN.index(
            "await acquire_engine_process_lease(lease_conn)")
        reclaim = self.LIFESPAN.index(
            "UPDATE bt_wealth_core_runs SET status='failed'")
        assert lease < reclaim

    def test_process_lease_is_session_scoped_not_transaction_scoped(self):
        source = inspect.getsource(jobs_busy.acquire_engine_process_lease)
        assert "pg_try_advisory_lock" in source
        assert "pg_try_advisory_xact_lock" not in source

    def test_a_second_process_refuses_before_it_can_reclaim(self):
        class Result:
            def scalar_one(self):
                return False

        class Conn:
            async def execute(self, _statement, params=None):
                assert params == {"key": jobs_busy.ENGINE_PROCESS_LEASE_KEY}
                return Result()

        async def scenario():
            with pytest.raises(
                    jobs_busy.EngineProcessLeaseUnavailable,
                    match="before orphan recovery"):
                await jobs_busy.acquire_engine_process_lease(Conn())

        asyncio.run(scenario())

    def test_the_startup_pass_reclaims_wealth_core_runs(self):
        assert "UPDATE bt_wealth_core_runs SET status='failed'" in self.LIFESPAN

    def test_EVERY_job_table_this_service_creates_is_reclaimed(self):
        """DERIVED from the DDL, not enumerated.

        This used to name bt_runs, bt_sweeps and bt_wealth_core_runs literally,
        because three existed — and the reason for the literal list was to stop
        a FOURTH table arriving with the same omission, which a literal list
        cannot actually do. It also went stale the moment the Wealth Core
        repair removed the two tables this service can no longer create: it
        demanded a reclaim for rows nothing here writes.

        Reading the DDL closes both holes at once. A new job table is covered
        the day it is added, and a removed one stops being demanded.
        """
        import re

        from app import wealth_core_api

        created = set()
        for ddl in wealth_core_api.WEALTH_CORE_DDL:
            m = re.search(r"CREATE TABLE IF NOT EXISTS (bt_\w+)", ddl)
            # A job table is one with a `status` lifecycle; the results and
            # progress tables have no run to reclaim.
            if m and "status" in ddl:
                created.add(m.group(1))

        assert created, "no job table found in WEALTH_CORE_DDL"
        for table in sorted(created):
            assert f"UPDATE {table} SET status='failed'" in self.LIFESPAN, (
                f"{table} has running rows that no restart pass reclaims")

    def test_the_RETIRED_tables_are_no_longer_touched(self):
        """bt_runs and bt_sweeps belong to the backtester the eradication
        deleted. Nothing here can create a row in them, so marking their stale
        rows RESTART_ABORTED would be a lie — they were not aborted by this
        restart, they were abandoned by a deletion."""
        for table in ("bt_runs", "bt_sweeps"):
            assert f"UPDATE {table} SET" not in self.LIFESPAN

    def _reclaim_statements(self):
        """The reclaim SQL, via AST rather than regex.

        Python folds adjacent string literals into ONE constant at parse time,
        so each multi-line statement arrives whole — and comments, which sit
        between the literals in the source, are already gone. A regex over the
        raw text fought both.
        """
        import ast
        tree = ast.parse(self.LIFESPAN)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                  and n.name == "lifespan")
        # Scoped to `lifespan`, not the whole module: bt-engine has other
        # `status='failed'` updates (the stale-run reclaim, the per-run failure
        # path) and counting those would make this test pass for the wrong
        # reason.
        return [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and "UPDATE bt_" in n.value and "status='failed'" in n.value]

    def test_every_reclaim_is_marked_RESTART_ABORTED(self):
        """The marker is what distinguishes 'the engine died' from 'the strategy
        failed'. A reclaim without it turns an infrastructure event into what
        looks like a result — and the scheduler's own recovery keys on the
        prefix."""
        stmts = self._reclaim_statements()
        assert stmts, "no reclaim statements at all"
        for stmt in stmts:
            assert "RESTART_ABORTED" in stmt, stmt[:120]

    def test_the_reclaim_only_touches_running_rows(self):
        """A finished run's summary must never be overwritten by a later
        restart — the metrics are the whole point of the row."""
        for stmt in self._reclaim_statements():
            assert "WHERE status='running'" in stmt, stmt[:120]


class TestAnEmptyUniverseIsRefusedNotScored:
    """The worst output this system can produce is a number that looks like an
    answer to a question nobody asked.

    An empty `bt_universe` raises nothing downstream: no candidates means no
    scores, no admissions, and no rejections either — so the run reaches
    `status: success` with a flat equity curve, 0.00% CAGR, 0.00% drawdown and
    ending equity exactly equal to starting cash. A strategy that EARNED nothing
    and a strategy that could not RUN are then indistinguishable, and the second
    reads as evidence about the first.

    Measured 2026-08-06: exactly that, over 753 sessions, with `securities: 0`
    the only trace.
    """

    SRC = (REPO / "services" / "bt-engine" / "app" / "wealth_core_api.py").read_text()

    def test_the_load_refuses_on_an_empty_universe(self):
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        assert "if not meta:" in body, (
            "an empty universe must be refused before any bar is loaded")
        assert "RawPriceDomainUnavailable" in body

    def test_the_refusal_comes_BEFORE_the_bars_are_read(self):
        """Refusing after the load would still be correct and would waste the
        entire corpus read — minutes, on the slowest step there is."""
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        assert body.index("if not meta:") < body.index("load_bars("), (
            "the universe check must precede load_bars")

    def test_the_message_names_the_remedy_and_denies_being_a_result(self):
        """A refusal an operator cannot act on gets retried verbatim. And this
        one has to say explicitly that 0% is not a finding, because the whole
        failure mode is that it looks like one."""
        body = self.SRC[self.SRC.index("async def _load_corpus"):
                        self.SRC.index("def _execute(")]
        msg = body[body.index("if not meta:"):body.index("identity = load_identity")]
        assert "bt_universe" in msg
        assert "/jobs/backfill" in msg, "the remedy must be a command, not advice"
        assert "0%" in msg and "NOT a strategy result" in msg


class TestRetentionIsReachableFromTheRequest:
    """The rehearsal's retention control had to be ASKABLE, not merely present.

    `rehearse_chain` has taken `retention_mode` since the memory work, and
    `test_retention_modes_are_certification_equivalent` proves `full` and
    `bounded` produce byte-identical certification output. None of that could
    take effect: the endpoint never passed the parameter, so every rehearsal ran
    `full` and retained every SessionRehearsal and RunTrace for the whole run.

    A 753-session rehearsal measured that as +0.128 GiB per 5-minute sample,
    dead linear across eleven consecutive samples, until the container OOM-killed
    at 2h52m (2026-08-09, run 58449402). Three lost rehearsals preceded it.

    These tests are about the WIRE, not the retention semantics — those are
    covered on the chain side. What is asserted here is that the value an
    operator sends is the value the engine receives, that omitting it changes
    nothing, and that a wrong value is refused rather than silently defaulted.
    """

    def _capture(self, monkeypatch):
        """Intercept rehearse_chain and record the kwargs it was handed."""
        seen: dict = {}
        real = api.rehearse_chain

        def spy(**kw):
            seen.update(kw)
            return real(**kw)

        monkeypatch.setattr(api, "rehearse_chain", spy)
        return seen

    def test_a_requested_mode_REACHES_rehearse_chain(self, corpus, monkeypatch):
        """The plumbing test. This is the one that was failing in production —
        silently, because nothing between the request and the engine mentioned
        retention at all."""
        seen = self._capture(monkeypatch)
        api._execute(req(retention_mode="bounded", retention_tail=7), corpus)
        assert seen["retention_mode"] == "bounded"
        assert seen["retention_tail"] == 7

    def test_omitting_it_still_reaches_the_engine_as_full(self, corpus,
                                                          monkeypatch):
        """Default compatibility. `full` must arrive EXPLICITLY rather than by
        the callee's own default — otherwise this wiring could regress to
        passing nothing and every test here would still pass."""
        seen = self._capture(monkeypatch)
        api._execute(req(), corpus)
        assert seen["retention_mode"] == "full"
        assert seen["retention_tail"] == api.DEFAULT_RETENTION_TAIL

    def test_an_invalid_mode_is_REFUSED_not_defaulted(self):
        """No silent fallback. `rehearse_chain`'s own refusal says falling back
        to 'full' on a typo is how a certification run OOMs after three hours;
        the request must not be able to produce that state either."""
        with pytest.raises(Exception) as exc:
            req(retention_mode="bunded")
        assert "bunded" in str(exc.value) or "retention_mode" in str(exc.value)

    def test_every_mode_the_engine_accepts_is_offered_by_the_request(self):
        """The two lists must not drift. A mode the engine supports but the
        request cannot express is exactly the defect being fixed here."""
        import typing
        offered = set(typing.get_args(
            api.WealthCoreJobRequest.model_fields["retention_mode"].annotation))
        assert offered == set(api.RETENTION_MODES)

    @pytest.mark.parametrize("mode,extra", [
        ("baseline_replay", {"expected_hashes": {k: "x" for k in HASH_ORDER}}),
        ("experiment", {"change": {"n_slots": 12}, "config": {"n_slots": 12},
                        "baseline_hashes": {k: "x" for k in HASH_ORDER}}),
    ])
    def test_a_mode_that_cannot_honour_it_refuses_it(self, mode, extra):
        """Only the rehearsal retains per-session detail. Accepting `bounded` on
        a replay would let an operator watch it OOM anyway and conclude bounded
        does not work — a dropped setting reading as a failed one."""
        with pytest.raises(HTTPException) as exc:
            api._validate(req(mode=mode, retention_mode="bounded", **extra))
        assert exc.value.status_code == 422
        assert "chain_rehearsal-only" in exc.value.detail

    def test_the_job_start_LOGS_the_retention_setting(self):
        """It was invisible for the whole time it was wrong: nothing printed it
        and it had to be inferred from an RSS curve after the fact."""
        body = self.__class__.__module__ and pathlib.Path(
            api.__file__).read_text()
        start = body.index("async def start_wealth_core_job")
        end = body.index("background_tasks.add_task", start)
        assert "retention_mode=" in body[start:end], (
            "the run's retention setting must be logged at job start")
