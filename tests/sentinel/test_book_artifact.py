"""The run emits what it held. No human transcription in the evidentiary chain.

The rejection audit's two strongest materiality checks need to know which
securities the run held and which it was carrying a terminal event for. Those
arrived as a comma-separated list on a command line, which puts a person between
the machine that knows the answer and the verdict that depends on it — and a
mistyped ticker there does not produce an error, it produces a CLEAN
certification.

TWO PROPERTIES ARE ASSERTED HERE, and they pull in opposite directions on
purpose:

```text
the artifact OVER-INCLUDES     a ticker wrongly present makes an irrelevant
                               rejection MATERIAL: the interval refuses, a human
                               looks, and says so. Costly, visible, safe.
                               A ticker wrongly ABSENT lets a rejection on a
                               held security be judged by the ADMISSION floors,
                               which do not govern an open position at all.
                               Free, invisible, wrong.

the LOADER refuses a partial    `.get("pending_terminal", [])` turns a file that
file                            names only `held` into the claim "nothing was
                                pending" — silently, on the field most likely to
                                be forgotten, and contradicting the
                                half-supplied-is-UNKNOWN rule the audit enforces
                                everywhere else.
```
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
#: The REPOSITORY under inspection. Inside the certified image ROOT is /work
#: (tests, an importable backtester copy, tools) while the repo SOURCES live at
#: /work/repo — so a repo file read through ROOT resolves in a checkout and
#: raises FileNotFoundError in the image.
REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from stock_strategy_shared import book_artifact as B  # noqa: E402

W = {"start": "2021-01-04", "end": "2023-12-29"}


class _Event:
    def __init__(self, ticker, security_id="P:X"):
        self.ticker = ticker
        self.security_id = security_id


class _Ledger:
    def __init__(self, events, receivables=()):
        self.events = list(events)
        self.receivables = list(receivables)


class _State:
    """A stand-in — and a WARNING. The previous version defined `.holdings`,
    an attribute the real `PortfolioState` does not have, which made every
    test here pass while `held_tickers` read nothing from the state at all.

    `TestAgainstTheREALPortfolioState` below is the answer to that: a fake can
    only prove the code agrees with the fake."""

    def __init__(self, **kw):
        self.episodes = kw.get("episodes", {})
        self.holdings = kw.get("holdings", {})
        self.terminal_pending_sessions = kw.get("terminal_pending_sessions", {})
        self.terminal_pending_terms = kw.get("terminal_pending_terms", {})
        self.terminal_carry_audit = kw.get("terminal_carry_audit", {})


class _Run:
    def __init__(self, **kw):
        self.ledger = kw.get("ledger")
        self.state = kw.get("state")
        self.terminal_results = kw.get("terminal_results", [])
        self.session_facts = kw.get("session_facts", [])


# ── 1. every source the run can name a security from ─────────────────────────

class TestTheUnionReachesEverySource:

    def test_the_LEDGER_is_the_primary_source(self):
        r = _Run(ledger=_Ledger([_Event("AAA"), _Event("BBB")]))
        assert B.held_tickers(r) == {"AAA", "BBB"}

    def test_it_is_the_WHOLE_interval_not_an_end_of_run_snapshot(self):
        """A name bought and sold in 2021 is not in the final state and was
        absolutely held. `sessions` is elided above 400 sessions, so a
        three-year run would answer this from a truncated record — the ledger
        is append-only and always retained, which is why it leads."""
        r = _Run(ledger=_Ledger([_Event("SOLD")]), state=_State(holdings={}))
        assert "SOLD" in B.held_tickers(r)

    def test_still_open_EPISODES_are_included(self):
        r = _Run(ledger=_Ledger([]),
                 state=_State(episodes={1: {"ticker": "CCC"}}))
        assert "CCC" in B.held_tickers(r)

    def test_RECEIVABLES_count_too(self):
        """An accrued dividend names a security the book was owed money by."""
        r = _Run(ledger=_Ledger([], [{"security_id": "P:D", "ticker": "DDD"}]))
        assert "DDD" in B.held_tickers(r)

    def test_session_facts_are_swept_as_well(self):
        r = _Run(ledger=_Ledger([]),
                 session_facts=[{"fills": [{"ticker": "EEE"}]}])
        assert "EEE" in B.held_tickers(r)

    def test_terminal_RESULTS_are_pending_terminal(self):
        r = _Run(terminal_results=[{"ticker": "TTT", "applied": True}])
        assert B.pending_terminal_tickers(r) == {"TTT"}

    def test_a_RESOLVED_terminal_event_still_counts(self):
        """It was pending before it resolved, and the grace window is exactly
        when a missing print changes the settlement price."""
        r = _Run(terminal_results=[{"ticker": "GONE", "applied": True,
                                    "settled": True}])
        assert "GONE" in B.pending_terminal_tickers(r)

    def test_the_CARRY_AUDIT_is_swept(self):
        r = _Run(state=_State(terminal_carry_audit={
            "P:H": {"ticker": "HHH", "carry_price": 10.0}}))
        assert "HHH" in B.pending_terminal_tickers(r)

    def test_pending_sessions_contribute_their_KEYS(self):
        """That dict is keyed on security id with an int value, so a structural
        ticker sweep finds nothing in it. An empty field here would
        misrepresent the run as having carried nothing."""
        r = _Run(state=_State(terminal_pending_sessions={"P:ZZZ": 3}))
        assert "P:ZZZ" in B.pending_terminal_tickers(r)

    def test_tickers_are_UPPERCASED_to_match_the_audit(self):
        r = _Run(ledger=_Ledger([_Event("aaa")]))
        assert B.held_tickers(r) == {"AAA"}

    def test_a_NESTED_ticker_is_still_found(self):
        r = _Run(terminal_results=[{"detail": {"successor": {"ticker": "NEW"}}}])
        assert "NEW" in B.pending_terminal_tickers(r)


class TestTheBiasIsTowardINCLUDING:

    def test_an_empty_run_produces_BOTH_keys(self):
        """An empty list is a positive claim — 'the run held nothing' — and
        only this function is entitled to make it."""
        rec = B.from_run_result(_Run(), **W)
        assert rec["held"] == [] and rec["pending_terminal"] == []

    def test_an_unrecognised_shape_does_not_CRASH_the_artifact(self):
        """A run object that grew a field this walk does not understand must
        not produce an exception — that would mean no artifact at all, and the
        audit would then be given nothing, which is the worst outcome."""
        class Weird:
            def to_dict(self):
                raise RuntimeError("boom")
        r = _Run(terminal_results=[Weird()], ledger=_Ledger([_Event("AAA")]))
        assert B.from_run_result(r, **W)["held"] == ["AAA"]

    def test_deep_nesting_terminates(self):
        deep = cur = {}
        for _ in range(50):
            cur["next"] = {}
            cur = cur["next"]
        cur["ticker"] = "TOODEEP"
        B.from_run_result(_Run(terminal_results=[deep]), **W)   # must not hang

    def test_the_note_explains_the_asymmetry(self):
        assert "over-inclusive" in B.from_run_result(_Run(), **W)["note"]


# ── 2. the loader refuses to invent the missing half ─────────────────────────

class TestTheLoaderIsFailClosed:

    def write(self, tmp_path, obj, *, schema=B.SCHEMA):
        """The schema is supplied by default so these tests exercise the KEY
        rules; `test_a_book_with_NO_schema_is_refused` covers the other gate."""
        p = tmp_path / "book.json"
        p.write_text(json.dumps({"schema": schema, **obj}))
        return p

    def test_a_book_with_NO_schema_is_refused(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({"held": [], "pending_terminal": []}))
        with pytest.raises(ValueError, match="schema"):
            B.load(p)

    def test_a_complete_book_loads(self, tmp_path):
        p = self.write(tmp_path, {"held": ["aaa"], "pending_terminal": ["bbb"]})
        assert B.load(p) == (["AAA"], ["BBB"])

    def test_THE_FALSIFIER_a_book_with_only_held_is_REFUSED(self, tmp_path):
        """The defect: `.get("pending_terminal", [])` made this file assert
        that nothing was pending terminal settlement."""
        p = self.write(tmp_path, {"held": ["AAA"]})
        with pytest.raises(ValueError, match="pending_terminal"):
            B.load(p)

    def test_a_book_with_only_pending_is_REFUSED(self, tmp_path):
        p = self.write(tmp_path, {"pending_terminal": ["AAA"]})
        with pytest.raises(ValueError, match="held"):
            B.load(p)

    def test_an_EXPLICIT_empty_list_is_accepted(self, tmp_path):
        """Absent and empty are different statements, which is the whole
        point. An emitted empty book is the run saying it held nothing."""
        p = self.write(tmp_path, {"held": [], "pending_terminal": []})
        assert B.load(p) == ([], [])

    def test_a_NON_LIST_value_is_refused(self, tmp_path):
        p = self.write(tmp_path, {"held": "AAA", "pending_terminal": []})
        with pytest.raises(ValueError, match="not a list"):
            B.load(p)

    def test_write_then_load_ROUND_TRIPS(self, tmp_path):
        r = _Run(ledger=_Ledger([_Event("AAA")]),
                 terminal_results=[{"ticker": "TTT"}])
        B.write(r, tmp_path / "b.json", **W)
        assert B.load(tmp_path / "b.json") == (["AAA"], ["TTT"])


# ── 3. and the audit consumes it end to end ──────────────────────────────────

class TestTheAuditAcceptsTheEmittedArtifact:

    def test_the_emitted_book_makes_holdings_KNOWN(self, tmp_path):
        from sentinel.feed import rejection_audit as RA

        r = _Run(ledger=_Ledger([_Event("AAA")]))
        B.write(r, tmp_path / "b.json", **W)
        held, pending = B.load(tmp_path / "b.json")

        class _NoRows:
            def cursor(self):
                return self

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a, **kw):
                self._rows = []

            def fetchall(self):
                return []

        a = RA.audit(_NoRows(), start=W["start"], end=W["end"],
                     held_tickers=held, pending_terminal_tickers=pending)
        assert a.holdings_known is True


# ── 4. the window must MATCH the audit it feeds ──────────────────────────────

class TestTheWindowIsCHECKED:
    """A well-formed book for the WRONG period is more dangerous than a
    malformed one, because nothing about it looks wrong. A 2022 book handed to a
    2021-2023 audit omits every name held only in 2021 or 2023, and a refused
    row on one of those is then judged by ADMISSION floors that do not govern an
    open position."""

    def write(self, tmp_path, **over):
        rec = B.from_run_result(_Run(ledger=_Ledger([_Event("AAA")])), **W)
        rec.update(over)
        p = tmp_path / "book.json"
        p.write_text(json.dumps(rec))
        return p

    def test_a_MATCHING_window_loads(self, tmp_path):
        p = self.write(tmp_path)
        assert B.load(p, start=W["start"], end=W["end"]) == (["AAA"], [])

    def test_THE_FALSIFIER_a_NARROWER_book_is_refused(self, tmp_path):
        p = self.write(tmp_path, window={"start": "2022-01-03",
                                         "end": "2022-12-30"})
        with pytest.raises(ValueError, match="2022-01-03"):
            B.load(p, start=W["start"], end=W["end"])

    def test_a_SHIFTED_window_is_refused(self, tmp_path):
        p = self.write(tmp_path, window={"start": W["start"],
                                         "end": "2023-12-28"})
        with pytest.raises(ValueError, match="Refused"):
            B.load(p, start=W["start"], end=W["end"])

    def test_a_MISSING_window_is_refused_when_one_is_required(self, tmp_path):
        p = self.write(tmp_path, window={})
        with pytest.raises(ValueError):
            B.load(p, start=W["start"], end=W["end"])

    def test_NO_window_check_when_the_caller_supplies_none(self, tmp_path):
        """Reading an artifact for inspection is a different act from feeding
        it to a gate."""
        p = self.write(tmp_path, window={"start": "1999-01-01", "end": "x"})
        assert B.load(p) == (["AAA"], [])

    def test_a_WRONG_SCHEMA_is_refused(self, tmp_path):
        p = self.write(tmp_path, schema="something.else/9")
        with pytest.raises(ValueError, match="schema"):
            B.load(p)

    def test_the_emitted_artifact_declares_the_CURRENT_schema(self, tmp_path):
        rec = B.from_run_result(_Run(), **W)
        assert rec["schema"] == B.SCHEMA


# ── 5. and PRODUCTION actually calls it ──────────────────────────────────────

class TestTheSharedBookArtifactBoundary:
    def test_the_canonical_module_is_SHARED_not_sentinel_only(self):
        """bt-engine produces it and Sentinel consumes it, and neither may
        import the other. One implementation, reachable from both."""
        from stock_strategy_shared import book_artifact as shared
        assert B is shared
        assert not (REPO / "sentinel" / "core" / "book_artifact.py").exists()

    def test_wealth_core_source_tree_is_UNTOUCHED_by_this(self):
        """It reads a RunResult, so `wealth_core/` looks like the tidy home. It
        is not: that tree is hashed as `wealth_core_source` in every
        certification record and has been byte-identical across three reviews.
        A reporting helper does not get to spend that."""
        assert not (REPO / "shared" / "stock_strategy_shared" / "wealth_core"
                    / "book_artifact.py").exists()


# ── 6. against the REAL classes, because the fake hid a real bug ─────────────

class TestAgainstTheREALPortfolioState:
    """`held_tickers` read `state.holdings`. `PortfolioState` has no such
    attribute — its live holdings are `state.episodes`, keyed by slot — and the
    local fake defined `.holdings`, so every test above passed while the state
    contributed nothing at all.

    A relabelling makes this worse than an ordinary missing source:
    `apply_ticker_changes` posts NO ledger event by design, so the ledger cannot
    recover a new symbol. The security below is bought as OLD and renamed to
    NEW, and the old code returned {OLD}.
    """

    def run(self, *, ledger_ticker="OLD", episode_ticker="NEW"):
        from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
        from stock_strategy_shared.wealth_core.state import (HoldingEpisode,
                                                             PortfolioState)

        led = Ledger()
        led.post(session="2021-06-01", event_type=EventType.BUY,
                 cash_before=1000.0, cash_delta=-100.0, security_id="P:X",
                 ticker=ledger_ticker)
        st = PortfolioState.fresh(1000.0, 25)
        st.episodes[1] = HoldingEpisode(
            security_id="P:X", ticker=episode_ticker, issuer_id="I", slot_id=1,
            signal_date="2021-06-01", entry_date="2021-06-02",
            entry_raw_open=10.0, entry_split_adjusted_price=10.0,
            initial_shares=100.0, current_shares=100.0)

        class R:
            def __init__(self):
                self.ledger, self.state = led, st
                self.terminal_results, self.session_facts = [], []
        return R()

    def test_the_real_state_has_NO_holdings_attribute(self):
        """Pinned so the fake can never drift back into inventing one."""
        from stock_strategy_shared.wealth_core.state import PortfolioState
        assert not hasattr(PortfolioState.fresh(1000.0, 25), "holdings")

    def test_THE_FALSIFIER_a_RELABELLED_holding_is_found(self):
        got = B.held_tickers(self.run())
        assert "NEW" in got, (
            "the current episode label is missing — and a relabelling posts no "
            "ledger event, so nothing else in the run can supply it")
        assert "OLD" in got, "the ledger's original label was dropped"

    def test_the_episode_label_survives_from_run_result(self):
        rec = B.from_run_result(self.run(), **W)
        assert {"NEW", "OLD"} <= set(rec["held"])

    def test_extra_held_carries_INTERMEDIATE_labels(self):
        """The end state holds only the LAST label and the ledger only the
        first, so a name renamed twice has a middle label neither can supply.
        `rehearse_chain` accumulates them per session and passes them here."""
        rec = B.from_run_result(self.run(), extra_held=["MIDDLE"], **W)
        assert {"OLD", "MIDDLE", "NEW"} <= set(rec["held"])
