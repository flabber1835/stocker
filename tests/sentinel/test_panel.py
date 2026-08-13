"""The read-only panel: its model, its rendering, and its refusal to act.

WHAT THESE PROTECT. The panel replaces Stocker's eight-tab dashboard, including
a trade-approval button, with one page that can only be read. Two classes of
regression matter and neither is cosmetic:

  * a WRITE route, or anything that could reach the broker from a page load.
    A phone refreshing on a desk must not be an unattended API client;
  * a value that looks healthy when it is not — a stalled ingest rendered
    plain, an unreadable source rendered as zero, a pinned exposure that reads
    like a decision. That class is the entire reason the panel exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel.panel import model
from sentinel.panel.render import render
from sentinel.panel.sources import build_panel

NOW = datetime(2026, 8, 9, 22, 47, tzinfo=timezone.utc)


def _panel(*rows, errors=()):
    return model.Panel(rows=list(rows), now=NOW, source_errors=list(errors))


# ── 1. staleness is visible ──────────────────────────────────────────────────

class TestStalenessCannotHide:
    """The evening this was written, a detached `feed-seed` died on a missing
    dependency and read exactly like a running seed. `feed-status` prints "a
    frozen clock here means STALLED, not working" for that reason; a UI has more
    room and less excuse."""

    def test_a_fresh_row_is_not_stale(self):
        r = model.Row("k", "L", "v", model.OK, as_of=NOW - timedelta(minutes=2),
                      freshness=timedelta(minutes=15))
        assert not r.is_stale(NOW)
        assert r.effective_status(NOW) is model.OK

    def test_a_row_past_its_budget_is_STALE_and_downgraded(self):
        r = model.Row("k", "L", "v", model.OK, as_of=NOW - timedelta(hours=3),
                      freshness=timedelta(minutes=15))
        assert r.is_stale(NOW)
        assert r.effective_status(NOW) is model.WARN, (
            "a stale OK still read as OK — the frozen-clock failure exactly")

    def test_staleness_never_IMPROVES_a_status(self):
        r = model.Row("k", "L", "v", model.FAIL, as_of=NOW - timedelta(days=9),
                      freshness=timedelta(minutes=15))
        assert r.effective_status(NOW) is model.FAIL

    def test_a_timeless_row_never_goes_stale(self):
        """Ownership is true until superseded. Ageing it would eventually paint
        an established handover amber for no reason, and a panel that cries
        wolf about its most important row is worse than no panel."""
        r = model.Row("ownership", "Ownership", "FLAT CONFIRMED", model.OK,
                      as_of=NOW - timedelta(days=400))
        assert not r.is_stale(NOW)
        assert r.effective_status(NOW) is model.OK

    def test_the_rendered_page_SAYS_stale(self):
        html = render(_panel(model.Row("k", "Feed", "2026-08-01", model.OK,
                                       as_of=NOW - timedelta(hours=9),
                                       freshness=timedelta(hours=1))))
        assert "STALE" in html


# ── 2. unknown is never zero ─────────────────────────────────────────────────

class TestUnknownIsNeverZero:

    def test_an_unreadable_feed_does_not_render_as_empty(self):
        r = model.feed_row(frontier=None, sessions_behind=None, ready=None,
                           checks_passed=0, checks_total=0, as_of=None,
                           error="connection refused")
        assert r.status is model.UNKNOWN
        assert "UNREADABLE" in r.value

    def test_a_TIMED_OUT_contract_check_is_not_a_FAILED_one(self):
        """`ready is None` means NO VERDICT EXISTS.

        It used to mean "the check timed out inside this page load" — the panel
        computed the contract itself and gave up first during a seed. It now
        reads a stored verdict (#14), so None means nothing has ever computed
        one. The rule is unchanged and is the point of this test: one flag must
        not answer both "the evidence says no" and "there is no evidence". Same
        rule as the crash brake's `evaluable`.
        """
        r = model.feed_row(frontier="2026-08-08", sessions_behind=1, ready=None,
                           checks_passed=0, checks_total=0, as_of=NOW)
        assert r.status is model.WARN, "an unmeasured contract reported as failed"
        assert "not checked" in r.detail.lower()
        failed = model.feed_row(frontier="2026-08-08", sessions_behind=1,
                                ready=False, checks_passed=7, checks_total=9,
                                as_of=NOW)
        assert failed.status is model.FAIL

    def test_an_EMPTY_feed_is_distinct_from_an_UNREADABLE_one(self):
        """"nothing ingested yet" and "the database is unreachable" call for
        completely different actions."""
        empty = model.feed_row(frontier=None, sessions_behind=None, ready=None,
                               checks_passed=0, checks_total=0, as_of=None)
        assert empty.status is model.WARN and "EMPTY" in empty.value

    def test_a_source_failure_makes_the_WHOLE_panel_fail(self):
        p = _panel(model.Row("k", "L", "v", model.OK), errors=["feed database"])
        assert p.overall is model.FAIL

    def test_the_panel_still_RENDERS_when_every_source_is_down(self):
        """The panel's job is to reveal that something is broken, so it must not
        go blank when something is broken. A 500 here would hide the ownership
        row, which is the fact an operator most needs during an outage."""
        p = build_panel(state_dir="/nonexistent", database_url="", now=NOW)
        html = render(p)
        assert "SENTINEL" in html and "Ownership" in html
        assert len(html) > 1000


# ── 3. pending is not failure ────────────────────────────────────────────────

class TestPendingIsNotFailure:

    def test_pending_rows_do_not_drive_the_headline(self):
        """A half-built system is mostly PENDING. Letting that drive the badge
        would leave it permanently amber and teach the reader to ignore it."""
        p = _panel(model.Row("a", "A", "x", model.OK),
                   model.Row("b", "B", "y", model.PENDING))
        assert p.overall is model.OK

    def test_the_unbuilt_rows_are_PENDING_not_FAIL(self):
        for r in (model.book_row(available=False),
                  model.broker_row(available=False),
                  model.terminals_row(counters=None)):
            assert r.status is model.PENDING, r.key

    def test_the_book_row_NAMES_what_it_is_waiting_for(self):
        assert "SessionState" in model.book_row(available=False).detail


# ── 4. the rows that carry the real warnings ─────────────────────────────────

class TestTheRowsThatMatter:

    def test_an_UNINITIALIZED_store_reads_NOT_ESTABLISHED(self):
        """Where every deployment starts, and the most common state this row
        will ever be read in. Calling it "handover in progress" would misreport
        the most important row on the page."""
        r = model.ownership_row(state="UNINITIALIZED", at=None)
        assert r.value == "NOT ESTABLISHED" and r.status is model.WARN

    def test_a_PART_WAY_handover_is_called_out(self):
        r = model.ownership_row(state="LIQUIDATION_SUBMITTED", at=NOW)
        assert r.status is model.WARN
        assert "part-way" in r.detail

    def test_established_ownership_does_not_claim_current_flatness(self):
        r = model.ownership_row(state="SENTINEL_OWNERSHIP_ESTABLISHED", at=NOW)
        assert r.status is model.OK and r.value == "SENTINEL OWNED"
        assert "historical flat handover" in r.detail
        assert "current positions" in r.detail
        assert "FLAT" not in r.value

    def test_a_CORRUPT_log_is_UNKNOWN_not_reassuring(self):
        r = model.ownership_row(state=None, at=None, error="torn line 3")
        assert r.status is model.UNKNOWN
        assert "NOT ESTABLISHED" not in r.value

    def test_a_pinned_exposure_SAYS_pinned(self):
        """`1.00 PINNED` and `1.00 computed` are different facts. When items
        F-H land, this row is where an operator learns the number became a
        DECISION — the change must be visible, not inferred from a value that
        did not move."""
        r = model.exposure_row(exposure=1.0, controller_active=False)
        assert "PINNED" in r.value and r.status is model.PENDING
        live = model.exposure_row(exposure=0.55, controller_active=True)
        assert "PINNED" not in live.value and live.status is model.OK

    def test_unknown_runtime_values_never_fall_back_to_placeholders(self):
        rows = (
            model.exposure_row(exposure=None, controller_active=None),
            model.book_row(available=None),
            model.terminals_row(error="state unreadable"),
            model.broker_row(available=None),
        )
        assert all(row.status is model.UNKNOWN for row in rows)
        assert all(row.value == "UNKNOWN" for row in rows)

    def test_automation_names_the_absence_of_durable_control(self):
        row = model.automation_row()
        assert row.value == "NOT INSTALLED"
        assert row.status is model.PENDING
        assert "control schema" in row.detail

    def test_execution_authority_names_the_missing_schema(self):
        row = model.execution_authority_row()
        assert row.value == "NOT INSTALLED"
        assert row.status is model.FAIL
        assert "authority schema" in row.detail

    def test_the_panel_always_includes_the_fail_closed_authority_row(self):
        panel = build_panel(state_dir="/nonexistent", database_url="", now=NOW)
        row = panel.row("authority")
        assert row is not None
        assert row.value == "UNKNOWN" and row.status is model.UNKNOWN

    def test_disabled_and_killed_are_healthy_policy_but_not_ready(self):
        disabled = model.automation_row(
            installed=True, enabled=False, killed=True, generation=3)
        killed = model.automation_row(
            installed=True, enabled=True, killed=True, generation=4)

        assert disabled.value == "DISABLED"
        assert disabled.status is model.PENDING
        assert "supervisor-healthy" in disabled.detail
        assert killed.value == "ENABLED · KILLED"
        assert killed.status is model.WARN

    def test_lifecycle_active_never_manufactures_a_runtime_verdict(self):
        row = model.execution_authority_row(
            installed=True, lifecycle_status="ACTIVE",
            certificate_sha256="a" * 64, authority_generation=7,
            expires_at=NOW + timedelta(days=1), lifecycle_current=True)

        assert row.value == "UNKNOWN" and row.status is model.UNKNOWN
        assert "no durable runtime authority verdict" in row.detail
        assert "lifecycle-only: ACTIVE" in row.detail

    @pytest.mark.parametrize(
        ("lifecycle_status", "certificate_sha256", "lifecycle_current"),
        (("REVOKED", "a" * 64, False),
         ("ACTIVE", "a" * 64, False),
         (None, None, False)),
    )
    def test_lifecycle_failure_overrides_a_cached_runtime_pass(
            self, lifecycle_status, certificate_sha256, lifecycle_current):
        row = model.execution_authority_row(
            installed=True, runtime_verdict="PASS",
            runtime_detail="claims matched before lifecycle changed",
            checked_at=NOW, lifecycle_status=lifecycle_status,
            certificate_sha256=certificate_sha256,
            expires_at=NOW - timedelta(seconds=1),
            authority_generation=8, lifecycle_current=lifecycle_current,
            verdict_binding_matches=True)

        assert row.status is model.FAIL
        assert "LIFECYCLE INVALID" in row.value
        assert "cannot override" in row.detail

    def test_a_stalled_ingest_has_a_TIGHT_freshness_budget(self):
        r = model.ingest_row(kind="seed", status="running", chunks_done=2,
                             chunks_total=31, rows_written=739_126,
                             current_chunk="1998",
                             updated_at=NOW - timedelta(hours=2))
        assert r.is_stale(NOW), "a two-hour-frozen seed read as healthy"

    def test_a_failed_ingest_shows_its_ERROR(self):
        r = model.ingest_row(kind="seed", status="failed", chunks_done=0,
                             chunks_total=31, rows_written=0,
                             current_chunk="tickers", updated_at=NOW,
                             error_message="No module named 'httpx'")
        assert r.status is model.FAIL and "httpx" in r.detail

    def test_blocking_terminals_OUTRANK_a_clean_looking_book(self):
        """The specific reading worth surfacing: no last-mark settlements
        alongside unresolved events means the book is blocking rather than
        settling, and everything downstream is unevaluable."""
        r = model.terminals_row(counters={"unresolved_terminal_events": 3,
                                          "derived_last_mark_settlements": 0})
        assert r.status is model.FAIL
        assert "unevaluable" in r.detail

    def test_settled_terminals_report_the_MIX(self):
        r = model.terminals_row(counters={"derived_last_mark_settlements": 8,
                                          "pending_terms_carried": 1})
        assert r.status is model.OK and "last-mark 8" in r.value

    def test_an_unresolved_terminal_makes_the_BOOK_row_fail(self):
        r = model.book_row(available=True, slots_used=23, slots_total=25,
                           nav=1_012_443, cash=41_002, blocked=0,
                           unresolved_terminals=2, pending_actions=0)
        assert r.status is model.FAIL
        assert "UNRESOLVED TERMINALS 2" in r.detail, (
            "the NAV is readable without the caveat beside it")


# ── 4b. it cannot hang ───────────────────────────────────────────────────────

class TestItCannotHang:
    """THE incident this class exists for (2026-08-09, first deploy).

    `/health` returned instantly and `/` never returned at all. The panel issued
    unbounded queries, and the readiness check scans `sentinel_bars` — which was
    mid-bulk-load from a running seed. The page hung forever, which is
    indistinguishable from a dead server and gives an operator nothing to act
    on, at exactly the moment they opened the panel to find out what was
    happening.

    A panel that reports UNKNOWN is useful. A panel that hangs is not a panel.
    """

    def test_the_dsn_carries_a_CONNECT_timeout(self):
        """A statement timeout does nothing if the CONNECT never completes."""
        from sentinel.panel.sources import CONNECT_TIMEOUT_SECONDS, _bounded_dsn
        out = _bounded_dsn("postgresql://u:p@host:5432/db")
        assert f"connect_timeout={CONNECT_TIMEOUT_SECONDS}" in out

    def test_an_existing_connect_timeout_is_not_doubled(self):
        from sentinel.panel.sources import _bounded_dsn
        dsn = "postgresql://u:p@h/db?connect_timeout=9"
        assert _bounded_dsn(dsn) == dsn

    def test_it_appends_correctly_to_a_dsn_that_ALREADY_has_params(self):
        from sentinel.panel.sources import _bounded_dsn
        assert "?sslmode=require&connect_timeout=" in _bounded_dsn(
            "postgresql://u:p@h/db?sslmode=require")

    def test_the_readiness_budget_is_TIGHTER_than_the_statement_budget(self):
        """The contract check is the expensive read and the least urgent one.
        It must be the first thing given up, not the thing that costs the page
        its frontier and its ingest row."""
        from sentinel.panel import sources
        assert sources.READINESS_TIMEOUT_MS < sources.STATEMENT_TIMEOUT_MS

    def test_a_SLOW_query_does_not_cost_the_page_its_other_rows(self):
        """Reported in use, one deploy after the hang fix: the whole feed read
        as `source unreadable — QueryCanceled` because the FRONTIER scan
        (`MAX(session)` over a table being bulk-loaded) timed out. Everything
        was grouped under one guard, so it took the INGEST row with it — the one
        row that can say whether the seed is alive, and the only reason to open
        the panel during an ingest.

        Each read now has its own timeout AND its own rollback, so a slow one
        cannot cascade.
        """
        import psycopg

        calls = []

        class FakeConn:
            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a):
                return None

            def rollback(self):
                calls.append("rollback")

            def close(self):
                pass

        from sentinel.panel.sources import _read

        conn = FakeConn()

        def slow(_c):
            raise psycopg.errors.QueryCanceled(
                "canceling statement due to statement timeout")

        value, err = _read(conn, slow, 100, default=None)
        assert value is None and err == "timed out", (
            "a timeout must read as a timeout, not as a driver traceback")
        assert "rollback" in calls, (
            "the aborted transaction was left in place, so the NEXT read fails "
            "with InFailedSqlTransaction and one slow query becomes a dead feed")

        ok, err2 = _read(conn, lambda _c: "still works", 100)
        assert ok == "still works" and err2 is None

    def test_a_frontier_timeout_DURING_AN_INGEST_reads_as_BUILDING(self):
        """Reported in use: the panel showed `FEED UNREADABLE — frontier timed
        out` while a healthy seed was writing that very table.

        Technically true and operationally wrong. The frontier is `MAX(session)`
        over `sentinel_bars`, and a seed is bulk-loading `sentinel_bars`, so the
        corpus is BUILDING — which the ingest row already says. An alarm here
        would fire for the several hours a seed takes, every time.
        """
        r = model.feed_row(frontier=None, sessions_behind=None, ready=None,
                           checks_passed=0, checks_total=0, as_of=NOW,
                           error="frontier timed out", ingest_running=True)
        assert r.status is model.PENDING and r.value == "BUILDING"
        # With NO ingest running, the same timeout IS a real unknown.
        idle = model.feed_row(frontier=None, sessions_behind=None, ready=None,
                              checks_passed=0, checks_total=0, as_of=NOW,
                              error="frontier timed out", ingest_running=False)
        assert idle.status is model.UNKNOWN and idle.value == "UNREADABLE"

    def test_a_timed_out_FRONTIER_is_not_a_source_failure(self):
        """`source_errors` is the banner meaning "the panel could not read the
        world". One slow scan does not qualify: the rows say so themselves, in
        the right place, and a banner for it would cry wolf on every page load
        during a seed."""
        r = model.feed_row(frontier=None, sessions_behind=None, ready=None,
                           checks_passed=0, checks_total=0, as_of=NOW,
                           error="frontier timed out")
        assert r.status is model.UNKNOWN
        assert "timed out" in r.detail

    def test_a_DEAD_port_does_not_hang_the_page(self):
        """A real socket that accepts and never speaks Postgres — the closest
        reproduction of a busy server available without one. The page must come
        back, with an unreadable feed row, well inside a browser's patience."""
        import socket
        import time

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)                       # accepts, never replies
        port = srv.getsockname()[1]
        try:
            t0 = time.monotonic()
            p = build_panel(state_dir="/nonexistent",
                            database_url=f"postgresql://u:p@127.0.0.1:{port}/db",
                            now=NOW)
            elapsed = time.monotonic() - t0
        finally:
            srv.close()

        assert elapsed < 30, f"the panel blocked for {elapsed:.1f}s"
        assert p.row("feed").status is model.UNKNOWN
        assert p.source_errors, "it hid a dead database instead of reporting it"
        assert p.row("ownership") is not None, (
            "a dead feed cost the page its ownership row — the one fact that "
            "matters most during an outage")


