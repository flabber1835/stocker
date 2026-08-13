"""Pre-start warm-up: a dated replay must be a backtest FROM its start date.

THE DEFECT. `_load_corpus` loaded bars only between the requested dates, and
nothing called `Feed.warmup` outside the test suite. The signal needs
`REQUIRED_CLOSES` (127) observations, so a run starting 2021-01-01 could not
rank a single name until roughly session 127 — late June. It sat in cash for
half the first year, built its initial book from a truncated window, and was
then compared against a benchmark measured fully invested from day one. The
arithmetic was right and the experiment was not.

WHY NOTHING CAUGHT IT. Every fixture arrives with enough history, or drives the
normalised engine directly. None of them proves that an ARBITRARY DATED database
rehearsal receives a pre-start window — which is a property of the loader, not
of the strategy, and the loader is the one part the golden fixture cannot reach.

These tests are about that property. They use a synthetic corpus rather than a
real one so the session count is exact and the assertions can be about counts
rather than about market behaviour.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import pathlib

import pytest

from app import wealth_core_api as api
from app.wealth_core_chain import STATEFUL_MODEL, rehearse_chain
from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.signals import (LONG_LOOKBACK_SESSIONS,
                                                       REQUIRED_CLOSES)


REPO = pathlib.Path(os.environ.get(
    "BT_ENGINE_REPO_ROOT", pathlib.Path(__file__).resolve().parents[2]))


# ── the constants line up with the signal ────────────────────────────────────

def test_the_warmup_length_is_derived_from_the_signal_not_guessed():
    """A hardcoded 126 would silently stop matching if the lookback changed."""
    assert api.WARMUP_SESSIONS == REQUIRED_CLOSES - 1 == LONG_LOOKBACK_SESSIONS


def test_the_calendar_window_can_actually_contain_that_many_sessions():
    """~252 sessions a year, so 126 sessions is ~183 calendar days. A window
    shorter than that could never find them and the run would always refuse."""
    assert api.WARMUP_CALENDAR_DAYS >= api.WARMUP_SESSIONS * 365 / 252 * 1.2


# ── the split ────────────────────────────────────────────────────────────────

def _sessions(n, start=dt.date(2020, 1, 1)):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(n)]


class TestTheSplit:

    def test_measured_sessions_start_exactly_at_the_requested_date(self):
        all_s = _sessions(400)
        warm, measured = api._split_warmup(all_s, "2020-06-01")
        assert measured[0] == "2020-06-01"
        assert all(s >= "2020-06-01" for s in measured)
        assert all(s < "2020-06-01" for s in warm)

    def test_the_warmup_is_trimmed_to_what_the_signal_needs(self):
        """Not to whatever the calendar query happened to return. Otherwise the
        result depends on WARMUP_CALENDAR_DAYS, which is a lookup hint rather
        than part of the strategy.

        Both queries reach back further than the signal needs and differ only in
        HOW MUCH further; the warm-up they yield must be identical.
        """
        wide, _ = api._split_warmup(_sessions(400, dt.date(2019, 1, 1)),
                                    "2020-01-01")
        narrow, _ = api._split_warmup(_sessions(300, dt.date(2019, 4, 1)),
                                      "2020-01-01")
        assert len(wide) == len(narrow) == api.WARMUP_SESSIONS
        assert wide == narrow, "a wider query must not change the warm-up"

    def test_the_warmup_is_the_sessions_IMMEDIATELY_before_the_start(self):
        """Contiguity matters: the signal reads a trailing window, so a gap
        would compute momentum across a hole."""
        warm, measured = api._split_warmup(_sessions(400), "2020-06-01")
        assert warm[-1] == "2020-05-31"
        assert measured[0] == "2020-06-01"

    def test_too_little_history_yields_a_short_warmup_for_the_caller_to_refuse(self):
        warm, measured = api._split_warmup(_sessions(400, dt.date(2020, 5, 1)),
                                           "2020-06-01")
        assert len(warm) < api.WARMUP_SESSIONS
        assert measured

    def test_action_cutoff_requires_one_session_before_the_full_warmup(self):
        warm = _sessions(api.WARMUP_SESSIONS)
        assert api._exclusive_prior_session(warm, warm) is None

        prior = "2019-12-31"
        assert api._exclusive_prior_session([prior, *warm], warm) == prior


# ── the behaviour: a warmed feed can rank on session one ─────────────────────

def _corpus(n_sessions: int, n_secs: int = 30):
    """A synthetic corpus that clears every eligibility threshold.

    Deliberately explicit about WHY each field is what it is, because a fixture
    that fails eligibility for an unrelated reason would make the warm-up
    assertions below pass or fail for the wrong cause:

        category    "Common Stock" and neither Warrant nor Preferred (§1)
        permaticker strict issuer identity refuses a security without one
        price       >= min_unadjusted_price (1.0)
        px * volume >= min_adv20_dollars (20M) and min_signal_dollar_volume (5M)
        the wobble  formation volatility must be non-zero and finite, or the
                    security is refused as INVALID_FORMATION_VOLATILITY
    """
    sessions = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).isoformat()
                for i in range(n_sessions)]
    meta = {f"S{k}": SecurityMeta(security_id=f"S{k}", ticker=f"T{k}",
                                  category="Domestic Common Stock",
                                  permaticker=f"P{k}")
            for k in range(n_secs)}
    bars = {}
    for i, s in enumerate(sessions):
        rows = []
        for k in range(n_secs):
            drift = 1.0 + 0.001 * i * (1 + k / 100.0)
            wobble = 1.0 + 0.01 * math.sin((i + k) * 0.7)
            px = 100.0 * drift * wobble
            rows.append(VendorBar(security_id=f"S{k}", ticker=f"T{k}",
                                  session=s, raw_close=px, raw_open=px,
                                  volume=1_000_000.0))
        bars[s] = rows
    return sessions, bars, meta


def _n_eligible(ns) -> int:
    """Counted off `eligibility`, the verdict itself — `bars` are DailyBars and
    carry no verdict at all."""
    return sum(1 for r in ns.eligibility.values() if r.eligible)


class TestAWarmedFeedRanksImmediately:
    """The property the whole fix exists for, stated as a count rather than a
    return: on the FIRST measured session the universe must already be
    rankable."""

    def _scored(self, warmup, measured, bars, meta):
        feed = Feed(meta, EligibilityConfig())
        if warmup:
            feed.warmup(list(warmup), bars)
        return feed.advance(measured[0], bars[measured[0]])

    def test_without_warmup_nothing_is_eligible_on_session_one(self):
        """The defect, reproduced. This is what the 2021 run actually did."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 40)
        measured = sessions[REQUIRED_CLOSES:]
        ns = self._scored((), measured, bars, meta)
        assert _n_eligible(ns) == 0

    def test_with_warmup_the_universe_is_rankable_on_session_one(self):
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 40)
        warmup = sessions[:REQUIRED_CLOSES - 1]
        measured = sessions[REQUIRED_CLOSES - 1:]
        ns = self._scored(warmup, measured, bars, meta)
        assert _n_eligible(ns) == 30, (
            "a warmed feed must be able to rank on the first measured session")

    def test_one_session_short_is_still_not_enough(self):
        """The boundary, checked rather than assumed — REQUIRED_CLOSES counts
        the current session too, so the warm-up is one less."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 40)
        warmup = sessions[:REQUIRED_CLOSES - 2]
        measured = sessions[REQUIRED_CLOSES - 2:]
        ns = self._scored(warmup, measured, bars, meta)
        assert _n_eligible(ns) == 0


# ── the production path, judged on its OUTPUT ────────────────────────────────

def _rehearse(warmup, measured, bars, meta):
    return rehearse_chain(
        sessions=list(measured), bars_by_session=bars, meta=meta,
        starting_cash=1_000_000.0, warmup_sessions=list(warmup),
        eligibility_cfg=EligibilityConfig(),
        config={"execution_model": STATEFUL_MODEL})


def _opens(session_rehearsal) -> int:
    return sum(1 for i in session_rehearsal.intents
               if i["operation"] == "OPEN_SLOT_POSITION")


class TestTheRehearsalBuildsABookOnSessionOne:
    """THE acceptance criterion, on the path production actually runs.

    The Feed-level tests above prove that a warmed feed CAN rank; they say
    nothing about whether `rehearse_chain` warms one. That gap is not
    hypothetical — with both `feed.warmup` calls removed, every other test in
    this file still passed, because the chain and the bulk replay were then
    wrong in the SAME way and their hashes still matched. Equivalence is a
    consistency check, not a correctness one.

    So these assert the observable the reviewer named: intents opened and book
    size on the FIRST measured session.
    """

    def test_the_first_measured_session_fills_the_book(self):
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30, n_secs=40)
        r = _rehearse(sessions[:REQUIRED_CLOSES - 1],
                      sessions[REQUIRED_CLOSES - 1:], bars, meta)
        first = r.sessions[0]
        assert _opens(first) == WealthCoreConfig().n_slots, (
            f"session one opened {_opens(first)} slot(s); a warmed run has a "
            f"full ranked universe on day one and should construct the whole "
            f"book immediately")

    def test_the_book_is_full_within_the_first_few_sessions(self):
        """Orders are placed on the signal date and fill at the NEXT open, so
        `held` is zero on session one by design — but it must be full almost
        at once, not in six months."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30, n_secs=40)
        r = _rehearse(sessions[:REQUIRED_CLOSES - 1],
                      sessions[REQUIRED_CLOSES - 1:], bars, meta)
        held = [b["held"] for b in r.book_size_by_session[:5]]
        assert max(held) == WealthCoreConfig().n_slots, (
            f"book sizes over the first five sessions were {held}")

    def test_WITHOUT_the_warmup_the_book_stays_empty_for_months(self):
        """The defect, reproduced through the production entry point. This is
        what the January-July 2021 rehearsal actually did, and it is the
        assertion that fails if either `feed.warmup` call is deleted."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30, n_secs=40)
        r = _rehearse((), sessions[REQUIRED_CLOSES - 1:], bars, meta)
        assert _opens(r.sessions[0]) == 0
        assert [b["held"] for b in r.book_size_by_session[:5]] == [0] * 5


# ── the warm-up must not leak into the RESULT ────────────────────────────────

class TestWarmupChangesNothingItShouldNot:

    def _rehearse(self, warmup, measured, bars, meta):
        return _rehearse(warmup, measured, bars, meta)

    def test_the_equity_curve_covers_only_the_measured_sessions(self):
        """No warm-up session may appear as an equity point, or the measured
        period silently starts earlier than requested."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30)
        warmup, measured = sessions[:REQUIRED_CLOSES - 1], sessions[REQUIRED_CLOSES - 1:]
        r = self._rehearse(warmup, measured, bars, meta)

        seen = [s.session for s in r.sessions]
        assert seen == list(measured)
        assert not set(seen) & set(warmup)

        perf = r.performance or r.performance_excluding_blocked
        assert perf["start_date"] == measured[0]
        assert perf["session_count"] == len(measured)

    def test_the_chain_still_reproduces_the_bulk_replay(self):
        """Both paths must warm identically. Warming one and not the other is a
        divergence with nothing to do with the strategy — and it would look
        exactly like a real one."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30)
        r = self._rehearse(sessions[:REQUIRED_CLOSES - 1],
                           sessions[REQUIRED_CLOSES - 1:], bars, meta)
        assert r.equivalence["state_hash_matches"] is True
        assert r.equivalence["ledger_hash_matches"] is True

    def test_warming_produces_no_trades_of_its_own(self):
        """A warmed run and an unwarmed one differ in WHEN they can trade, never
        in trades attributed to the warm-up window itself."""
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 30)
        r = self._rehearse(sessions[:REQUIRED_CLOSES - 1],
                           sessions[REQUIRED_CLOSES - 1:], bars, meta)
        for s in r.sessions:
            assert s.session not in sessions[:REQUIRED_CLOSES - 1]


# ── the refusal ──────────────────────────────────────────────────────────────

def test_the_refusal_names_the_defect_rather_than_just_the_shortfall():
    """A short corpus must not silently produce the delayed-start run. The
    message has to say WHY the numbers would be wrong, because a bare
    'insufficient history' reads as a tuning problem."""
    src = (api.__file__ and open(api.__file__).read())
    body = src[src.index("async def _load_corpus"):src.index("def _execute(")]
    assert "len(warmup_sessions) < WARMUP_SESSIONS" in body
    assert "NOT be a backtest" in body
    assert "fully invested from day" in body


# ── the seam: the loader's warm-up must reach every mode ─────────────────────

class TestTheWarmupSurvivesTheHandoff:
    """`_load_corpus` computes the warm-up and `_execute` dispatches it. Between
    them is a plain dict key, and a mode that forgets to forward it would run
    the delayed-start book while every other check stayed green — the warm-up is
    invisible in the result by design.

    `_execute` is pure given a corpus, so the seam is testable with no database.
    """

    def _corpus_dict(self):
        sessions, bars, meta = _corpus(REQUIRED_CLOSES + 5, n_secs=5)
        return {"sessions": sessions[REQUIRED_CLOSES - 1:],
                "bars_by_session": bars, "meta": meta,
                "terminal_events": (),
                "warmup_sessions": sessions[:REQUIRED_CLOSES - 1],
                "benchmark_closes": None}

    def _captured(self, monkeypatch, name, req):
        seen = {}

        def spy(**kw):
            seen.update(kw)
            raise _Stop()

        monkeypatch.setattr(api, name, spy)
        corpus = self._corpus_dict()
        with pytest.raises(_Stop):
            api._execute(req, corpus)
        return seen, corpus

    def test_chain_rehearsal_forwards_it(self, monkeypatch):
        seen, corpus = self._captured(
            monkeypatch, "rehearse_chain",
            api.WealthCoreJobRequest(mode="chain_rehearsal",
                                     start_date="2020-05-06",
                                     end_date="2020-05-10"))
        assert seen["warmup_sessions"] == corpus["warmup_sessions"]

    def test_baseline_replay_forwards_it(self, monkeypatch):
        seen, corpus = self._captured(
            monkeypatch, "baseline_replay",
            api.WealthCoreJobRequest(mode="baseline_replay",
                                     start_date="2020-05-06",
                                     end_date="2020-05-10",
                                     expected_hashes={},
                                     expected_data_version="generation-7"))
        assert seen["warmup_sessions"] == corpus["warmup_sessions"]

    def test_experiment_forwards_it(self, monkeypatch):
        seen, corpus = self._captured(
            monkeypatch, "experiment",
            api.WealthCoreJobRequest(mode="experiment",
                                     start_date="2020-05-06",
                                     end_date="2020-05-10",
                                     baseline_hashes={},
                                     change={"n_slots": 20}))
        assert seen["warmup_sessions"] == corpus["warmup_sessions"]


class _Stop(Exception):
    """Cut the spy short: the test is about the ARGUMENT, and letting the real
    run proceed would make it a slow duplicate of the tests above."""


# ── the widened window changed what the ACTION index means ───────────────────

class TestActionsAreIndexedAgainstTheRightWindow:
    """`snap_to_session` maps an action to the first session ON OR AFTER its
    date, WITHIN the index it is handed — so the index chooses where a
    warm-up-window action lands, and the right choice differs by action type.

    This is a defect the warm-up fix INTRODUCED and had to close in the same
    change: widening the corpus query to `warmup_from` brought pre-start action
    rows into scope for the first time, and the original measured-only index
    would have snapped every one of them onto day one.
    """

    @staticmethod
    def _replay():
        """Loaded from its CHECKOUT path. In the image it is COPYed to
        `app/live/wealth_core_replay.py`; in the repo it lives under the
        backtester, and importing it by file keeps this test independent of
        whichever layout is present."""
        if os.environ.get("BT_ENGINE_IN_IMAGE") == "1":
            from app.live import wealth_core_replay
            return wealth_core_replay

        import importlib.util
        import sys
        if "_wcr_probe" in sys.modules:
            return sys.modules["_wcr_probe"]
        src = (REPO / "services" / "backtester" / "app" /
               "wealth_core_replay.py")
        spec = importlib.util.spec_from_file_location("_wcr_probe", src)
        mod = importlib.util.module_from_spec(spec)
        # Registered BEFORE exec: its dataclasses resolve string annotations
        # through `sys.modules[cls.__module__]`, which is None for a module that
        # is only half-imported.
        sys.modules["_wcr_probe"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_a_split_during_the_warmup_lands_on_its_own_session(self):
        """Against a measured-only index it would land on the first measured
        session instead — a 2:1 discontinuity injected into the signal series at
        precisely the point the momentum window reads."""
        wcr = self._replay()
        warm = ["2020-11-02", "2020-11-03"]
        measured = ["2021-01-04", "2021-01-05"]
        rows = [{"ticker": "AAA", "date": "2020-11-03", "action": "split",
                 "value": 2.0}]

        full = wcr.split_ratios_from_actions(rows, wcr.sessions_index(warm + measured))
        assert full == {("AAA", "2020-11-03"): 2.0}

        measured_only = wcr.split_ratios_from_actions(
            rows, wcr.sessions_index(measured))
        assert measured_only == {("AAA", "2021-01-04"): 2.0}, (
            "this is the wrong answer the full index exists to avoid")

    def test_a_dividend_during_the_warmup_is_not_paid_on_day_one(self):
        wcr = self._replay()
        warm, measured = ["2020-11-02"], ["2021-01-04"]
        rows = [{"ticker": "AAA", "date": "2020-11-02", "action": "dividend",
                 "value": 1.5}]
        full = wcr.dividends_from_actions(rows, wcr.sessions_index(warm + measured))
        assert ("AAA", "2021-01-04") not in full
        assert full == {("AAA", "2020-11-02"): 1.5}

    @pytest.mark.parametrize(("raw_date", "expected"), [
        ("2022-03-06", ["SUNDAY"]),       # Sunday -> Monday
        ("2022-04-15", ["GOOD_FRIDAY"]), # exchange holiday -> Monday
    ])
    def test_effective_session_filter_keeps_non_session_day_one_actions(
            self, raw_date, expected):
        wcr = self._replay()
        if raw_date.startswith("2022-03"):
            sessions = wcr.sessions_index([
                "2022-03-04", "2022-03-07", "2022-03-08"])
            ticker = "SUNDAY"
        else:
            sessions = wcr.sessions_index([
                "2022-04-14", "2022-04-18", "2022-04-19"])
            ticker = "GOOD_FRIDAY"
        measured = sessions[1:]
        rows = [{"ticker": ticker, "date": raw_date,
                 "action": "delisted", "value": None}]
        selected = wcr.actions_effective_in_sessions(
            rows, sessions, measured)
        assert [row["ticker"] for row in selected] == expected

    def test_effective_session_filter_excludes_both_sides_of_the_window(self):
        wcr = self._replay()
        sessions = wcr.sessions_index([
            "2022-03-04", "2022-03-07", "2022-03-08"])
        measured = sessions[1:]
        rows = [
            {"ticker": "WARMUP", "date": "2022-03-04"},
            {"ticker": "MEASURED", "date": "2022-03-06"},
            {"ticker": "AFTER", "date": "2022-03-09"},
        ]
        selected = wcr.actions_effective_in_sessions(
            rows, sessions, measured)
        assert [row["ticker"] for row in selected] == ["MEASURED"]

    def test_prior_or_older_actions_drop_but_weekend_actions_map_forward(
            self):
        """The calendar net is wider than the retained feature history.

        Mapping its discarded action rows against the trimmed index would put
        both OLD events on 2020-11-02, inventing causal inputs on the boundary.
        The canonical filter must remove them before either mapper sees them.
        """
        wcr = self._replay()
        prior = "2020-10-30"  # Friday, exclusive cutoff
        warm = ["2020-11-02", "2020-11-03"]  # first retained is Monday
        measured = ["2021-01-04"]
        rows = [
            {"ticker": "OLD_SPLIT", "date": "2020-10-30",
             "action": "split", "value": 2.0},
            {"ticker": "OLD_DIV", "date": "2020-10-29",
             "action": "dividend", "value": 1.0},
            {"ticker": "WEEKEND_SPLIT", "date": "2020-11-01",
             "action": "split", "value": 3.0},
            {"ticker": "WEEKEND_DIV", "date": "2020-11-01",
             "action": "dividend", "value": 1.5},
        ]
        causal = wcr.actions_after_session(rows, prior)
        index = wcr.sessions_index(warm + measured)

        assert wcr.split_ratios_from_actions(causal, index) == {
            ("WEEKEND_SPLIT", "2020-11-02"): 3.0}
        assert wcr.dividends_from_actions(causal, index) == {
            ("WEEKEND_DIV", "2020-11-02"): 1.5}

        src = open(api.__file__).read()
        body = src[src.index("async def _load_corpus"):src.index("def _execute(")]
        assert "source_action_rows = load_actions(conn, warmup_from, end)" in body
        assert "action_rows = actions_after_session(\n" \
               "                source_action_rows, " \
               "actions_exclusive_prior_session)" in body
        assert body.index("action_rows = actions_after_session(") < body.index(
            "split_ratios_from_actions(action_rows, full_idx)")
        assert body.index("action_rows = actions_after_session(") < body.index(
            "dividends_from_actions(action_rows, full_idx)")

    def test_producer_and_baseline_select_terminals_by_EFFECTIVE_session(self):
        """Both consumers map on the complete causal calendar before filtering.

        This preserves Sunday/holiday rows that become effective on measured
        day one without shifting warm-up events onto that session.
        """
        src = open(api.__file__).read()
        body = src[src.index("async def _load_corpus"):src.index("def _execute(")]
        assert "actions_exclusive_prior_session = _exclusive_prior_session(" \
               in body
        assert "actions_first_retained_session = warmup_sessions[0]" in body
        assert "measured_action_rows = actions_effective_in_sessions(\n" \
               "                action_rows, full_idx, sessions)" in body
        assert "terminal_events_from_actions(\n" \
               "                    measured_action_rows, full_idx," in body
        assert "split_ratios_from_actions(action_rows, full_idx)" in body
        assert "dividends_from_actions(action_rows, full_idx)" in body
