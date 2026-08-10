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
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.core import book_artifact as B  # noqa: E402

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
    def __init__(self, **kw):
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

    def test_still_open_holdings_are_included(self):
        r = _Run(ledger=_Ledger([]),
                 state=_State(holdings={"P:C": {"ticker": "CCC"}}))
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

    def write(self, tmp_path, obj):
        p = tmp_path / "book.json"
        p.write_text(json.dumps(obj))
        return p

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
