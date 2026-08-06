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
import os
import pathlib

import pytest

os.environ.setdefault(
    "BT_DATABASE_URL", "postgresql+asyncpg://smoke:smoke@localhost/smoke")

from fastapi import HTTPException  # noqa: E402

from app import wealth_core_api as api  # noqa: E402
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
        assert "load_sessions(conn, start, end)" in src
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

    def test_rows_are_MATERIALISED_not_a_live_cursor(self):
        """A cursor bound to the loop's connection, iterated in the worker
        thread, is a use-after-free that shows up as intermittent corruption
        rather than an error."""
        r = api._Rows([{"a": 1}, {"a": 2}])
        assert list(r.mappings()) == [{"a": 1}, {"a": 2}]
        assert list(r) == [{"a": 1}, {"a": 2}], "re-iterable"
        assert r.first() == {"a": 1}

    def test_an_empty_result_first_is_None_not_an_IndexError(self):
        assert api._Rows([]).first() is None

    def test_the_bridge_marshals_back_to_the_LOOP(self):
        """`asyncio.run_coroutine_threadsafe` is load-bearing: calling the async
        connection from the worker thread directly would silently return a
        coroutine object the loader would then treat as rows."""
        src = ast.parse((REPO / "services" / "bt-engine" / "app" /
                         "wealth_core_api.py").read_text())
        names = {n.attr for n in ast.walk(src) if isinstance(n, ast.Attribute)}
        assert "run_coroutine_threadsafe" in names
