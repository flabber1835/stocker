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
        assert "item E" in model.book_row(available=False).detail


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

    def test_established_ownership_is_OK(self):
        r = model.ownership_row(state="SENTINEL_OWNERSHIP_ESTABLISHED", at=NOW)
        assert r.status is model.OK and "FLAT CONFIRMED" in r.value

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


# ── 5. it cannot act ─────────────────────────────────────────────────────────

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

    def test_health_does_NO_io(self):
        """Stocker's lesson: a `/health` that probes a dependency reports
        someone else's outage as its own death and blows the healthcheck
        budget."""
        import inspect

        from sentinel.panel import app as app_mod
        src = inspect.getsource(app_mod.health)
        for marker in ("connect", "build_panel", "open(", "await"):
            assert marker not in src


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