# ── 4c. runtime rows are durable facts ───────────────────────────────────────

class TestRuntimeRowsAreDurableFacts:

    @staticmethod
    def _state():
        return {
            "version": 3,
            "last_processed_session": "2026-08-12",
            "wealth_core": {
                "slots": {"0": {}, "1": {}},
                "episodes": {"0": {}},
                "cash": "350",
                "unresolved_terminals": {},
                "terminal_pending_terms": {},
            },
            "pending": [{"security_id": "SEC-B"}],
            "last_evidence": {
                "wealth_core": {
                    "blocked": False,
                    "estimated_equity": "1000",
                },
            },
            "last_decision": {
                "session": "2026-08-12",
                "target_core_exposure": "0.55",
            },
        }

    @staticmethod
    def _connection():
        class Connection:
            closed = False

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, *_args):
                return None

            def rollback(self):
                return None

            def close(self):
                self.closed = True

        return Connection()

    def _install_sources(self, monkeypatch, *, schema=None, state=None,
                         plan=None, rollout=None, observation=None,
                         commands=None):
        from sentinel.feed import store as feed_store
        from sentinel.panel import sources

        conn = self._connection()
        complete_schema = {
            table: set(columns)
            for table, columns in sources._RUNTIME_COLUMNS.items()
        }
        monkeypatch.setattr(feed_store, "connect", lambda _dsn: conn)
        monkeypatch.setattr(
            sources, "_runtime_schema",
            lambda _conn: complete_schema if schema is None else schema)
        monkeypatch.setattr(sources, "_canonical_state", lambda _conn: state)
        monkeypatch.setattr(sources, "_current_plan", lambda _conn: plan)
        monkeypatch.setattr(
            sources, "_rollout_state",
            lambda _conn: rollout or {
                "mode": "CONTROLLER", "version": 2,
                "certificate_sha256": "cert-controller",
                "updated_at": NOW,
            })
        monkeypatch.setattr(
            sources, "_latest_observation", lambda _conn: observation)
        monkeypatch.setattr(
            sources, "_active_commands", lambda _conn: commands)
        return sources, conn

    def test_current_plan_book_and_observation_replace_the_old_placeholders(
            self, monkeypatch):
        state = {
            "session": "2026-08-12", "state": self._state(),
            "updated_at": NOW,
        }
        plan = {
            "plan_id": "sentinel-plan", "decision_session": "2026-08-12",
            "effective_session": "2026-08-13",
            "target_exposure": Decimal("0.55"),
            "unpriced_securities": [], "created_at": NOW,
            "rollout_mode": "CONTROLLER", "rollout_version": 2,
            "rollout_certificate_sha256": "cert-controller",
        }
        observation = {
            "observed_at": NOW, "completeness": "COMPLETE",
            "positions": {"SEC-A": "10", "SEC-Z": "0"},
            "orders": [{"state": "ACKNOWLEDGED"}],
            "runtime_state": "RUNNING",
        }
        commands = {
            "counts": {"ACKNOWLEDGED": 1}, "updated_at": NOW,
        }
        sources, conn = self._install_sources(
            monkeypatch, state=state, plan=plan, observation=observation,
            commands=commands)

        rows, errors = sources._runtime_rows("postgresql://panel@db/sentinel")

        assert errors == []
        by_key = {row.key: row for row in rows}
        assert by_key["exposure"].value == "0.55"
        assert "durable current controller plan" in by_key["exposure"].detail
        assert by_key["book"].value.startswith("1/2 slots · NAV $1,000")
        assert "1 pending" in by_key["book"].detail
        assert by_key["terminals"].value == "CLEAR"
        assert by_key["broker"].value == "1 positions · 1 working"
        assert by_key["broker"].status is model.OK
        assert conn.closed

    def test_plan_state_mismatch_is_unknown_not_a_computed_exposure(
            self, monkeypatch):
        state = {
            "session": "2026-08-12", "state": self._state(),
            "updated_at": NOW,
        }
        plan = {
            "plan_id": "sentinel-plan", "decision_session": "2026-08-11",
            "effective_session": "2026-08-12",
            "target_exposure": Decimal("1"),
            "unpriced_securities": [], "created_at": NOW,
            "rollout_mode": "CONTROLLER", "rollout_version": 2,
            "rollout_certificate_sha256": "cert-controller",
        }
        sources, _conn = self._install_sources(
            monkeypatch, state=state, plan=plan, observation=None,
            commands={"counts": {}, "updated_at": None})

        rows, errors = sources._runtime_rows("postgresql://panel@db/sentinel")

        exposure = next(row for row in rows if row.key == "exposure")
        assert exposure.status is model.UNKNOWN
        assert "disagree" in exposure.detail
        assert errors, "a plan/state mismatch was hidden from the source banner"

    def test_pinned_rollout_reports_one_even_when_controller_decides_point55(
            self, monkeypatch):
        state = {
            "session": "2026-08-12", "state": self._state(),
            "updated_at": NOW,
        }
        plan = {
            "plan_id": "sentinel-plan", "decision_session": "2026-08-12",
            "effective_session": "2026-08-13",
            "target_exposure": Decimal("1"),
            "unpriced_securities": [], "created_at": NOW,
            "rollout_mode": "PINNED_1_00", "rollout_version": 1,
            "rollout_certificate_sha256": None,
        }
        rollout = {
            "mode": "PINNED_1_00", "version": 1,
            "certificate_sha256": None, "updated_at": NOW,
        }
        sources, _conn = self._install_sources(
            monkeypatch, state=state, plan=plan, rollout=rollout,
            observation=None, commands={"counts": {}, "updated_at": None})

        rows, errors = sources._runtime_rows("postgresql://panel@db/sentinel")
        exposure = next(row for row in rows if row.key == "exposure")

        assert errors == []
        assert exposure.value == "1.00 PINNED"
        assert exposure.status is model.PENDING

    def test_partial_schema_is_feature_detected_and_never_queried(
            self, monkeypatch):
        sources, conn = self._install_sources(
            monkeypatch, schema={}, state=pytest.fail, plan=pytest.fail,
            rollout=pytest.fail, observation=pytest.fail,
            commands=pytest.fail)

        rows, errors = sources._runtime_rows("postgresql://panel@db/sentinel")

        assert all(row.status is model.UNKNOWN for row in rows)
        assert len(errors) == 5
        assert all("missing schema" in error for error in errors)
        assert conn.closed

    def test_malformed_canonical_json_does_not_hide_broker_evidence(
            self, monkeypatch):
        malformed = self._state()
        malformed["last_evidence"]["wealth_core"]["estimated_equity"] = "NaN"
        state = {
            "session": "2026-08-12", "state": malformed,
            "updated_at": NOW,
        }
        observation = {
            "observed_at": NOW, "completeness": "COMPLETE",
            "positions": {}, "orders": [], "runtime_state": "RUNNING",
        }
        sources, _conn = self._install_sources(
            monkeypatch, state=state, plan=None, observation=observation,
            commands={"counts": {}, "updated_at": None})

        rows, errors = sources._runtime_rows("postgresql://panel@db/sentinel")
        by_key = {row.key: row for row in rows}

        assert by_key["book"].status is model.UNKNOWN
        assert by_key["exposure"].status is model.UNKNOWN
        assert by_key["terminals"].status is model.UNKNOWN
        assert by_key["broker"].status is model.OK
        assert any("state" in error for error in errors)

    def test_incomplete_or_indeterminate_broker_evidence_never_reads_clean(
            self):
        incomplete = model.broker_row(
            available=True, positions=3, completeness="TRUNCATED",
            runtime_state="RECONCILING")
        uncertain = model.broker_row(
            available=True, positions=3, completeness="COMPLETE",
            runtime_state="RUNNING", uncertain_commands=1)
        assert incomplete.status is model.FAIL
        assert uncertain.status is model.FAIL
        assert "indeterminate" in uncertain.detail


# ── 5. it cannot act ─────────────────────────────────────────────────────────

class TestAutomationRowsAreDurableFacts:

    @staticmethod
    def _connection():
        class Connection:
            closed = False

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, *_args):
                return None

            def rollback(self):
                return None

            def close(self):
                self.closed = True

        return Connection()

    def _install(self, monkeypatch, *, found=None, control=None,
                 lease=None, cycle=None, alerts=None, lifecycle=None,
                 instance=None, service_verdict=None):
        from sentinel.feed import store as feed_store
        from sentinel.panel import sources

        conn = self._connection()
        complete = {
            table: set(columns) for table, columns in {
                **sources._AUTOMATION_COLUMNS,
                **sources._AUTHORITY_COLUMNS,
            }.items()
        }
        monkeypatch.setattr(feed_store, "connect", lambda _dsn: conn)
        monkeypatch.setattr(
            sources, "_automation_schema",
            lambda _conn: complete if found is None else found)
        monkeypatch.setattr(
            sources, "_automation_control", lambda _conn, _found: control)
        monkeypatch.setattr(
            sources, "_automation_lease",
            lambda _conn, _generation: lease)
        monkeypatch.setattr(
            sources, "_latest_automation_cycle", lambda _conn: cycle)
        monkeypatch.setattr(
            sources, "_automation_alert_counts", lambda _conn: alerts)
        monkeypatch.setattr(
            sources, "_latest_automation_instance", lambda _conn: instance)
        monkeypatch.setattr(
            sources, "_authority_lifecycle", lambda _conn: lifecycle)
        monkeypatch.setattr(
            sources, "_service_authority_verdict",
            lambda _conn, _found: service_verdict)
        return sources, conn

    def test_projects_policy_lease_cycle_alerts_and_persisted_verdict(
            self, monkeypatch):
        sources, conn = self._install(
            monkeypatch,
            control={
                "enabled": True, "generation": 9, "killed": False,
                "certificate_sha256": "a" * 64,
                "updated_at": NOW, "authority_verdict": "VALID",
                "authority_detail": "all runtime claims matched",
                "authority_checked_at": NOW,
            },
            lease={
                "holder": "appliance-a", "fence": 41,
                "heartbeat_at": NOW,
                "expires_at": NOW + timedelta(seconds=30), "active": True,
            },
            cycle={
                "cycle_id": "cycle-2026-08-13", "state": "RETRY_WAIT",
                "decision_session": "2026-08-12",
                "effective_session": "2026-08-13",
                "next_wake_at": NOW + timedelta(minutes=2),
                "clean_reconciliation_id": "recon-clean-8",
                "failure_code": "PUBLICATION_PENDING",
                "failure_detail": "waiting for pinned publication",
                "updated_at": NOW,
            },
            alerts={
                "pending": 2, "dead_letter": 1, "unacknowledged": 3,
                "updated_at": NOW,
            },
            lifecycle={
                "authority_generation": 7,
                "certificate_sha256": "a" * 64,
                "expires_at": NOW + timedelta(days=2),
                "lifecycle_status": "ACTIVE", "lifecycle_current": True,
            })

        rows, errors = sources._automation_rows(
            "postgresql://panel@db/sentinel")
        by_key = {row.key: row for row in rows}

        assert errors == []
        assert by_key["automation"].value == "ENABLED · KILL RELEASED"
        assert by_key["automation_leader"].value == "appliance-a · fence 41"
        assert by_key["automation_cycle"].value == "RETRY_WAIT"
        assert "recon-clean-8" in by_key["automation_cycle"].detail
        assert "PUBLICATION_PENDING" in by_key["automation_cycle"].detail
        assert by_key["automation_alerts"].value == (
            "2 pending · 1 DLQ · 3 unacked")
        assert by_key["automation_alerts"].status is model.FAIL
        assert by_key["authority"].value.startswith("VALID")
        assert by_key["authority"].status is model.OK
        assert "lifecycle-only: ACTIVE" in by_key["authority"].detail
        assert conn.closed

    def test_absent_optional_runtime_verdict_stays_unknown(self, monkeypatch):
        sources, _conn = self._install(
            monkeypatch,
            control={
                "enabled": False, "generation": 1, "killed": True,
                "certificate_sha256": "b" * 64,
                "updated_at": NOW, "authority_verdict": None,
                "authority_detail": None, "authority_checked_at": None,
            },
            lease={
                "holder": None, "fence": 0, "heartbeat_at": None,
                "expires_at": None, "active": False,
            }, cycle=None,
            alerts={
                "pending": 0, "dead_letter": 0, "unacknowledged": 0,
                "updated_at": None,
            },
            lifecycle={
                "authority_generation": 3,
                "certificate_sha256": "b" * 64,
                "expires_at": NOW + timedelta(days=1),
                "lifecycle_status": "ACTIVE", "lifecycle_current": True,
            })

        rows, errors = sources._automation_rows(
            "postgresql://panel@db/sentinel")
        authority = next(row for row in rows if row.key == "authority")

        assert errors == []
        assert authority.status is model.UNKNOWN
        assert "no durable runtime authority verdict" in authority.detail

    def test_source_projection_never_renders_revoked_cached_pass_green(
            self, monkeypatch):
        sources, _conn = self._install(
            monkeypatch,
            control={
                "enabled": True, "generation": 10, "killed": False,
                "certificate_sha256": "c" * 64,
                "updated_at": NOW, "authority_verdict": "PASS",
                "authority_detail": "valid before revocation",
                "authority_checked_at": NOW,
            },
            lease={
                "holder": "appliance-a", "fence": 42,
                "heartbeat_at": NOW,
                "expires_at": NOW + timedelta(seconds=30), "active": True,
            }, cycle=None,
            alerts={
                "pending": 0, "dead_letter": 0, "unacknowledged": 0,
                "updated_at": NOW,
            },
            lifecycle={
                "authority_generation": 9,
                "certificate_sha256": "c" * 64,
                "expires_at": NOW + timedelta(days=1),
                "lifecycle_status": "REVOKED", "lifecycle_current": False,
            })

        rows, errors = sources._automation_rows(
            "postgresql://panel@db/sentinel")
        authority = next(row for row in rows if row.key == "authority")

        assert errors == []
        assert authority.status is model.FAIL
        assert "LIFECYCLE INVALID" in authority.value
        assert "REVOKED" in authority.detail

    def test_completely_absent_schema_is_not_installed_not_unreadable(
            self, monkeypatch):
        sources, _conn = self._install(
            monkeypatch, found={}, control=pytest.fail, lease=pytest.fail,
            cycle=pytest.fail, alerts=pytest.fail, lifecycle=pytest.fail)

        rows, errors = sources._automation_rows(
            "postgresql://panel@db/sentinel")
        by_key = {row.key: row for row in rows}

        assert errors == []
        assert by_key["automation"].value == "NOT INSTALLED"
        assert by_key["authority"].value == "NOT INSTALLED"

    def test_partial_schema_is_unknown_and_never_queried(self, monkeypatch):
        from sentinel.panel import sources as source_module

        partial = {
            table: set() for table in {
                **source_module._AUTOMATION_COLUMNS,
                **source_module._AUTHORITY_COLUMNS,
            }
        }
        partial["sentinel_automation_control"] = {"id", "enabled"}
        sources, _conn = self._install(
            monkeypatch, found=partial, control=pytest.fail,
            lease=pytest.fail, cycle=pytest.fail, alerts=pytest.fail,
            lifecycle=pytest.fail)

        rows, errors = sources._automation_rows(
            "postgresql://panel@db/sentinel")

        assert errors
        assert all(row.status is model.UNKNOWN for row in rows[1:])
        assert "missing schema sentinel_automation_control" in errors[0]

    def test_automation_panel_queries_are_structurally_select_only(self):
        import inspect
        import re

        from sentinel.panel import sources

        query_functions = (
            sources._automation_schema, sources._automation_control,
            sources._automation_lease, sources._latest_automation_cycle,
            sources._automation_alert_counts,
            sources._latest_automation_instance,
            sources._service_authority_verdict,
            sources._authority_lifecycle,
        )
        body = "\n".join(inspect.getsource(fn) for fn in query_functions)
        assert re.search(
            r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|CREATE|DROP)\b", body
        ) is None
        assert "build_broker" not in body


class TestItCannotAct:

    def test_there_are_NO_write_routes(self):
        from sentinel.panel.app import app
        for route in app.routes:
            for m in (getattr(route, "methods", None) or set()):
                assert m in {"GET", "HEAD", "OPTIONS"}, (
                    f"{route.path} accepts {m}. Sentinel's write paths "
                    f"liquidate accounts; this process must not have verbs.")

    def test_the_page_has_no_form_or_button(self):
        html = render(build_panel(state_dir="/nonexistent", database_url="",
                                  now=NOW))
        low = html.lower()
        for tag in ("<form", "<button", "<input", 'type="submit"'):
            assert tag not in low, f"{tag} on a read-only panel"

    def test_no_PERFORMANCE_figure_is_shown(self):
        """The certification rule: no Wealth Core performance number without the
        settlement counters and the episode audit beside it. A dashboard is
        precisely where a bare number gets screenshotted and quoted."""
        html = render(build_panel(state_dir="/nonexistent", database_url="",
                                  now=NOW)).lower()
        for word in ("cagr", "sharpe", "total return", "p&l"):
            assert word not in html, f"{word!r} on the panel"

    def test_the_sources_module_never_imports_a_BROKER(self):
        """A page refreshing every 30 seconds must not produce broker traffic."""
        import inspect

        from sentinel.panel import sources
        src = inspect.getsource(sources)
        assert "build_broker" not in src and "broker" not in src.split("\n\n")[0]

    def test_health_refuses_when_database_configuration_is_missing(
            self, monkeypatch):
        from fastapi import HTTPException
        from sentinel.panel import app as app_mod

        monkeypatch.delenv("SENTINEL_DATABASE_URL", raising=False)
        with pytest.raises(HTTPException) as raised:
            app_mod.health()
        assert raised.value.status_code == 503
        assert "SENTINEL_DATABASE_URL is unset" in raised.value.detail

    def test_health_proves_the_required_database_schema(self, monkeypatch):
        from sentinel.feed import store as feed_store
        from sentinel.panel import app as app_mod

        class Conn:
            def __init__(self):
                self.statements = []
                self.closed = False

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement):
                self.statements.append(str(statement))

            def close(self):
                self.closed = True

        conn = Conn()
        opened = []
        monkeypatch.setenv(
            "SENTINEL_DATABASE_URL", "postgresql://panel@db/sentinel")
        monkeypatch.setattr(
            feed_store, "connect",
            lambda dsn: opened.append(dsn) or conn)

        assert app_mod.health() == {
            "status": "ready", "service": "sentinel-panel"}
        assert opened and "connect_timeout=" in opened[0]
        sql = "\n".join(conn.statements)
        for table in (
                "sentinel_account_binding", "sentinel_bars",
                "sentinel_corpus_publications",
                "sentinel_readiness_snapshots", "feed_ingest_runs",
                "sentinel_processed_sessions", "sentinel_execution_plans",
                "sentinel_rollout_state", "sentinel_observations",
                "sentinel_commands"):
            assert table in sql
        assert sql.count("LIMIT 0") == len(app_mod._REQUIRED_SCHEMA_PROBES)
        assert conn.closed

    def test_health_refuses_an_old_or_partial_schema_and_closes(
            self, monkeypatch):
        from fastapi import HTTPException
        from sentinel.feed import store as feed_store
        from sentinel.panel import app as app_mod

        class Conn:
            closed = False

            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement):
                if "sentinel_bars" in str(statement):
                    raise RuntimeError("column last_written_run_id missing")

            def close(self):
                self.closed = True

        conn = Conn()
        monkeypatch.setenv(
            "SENTINEL_DATABASE_URL", "postgresql://panel@db/sentinel")
        monkeypatch.setattr(feed_store, "connect", lambda _dsn: conn)

        with pytest.raises(HTTPException) as raised:
            app_mod.health()
        assert raised.value.status_code == 503
        assert "schema not ready" in raised.value.detail
        assert "last_written_run_id missing" in raised.value.detail
        assert conn.closed

    def test_health_reloads_database_configuration_each_request(
            self, monkeypatch):
        from sentinel.panel import app as app_mod

        seen = []
        monkeypatch.setattr(
            app_mod, "_probe_database", lambda dsn: seen.append(dsn))
        monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://first/db")
        app_mod.health()
        monkeypatch.setenv("SENTINEL_DATABASE_URL", "postgresql://second/db")
        app_mod.health()
        assert seen == ["postgresql://first/db", "postgresql://second/db"]


# ── 6. it renders ────────────────────────────────────────────────────────────

class TestItRenders:

    def test_the_html_is_wellformed_enough_to_parse(self):
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.n = 0

            def handle_starttag(self, tag, attrs):
                self.n += 1

        p = P()
        p.feed(render(build_panel(state_dir="/nonexistent", database_url="",
                                  now=NOW)))
        assert p.n > 20

    def test_it_escapes_source_text(self):
        """Error strings reach this page from drivers and vendors. They are not
        trusted input."""
        html = render(_panel(model.Row("k", "L", "<script>x</script>",
                                       model.OK)))
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html

    def test_it_declares_a_MOBILE_viewport(self):
        html = render(build_panel(state_dir="/nonexistent", database_url="",
                                  now=NOW))
        assert "width=device-width" in html
        assert "viewport-fit=cover" in html, (
            "without this the iPhone safe areas are not respected and content "
            "sits under the notch or the home indicator")

    def test_it_defines_BOTH_themes_without_a_media_only_colour(self):
        """The panel is read on a phone in a dark room. Every colour must have a
        definition on bare `:root`, or a viewer whose theme is unset gets an
        undefined variable and an unstyled page."""
        from sentinel.panel.render import CSS
        base = CSS.split("@media")[0]
        for var in ("--bg", "--card", "--ink", "--ok", "--warn", "--fail"):
            assert var in base, f"{var} has no light-mode definition"
        assert "prefers-color-scheme:dark" in CSS
