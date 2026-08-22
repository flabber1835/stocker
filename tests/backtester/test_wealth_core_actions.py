"""SHARADAR/ACTIONS -> Wealth Core corporate actions.

WHAT CAN GO WRONG HERE, and why it needs its own file. The strategy is pinned
elsewhere; these are the MAPPING rules, and every one of their failure modes
produces a complete, plausible backtest of something that did not happen:

  * a split ratio applied upside down halves a position on a 2:1
  * an ex-date on a weekend silently never fires, leaving a terminated holding
    outstanding for the rest of the run
  * and the one that matters most — a delisting with no stated terms turned
    into a WRITE_OFF, which FABRICATES A TOTAL LOSS. In a strategy where every
    admission is 4% of equity, an invented zero permanently shrinks every
    position opened afterwards, and nothing raises.

That last rule is asserted three ways: on the mapping, on the resulting terms,
and end-to-end through `apply_terminal` against a real holding — because a test
that only checks the returned object's shape would pass on a `TerminalTerms`
that blocks in principle and applies in practice.
"""
from __future__ import annotations

import pytest

from app.wealth_core_replay import (  # noqa: E402
    ACTIONS_CAVEATS,
    CorporateActionsAmbiguous,
    CorporateActionsUnavailable,
    DERIVED_SPLIT_CAVEATS,
    DIVIDEND_ACTIONS,
    SPLIT_ACTIONS,
    TERMINAL_ACTIONS,
    TERMINAL_ACTION_SIDES,
    ActionSide,
    actions_effective_in_sessions,
    assert_actions_source_authority,
    dividends_from_actions,
    reconcile_split,
    sessions_index,
    snap_to_session,
    split_ratios_from_actions,
    terminal_events_from_actions,
    terminal_from_action,
)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    apply_terminal,
)

# Mon-Fri, then a gap over a weekend, then Mon-Tue.
SESSIONS = sessions_index(["2022-03-01", "2022-03-02", "2022-03-03",
                           "2022-03-04", "2022-03-07", "2022-03-08"])


def action(**over):
    # `mergerto` — the vendor's ACTUAL name. "merger" appears in no row of the
    # corpus; the code's old vocabulary listed seven names of which only
    # `delisted` existed. See docs/data-sources.md "Defect D".
    base = {"ticker": "AAA", "date": "2022-03-02", "action": "mergerto",
            "value": None, "contraticker": None, "contraname": None}
    base.update(over)
    return base


# ── ex-dates are CALENDAR dates ─────────────────────────────────────────────

class TestSnappingToARealSession:

    def test_a_session_date_maps_to_itself(self):
        assert snap_to_session("2022-03-03", SESSIONS) == "2022-03-03"

    def test_a_WEEKEND_ex_date_snaps_FORWARD_to_the_next_session(self):
        """MANDATORY. `run_sessions` REFUSES an event dated inside its window
        but on no session — deliberately, because such an event never fires and
        the position stays outstanding for the rest of the run. So the mapping
        has to resolve the calendar date here rather than hand the driver one
        it will reject."""
        assert snap_to_session("2022-03-05", SESSIONS) == "2022-03-07"  # Sat
        assert snap_to_session("2022-03-06", SESSIONS) == "2022-03-07"  # Sun

    def test_a_date_before_the_window_snaps_to_the_first_session(self):
        assert snap_to_session("2022-01-01", SESSIONS) == "2022-03-01"

    def test_a_date_PAST_the_window_is_not_this_run_s_event(self):
        """None, not the last session. Clamping backwards would fire a merger
        that has not happened yet."""
        assert snap_to_session("2022-04-01", SESSIONS) is None


class TestMeasuredActionSelectionUsesTheEffectiveSession:

    FULL = sessions_index([
        "2022-03-03", "2022-03-04", "2022-03-07", "2022-03-08"])
    MEASURED = sessions_index(["2022-03-07", "2022-03-08"])

    def test_a_SUNDAY_before_day_one_is_retained_for_MONDAY(self):
        row = action(date="2022-03-06")
        assert actions_effective_in_sessions(
            [row], self.FULL, self.MEASURED) == [row]

    def test_an_EXCHANGE_HOLIDAY_before_day_one_is_retained(self):
        # Friday 2022-04-15 was Good Friday. The supplied trading calendar, not
        # weekday arithmetic, establishes that the event becomes effective on
        # Monday's open.
        full = sessions_index(["2022-04-14", "2022-04-18", "2022-04-19"])
        measured = sessions_index(["2022-04-18", "2022-04-19"])
        row = action(date="2022-04-15")
        assert actions_effective_in_sessions([row], full, measured) == [row]

    def test_rows_effective_OUTSIDE_the_measured_window_are_excluded(self):
        rows = [
            action(ticker="WARMUP", date="2022-03-04"),
            action(ticker="MEASURED", date="2022-03-06"),
            action(ticker="AFTER", date="2022-03-09"),
        ]
        assert actions_effective_in_sessions(
            rows, self.FULL, self.MEASURED) == [rows[1]]


# ── splits ──────────────────────────────────────────────────────────────────

class TestAuthoritativeSplits:

    def test_a_two_for_one_is_a_share_multiplier_of_two(self):
        """NOT inverted. Sharadar states a forward 2:1 as value=2.0, which is
        already what `apply_splits` multiplies the share count by. The DERIVED
        ratio needed an inversion (the adjustment factor falls through a forward
        split), and carrying that habit over here would halve the position."""
        got = split_ratios_from_actions(
            [action(action="split", value=2.0, date="2022-03-03")], SESSIONS)
        assert got == {("AAA", "2022-03-03"): 2.0}

    def test_a_reverse_split_is_a_fraction(self):
        got = split_ratios_from_actions(
            [action(action="split", value=0.1, date="2022-03-03")], SESSIONS)
        assert got[("AAA", "2022-03-03")] == 0.1

    def test_a_weekend_split_lands_on_the_next_session(self):
        got = split_ratios_from_actions(
            [action(action="split", value=2.0, date="2022-03-05")], SESSIONS)
        assert got == {("AAA", "2022-03-07"): 2.0}

    @pytest.mark.parametrize("value", [None, 0.0, -1.0])
    def test_an_unusable_ratio_is_DROPPED_rather_than_defaulted(self, value):
        """A missing ratio must not become 1.0 in this map: 1.0 would read as
        'the vendor says there was no split', which is a statement the vendor
        did not make. Absent from the map means the derived cross-check still
        has something to say."""
        assert split_ratios_from_actions(
            [action(action="split", value=value)], SESSIONS) == {}

    def test_non_split_actions_are_ignored(self):
        rows = [action(action="dividend", value=0.5),
                action(action="mergerto", value=54.0)]
        assert split_ratios_from_actions(rows, SESSIONS) == {}

    def test_distinct_same_key_split_siblings_refuse_in_every_order(self):
        rows = [
            action(action="split", value=2.0, source_row_id="a" * 64),
            action(action="split", value=3.0, source_row_id="b" * 64),
        ]
        for ordered in (rows, list(reversed(rows))):
            with pytest.raises(CorporateActionsAmbiguous,
                               match="ambiguous split ACTIONS multiplicity"):
                split_ratios_from_actions(ordered, SESSIONS)

    def test_reciprocal_split_siblings_are_one_reverse_event(self):
        rows = [
            action(action="split", value=0.1, source_row_id="a" * 64),
            action(action="adrratiosplit", value=10.0,
                   source_row_id="b" * 64),
        ]
        expected = {("AAA", "2022-03-02"): 0.1}
        assert split_ratios_from_actions(rows, SESSIONS) == expected
        assert split_ratios_from_actions(list(reversed(rows)), SESSIONS) == expected

    def test_identical_greater_than_one_siblings_preserve_orientation_question(self):
        rows = [
            action(action="split", value=2.0, source_row_id="a" * 64),
            action(action="adrratiosplit", value=2.0,
                   source_row_id="b" * 64),
        ]
        assert split_ratios_from_actions(rows, SESSIONS) == {
            ("AAA", "2022-03-02"): 2.0,
        }


class TestAuthoritativeDividends:

    def test_distinct_same_key_rows_are_all_summed_order_independently(self):
        rows = [
            action(action="dividend", value=0.1, source_row_id="a" * 64),
            action(action="dividend", value=0.2, source_row_id="b" * 64),
            action(action="dividend", value=0.3, source_row_id="c" * 64),
        ]
        expected = {("AAA", "2022-03-02"): pytest.approx(0.6)}
        assert dividends_from_actions(rows, SESSIONS) == expected
        assert dividends_from_actions(list(reversed(rows)), SESSIONS) == expected


class TestActionsAuthority:

    class _Result:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class _Conn:
        def __init__(self, row):
            self.row = row

        def execute(self, *_args, **_kwargs):
            return TestActionsAuthority._Result(self.row)

    def test_complete_identity_and_coverage_are_both_required(self):
        ready = {"schema_version": "complete-source-row-v1", "status": "READY",
                 "date_min": "1900-01-01", "date_max": "2026-08-20",
                 "covers_start": True, "covers_end": True}
        assert assert_actions_source_authority(
            self._Conn(ready), "2000-01-01", "2026-08-20") is None

        for changed in (
                {"status": "NEEDS_REBUILD"},
                {"schema_version": "coarse-key-v0"},
                {"covers_start": False},
                {"covers_end": False}):
            with pytest.raises(CorporateActionsUnavailable,
                               match="complete-row authority"):
                assert_actions_source_authority(
                    self._Conn({**ready, **changed}),
                    "2000-01-01", "2026-08-20")


# ── reconciliation: price evidence orients ACTIONS; ambiguity is suppressed ─

class TestReconciliation:

    def test_agreement_is_agreement(self):
        assert reconcile_split(2.0, 2.0) == (2.0, "agreed")

    def test_a_greater_than_one_actions_value_without_orientation_is_refused(self):
        assert reconcile_split(1.0, 3.0) == (1.0, "unresolved")

    def test_a_nonpositive_actions_value_is_unresolved(self):
        assert reconcile_split(1.0, 0.0) == (1.0, "unresolved")

    def test_no_event_evidence_cannot_corroborate_a_near_one_forward_ratio(self):
        assert reconcile_split(None, 1.005) == (1.0, "unresolved")
        # The legacy replay spelling for no-event evidence remains equivalent.
        assert reconcile_split(1.0, 1.005) == (1.0, "unresolved")

    def test_on_DISAGREEMENT_neither_source_wins(self):
        ratio, outcome = reconcile_split(2.0, 3.0)
        assert ratio == 1.0 and outcome == "unresolved"

    def test_reverse_denominator_is_oriented_by_reciprocal_evidence(self):
        ratio, outcome = reconcile_split(1 / 30, 30.0)
        assert ratio == pytest.approx(1 / 30) and outcome == "reciprocal"

    def test_a_derived_split_ACTIONS_does_not_carry_is_flagged(self):
        """Applied — it is all we have — but never silently. Acting on a ratio
        the authoritative source does not carry is the behaviour this work
        removes, so it can be reported but not hidden."""
        assert reconcile_split(2.0, None) == (2.0, "disagreed")

    def test_a_quiet_bar_with_no_actions_row_is_not_a_disagreement(self):
        assert reconcile_split(1.0, None) == (1.0, "agreed")

    def test_rounding_noise_inside_tolerance_counts_as_agreement(self):
        ratio, outcome = reconcile_split(1.999, 2.0)
        assert ratio == 2.0 and outcome == "agreed"

    def test_overlapping_direct_and_reciprocal_bands_are_ambiguous(self):
        ratio, outcome = reconcile_split(1 / 1.005, 1.005)
        assert ratio == 1.0 and outcome == "unresolved"


# ── terminal actions, and the rule that must not be broken ──────────────────

class TestTerminalMapping:

    def test_a_DEAL_VALUE_never_becomes_a_PER_SHARE_PRICE(self):
        """DEFECT D2. `value` is the TRANSACTION VALUE IN MILLIONS.

        It was read as cash per share. TMHC acquired by Berkshire carries
        6768.8 — a $6.77bn deal, not a $6,768.80 share price. The vendor
        supplies NO holder-level consideration at any action type, so the only
        honest mapping is "terms unavailable".
        """
        t = terminal_from_action(action(action="acquisitionby", value=6768.8),
                                 "2022-03-02", security_id="P:1")
        assert t.cash_per_share is None, (
            "a deal size was written into cash_per_share — every holder would "
            "be paid the market capitalisation per share")
        complete, why = t.completeness(100)
        assert complete is False and why == "MISSING_CASH_PER_SHARE"

    def test_a_PUBLIC_buyer_does_not_create_a_stock_deal(self):
        """A buyer ticker names a counterparty, not holder consideration."""
        t = terminal_from_action(
            action(action="acquisitionby", value=6768.8, contraticker="BRK.B"),
            "2022-03-02", security_id="P:1", delivered_security_id="P:2",
            delivered_issuer_id="ISS_2")
        assert t.kind is TerminalKind.CASH_MERGER
        assert t.delivered_security_id is None
        assert t.delivered_ticker is None
        assert "counterparty_ticker=BRK.B" in t.reference
        complete, why = t.completeness(100)
        assert complete is False and why == "MISSING_CASH_PER_SHARE"

    def test_explicit_buyer_identity_still_does_not_prove_consideration(self):
        t = terminal_from_action(
            action(action="acquisitionby", value=None, contraticker="BRK.B"),
            "2022-03-02", security_id="P:1", delivered_security_id="P:2",
            delivered_issuer_id="ISS_2")
        assert t.delivered_security_id is None
        assert t.delivered_issuer_id is None
        assert t.delivered_ticker is None

    def test_the_NA_SENTINEL_is_ABSENCE_not_a_counterparty(self):
        """DEFECT D1, at the layer that failed.

        `contraticker` carries the literal string 'N/A' whenever the acquirer is
        PRIVATE — 19,216 of 19,216 delisted rows have a non-empty contraticker.
        `row.get("contraticker") or None` normalises None and '' and looks
        total, and passes 'N/A' through as truthy. Every terminal event then took
        the security-for-security branch and blocked on
        MISSING_DELIVERED_SECURITY: the permanent freeze that killed a
        three-year rehearsal, needing no missing action name at all.
        """
        t = terminal_from_action(
            action(action="acquisitionby", value=1170.2, contraticker="N/A",
                   contraname="AMERICAN INDUSTRIAL PARTNERS CORP"),
            "2022-03-02", security_id="P:1")
        assert t.kind is not TerminalKind.CONVERSION, (
            "'N/A' was treated as a delivered security")
        assert t.delivered_ticker is None
        assert t.completeness(100)[1] == "MISSING_CASH_PER_SHARE", (
            "the refusal must name the real gap — absent CASH terms for a "
            "private buyer — not a missing delivered security")

    def test_a_PRIVATE_buyer_is_still_NAMED_in_the_provenance(self):
        """`contraname` is populated even when the ticker is 'N/A', and it is the
        only counterparty identity those deals have. Provenance only — a name
        resolves to no security — but discarding it would throw away the single
        fact that distinguishes a buyout from an unexplained delisting."""
        t = terminal_from_action(
            action(action="acquisitionby", value=428.4, contraticker="N/A",
                   contraname="KNOX LANE LP"), "2022-03-02", security_id="P:1")
        assert "KNOX LANE LP" in t.reference
        assert "428.4" in t.reference, "the deal value belongs in the audit trail"

    def test_a_ZERO_deal_value_is_NOT_a_write_off(self):
        """THE REMOVED ROUTE, and its removal is the point of D2.

        `value == 0.0` used to mean "the vendor says holders received nothing".
        With `value` being a transaction SIZE, a zero is a statement about deal
        size and says nothing whatever about consideration — so that route wrote
        positions off at zero on evidence that never existed. A genuine
        stated-zero write-off needs a source that actually states consideration,
        and this corpus is not one.
        """
        t = terminal_from_action(
            action(action="bankruptcyliquidation", value=0.0),
            "2022-03-02", security_id="P:1")
        assert t.kind is not TerminalKind.WRITE_OFF, (
            "a zero DEAL SIZE was read as zero consideration")
        assert t.completeness(100)[0] is False

    @pytest.mark.parametrize("act", ["acquisitionof", "mergerfrom"])
    def test_the_ACQUIRER_side_is_NOT_TERMINAL(self, act):
        """THE ACQUIRER-SIDE TRAP, and why the mapping is per-name rather than a
        substring match.

        `acquisitionof` (7,193 rows) and `mergerfrom` (116) sit on the security
        that BOUGHT something and continues to exist. Any fix that pattern-matched
        on "acquisition" or "merger" would write off the buyer instead of the
        target — worse than the bug it replaced.
        """
        assert terminal_from_action(action(action=act, value=6768.8),
                                    "2022-03-02", security_id="P:1") is None
        assert act not in TERMINAL_ACTIONS
        assert TERMINAL_ACTION_SIDES[act] is ActionSide.ACQUIRER

    def test_every_TARGET_name_in_the_table_is_terminal(self):
        """The table and the frozenset cannot drift apart."""
        for name, side in TERMINAL_ACTION_SIDES.items():
            assert (name in TERMINAL_ACTIONS) is (side is ActionSide.TARGET), name

    def test_the_vocabulary_matches_the_CORPUS_not_an_invented_one(self):
        """The old set listed seven names of which exactly one existed in the
        data. Every name here was read off `SELECT DISTINCT action FROM
        bt_actions`, so a name absent from the corpus is a red flag."""
        observed = {"delisted", "acquisitionby", "acquisitionof", "mergerto",
                    "mergerfrom", "bankruptcyliquidation", "regulatorydelisting",
                    "voluntarydelisting"}
        assert set(TERMINAL_ACTION_SIDES) == observed
        for gone in ("merger", "acquisition", "bankruptcy", "liquidation",
                     "regulatory", "reversemerger"):
            assert gone not in TERMINAL_ACTIONS, (
                f"{gone!r} appears in no row of the corpus")

    def test_adrratiosplit_IS_a_split_and_spinoffdividend_IS_a_dividend(self):
        """Both were absent from their sets. An ADR ratio change alters shares
        per receipt exactly as a split does, so missing it leaves the split
        factor — and therefore every stored episode peak — wrong."""
        assert "adrratiosplit" in SPLIT_ACTIONS
        assert "spinoffdividend" in DIVIDEND_ACTIONS

    @pytest.mark.parametrize("act", ["delisted", "bankruptcyliquidation",
                                     "mergerto", "voluntarydelisting",
                                     "regulatorydelisting", "acquisitionby"])
    def test_NO_TERMS_IS_NOT_A_WRITE_OFF_it_BLOCKS(self, act):
        """THE RULE THIS FILE EXISTS FOR.

        Mapping a terms-less delisting to WRITE_OFF is the obvious
        implementation and it invents a total loss. Because every admission is
        4% of equity, that invented zero permanently shrinks every position
        opened afterwards — and the run stays complete and plausible the whole
        way through.
        """
        t = terminal_from_action(action(action=act, value=None), "2022-03-02",
                                 security_id="P:1")
        assert t.kind is not TerminalKind.WRITE_OFF, (
            f"{act!r} with no stated terms was mapped to a write-off — that "
            f"fabricates a total loss from an absence of information")
        complete, why = t.completeness(100)
        assert complete is False
        assert why == "MISSING_CASH_PER_SHARE"

    def test_a_buyer_ticker_with_NO_terms_blocks_as_unknown_consideration(self):
        t = terminal_from_action(
            action(action="acquisitionby", value=None, contraticker="BBB"),
            "2022-03-02", security_id="P:1", delivered_security_id="P:2",
            delivered_issuer_id="ISS_2")
        complete, why = t.completeness(100)
        assert complete is False and why == "MISSING_CASH_PER_SHARE"

    def test_the_ORIGINAL_action_survives_in_the_reference(self):
        """A terms-less bankruptcy is emitted in the shape of a CASH_MERGER
        because that is what blocks. The audit must still say what actually
        happened, or a reader months later sees a merger that never was."""
        t = terminal_from_action(action(action="bankruptcyliquidation", value=None),
                                 "2022-03-02", security_id="P:1")
        assert t.reference.startswith("actions/bankruptcyliquidation")

    @pytest.mark.parametrize("act", ["split", "dividend", "ticker_change"])
    def test_a_non_terminal_action_produces_nothing(self, act):
        assert terminal_from_action(action(action=act, value=1.0),
                                    "2022-03-02", security_id="P:1") is None
        assert act not in TERMINAL_ACTIONS


class TestTheBlockIsREALNotJustAShape:
    """`completeness()` returning False is a claim about an object. This drives
    the terms through `apply_terminal` against an actual holding and asserts the
    book is left blocked — which is the behaviour, not the shape."""

    def _held(self):
        st = PortfolioState.fresh(100_000.0, n_slots=2)
        # Keyed on the PERMANENT id while the ACTIONS row says "AAA" — which is
        # the whole integration this file now has to prove.
        st.slots[0].occupied_by = "P:1"
        st.episodes[0] = HoldingEpisode(
            security_id="P:1", ticker="AAA", issuer_id="ISS_1", slot_id=0,
            signal_date="2022-02-01", entry_date="2022-02-02",
            entry_raw_open=40.0, entry_split_adjusted_price=40.0,
            initial_shares=100, current_shares=100,
            episode_peak_split_adjusted_close=45.0, market_sessions_held=10)
        st.initialized = True
        return st

    def test_a_terms_less_delisting_leaves_the_holding_UNRESOLVED(self):
        st = self._held()
        res = apply_terminal(
            st, terminal_from_action(action(action="delisted", value=None),
                                     "2022-03-02", security_id="P:1"),
            ledger=Ledger(), session="2022-03-02", cfg=WealthCoreConfig())

        assert res["applied"] is False and res["blocked"] is True
        assert st.unresolved_terminals == {"P:1": "MISSING_CASH_PER_SHARE"}
        assert "P:1" in st.held_security_ids(), (
            "the holding must be PRESERVED — the point of the rule is that an "
            "unknown outcome is not a loss")
        assert st.episodes[0].current_shares == 100

    def test_the_MACHINERY_can_still_write_off_when_terms_SAY_zero(self):
        """THE FALSIFIER, preserved but re-sourced.

        Its original point stands: if nothing could ever reach WRITE_OFF, the
        test above would pass on an implementation that simply never writes
        anything off. What changed is where a stated zero can come FROM. It used
        to be driven by an ACTIONS row with `value == 0.0` — but `value` is a
        transaction SIZE, so that route was reading a deal size as consideration
        and has been removed (defect D2). The terms are therefore constructed
        directly here, which is what proves the machinery works without claiming
        this vendor supplies it.
        """
        st = self._held()
        led = Ledger()
        res = apply_terminal(
            st, TerminalTerms(session="2022-03-02", security_id="P:1",
                              kind=TerminalKind.WRITE_OFF,
                              reference="test/stated-zero"),
            ledger=led, session="2022-03-02", cfg=WealthCoreConfig())
        assert res["applied"] is True and res["kind"] == "WRITE_OFF"
        assert "P:1" not in st.held_security_ids()
        assert [e.event_type.value for e in led.events] == ["WRITE_OFF"]

    def test_the_MACHINERY_can_still_pay_a_cash_merger(self):
        """Same shape: settlement works when terms are genuinely known. Sharadar
        ACTIONS never supplies them, which is a fact about the DATA, not about
        the engine — and the distinction has to stay testable or a future source
        that does supply terms would have no proof it is wired up."""
        st = self._held()
        cash_before = st.cash
        res = apply_terminal(
            st, TerminalTerms(session="2022-03-02", security_id="P:1",
                              kind=TerminalKind.CASH_MERGER,
                              cash_per_share=54.0, reference="test/exact-terms"),
            ledger=Ledger(), session="2022-03-02", cfg=WealthCoreConfig())
        assert res["applied"] is True
        assert st.cash == pytest.approx(cash_before + 100 * 54.0)

    def test_an_ACTIONS_SOURCED_merger_BLOCKS_rather_than_paying(self):
        """The complement, and the one that would have caught D2.

        A real acquisition row carries a deal value of 6768.8 ($6.77bn, TMHC by
        Berkshire). Nothing about it may become cash: the position must stay
        held and unresolved, not be paid out at 6,768.8 per share.
        """
        st = self._held()
        cash_before = st.cash
        res = apply_terminal(
            st, terminal_from_action(
                action(action="acquisitionby", value=6768.8,
                       contraname="BERKSHIRE HATHAWAY INC"),
                "2022-03-02", security_id="P:1"),
            ledger=Ledger(), session="2022-03-02", cfg=WealthCoreConfig())
        assert res["applied"] is False and res["blocked"] is True
        assert st.cash == cash_before, "a deal size was paid out as cash"
        assert "P:1" in st.held_security_ids()
        assert st.unresolved_terminals == {"P:1": "MISSING_CASH_PER_SHARE"}


# ── the event stream as a whole ─────────────────────────────────────────────

class TestTheEventStream:

    class _IGMSIdentity:
        @staticmethod
        def resolve(ticker, session):
            assert session == "2025-08-13"
            return {"IGMS": "110543", "BBB": "220000", "CCC": "330000"}.get(
                ticker)

    def test_the_exact_IGMS_pair_coalesces_once_independent_of_order(self):
        sessions = sessions_index(["2025-08-13"])
        rows = [
            action(ticker="IGMS", date="2025-08-13",
                   action="acquisitionby", value=76.6, contraticker="N/A"),
            action(ticker="IGMS", date="2025-08-13", action="delisted",
                   value=76.6, contraticker="N/A"),
        ]
        counts: dict[str, int] = {}
        forward = terminal_events_from_actions(
            rows, sessions, {"110543"}, identity=self._IGMSIdentity(),
            unresolved=counts)
        reverse = terminal_events_from_actions(
            list(reversed(rows)), sessions, {"110543"},
            identity=self._IGMSIdentity())

        assert forward == reverse
        assert len(forward) == 1
        assert forward[0].security_id == "110543"
        assert forward[0].reference == (
            "actions/acquisitionby deal_value_musd=76.6")
        assert forward[0].cash_per_share is None
        assert forward[0].kind is not TerminalKind.WRITE_OFF
        assert counts == {"terminal_duplicate_rows_collapsed": 1}

    def test_multiple_public_buyers_coalesce_as_one_unknown_consideration(self):
        sessions = sessions_index(["2025-08-13"])
        rows = [
            action(ticker="IGMS", date="2025-08-13",
                   action="acquisitionby", contraticker="BBB"),
            action(ticker="IGMS", date="2025-08-13",
                   action="acquisitionby", contraticker="CCC"),
        ]
        counts: dict[str, int] = {}
        events = terminal_events_from_actions(
            rows, sessions, {"110543"}, identity=self._IGMSIdentity(),
            unresolved=counts)
        assert len(events) == 1
        assert events[0].kind is TerminalKind.CASH_MERGER
        assert events[0].delivered_ticker is None
        assert counts == {"terminal_duplicate_rows_collapsed": 1}

    def test_actions_on_unknown_tickers_are_excluded(self):
        """An action on a security the run cannot hold is not a run event, and
        emitting it anyway puts tens of thousands of NOT_HELD rows into
        `terminal_results` — which is inside the result hash."""
        rows = [action(ticker="AAA", value=54.0),
                action(ticker="ZZZ", value=12.0)]
        got = terminal_events_from_actions(rows, SESSIONS,
                                           known_securities={"AAA"})
        assert [t.security_id for t in got] == ["AAA"]

    def test_events_past_the_window_are_dropped(self):
        rows = [action(date="2022-04-01", value=54.0)]
        assert terminal_events_from_actions(rows, SESSIONS,
                                            known_securities={"AAA"}) == []

    def test_the_order_is_deterministic_regardless_of_row_order(self):
        rows = [action(ticker="CCC", value=1.0), action(ticker="AAA", value=2.0),
                action(ticker="BBB", value=3.0)]
        known = {"AAA", "BBB", "CCC"}
        fwd = [(t.session, t.security_id)
               for t in terminal_events_from_actions(rows, SESSIONS, known)]
        rev = [(t.session, t.security_id)
               for t in terminal_events_from_actions(list(reversed(rows)),
                                                     SESSIONS, known)]
        assert fwd == rev == sorted(fwd)

    def test_every_emitted_event_lands_on_a_REAL_session(self):
        """The invariant `run_sessions` enforces by raising. Checked here so the
        failure names the mapping rather than surfacing 4,000 sessions later."""
        rows = [action(date=d, value=54.0)
                for d in ("2022-03-05", "2022-03-06", "2022-03-02")]
        got = terminal_events_from_actions(rows, SESSIONS, {"AAA"})
        assert got and all(t.session in SESSIONS for t in got)


# ── the caveats say which source ran ────────────────────────────────────────

def test_the_two_caveat_sets_say_opposite_things_about_certification():
    """A run scored on derived splits must not be mistakable for one scored on
    the authoritative stream. The caveats are the only thing that travels with
    the numbers into the evaluator."""
    derived = " ".join(DERIVED_SPLIT_CAVEATS).lower()
    actions = " ".join(ACTIONS_CAVEATS).lower()

    # The fallback path must say so, in both respects.
    assert "not certified-reproducible" in derived
    assert "terminal actions are not modelled" in derived

    # The authoritative path must claim neither.
    assert "not certified-reproducible" not in actions
    assert "terminal actions are not modelled" not in actions
    assert "authoritative" in actions
    # ...and must still describe what the terms-less case does, since that is
    # the behaviour a reader is most likely to be surprised by.
    assert "settlement waterfall" in actions
    assert "public buyer tickers are provenance" in actions


# ── permanent identity (item 7) ─────────────────────────────────────────────

class TestPointInTimeIdentity:
    """`bt_universe` keyed meta on the TICKER, which splices ticker reuse: two
    unrelated companies that held one symbol at different times became a single
    continuous security and momentum ran straight across the discontinuity."""

    ROWS = [
        # One security, two symbols over time — a rename.
        {"permaticker": "111", "ticker": "FB",
         "first_price_date": "2012-05-18", "last_price_date": "2022-06-08"},
        {"permaticker": "111", "ticker": "META",
         "first_price_date": "2022-06-09", "last_price_date": None},
        # One symbol, two securities over time — a reuse.
        {"permaticker": "222", "ticker": "AAA",
         "first_price_date": "2000-01-01", "last_price_date": "2005-01-01"},
        {"permaticker": "333", "ticker": "AAA",
         "first_price_date": "2010-01-01", "last_price_date": None},
    ]

    def r(self):
        from app.wealth_core_replay import IdentityResolver
        return IdentityResolver(self.ROWS)

    def test_a_rename_resolves_to_ONE_permanent_security(self):
        r = self.r()
        assert r.resolve("FB", "2015-01-01") == "P:111"
        assert r.resolve("META", "2023-01-01") == "P:111"

    def test_a_REUSED_ticker_resolves_by_SESSION(self):
        r = self.r()
        assert r.resolve("AAA", "2002-01-01") == "P:222"
        assert r.resolve("AAA", "2015-01-01") == "P:333"
        assert r.reused_tickers == ["AAA"]

    def test_a_session_no_owner_covers_is_REFUSED_not_guessed(self):
        """Between the two owners' windows. Picking either produces a complete
        run of a security that did not exist that day."""
        r = self.r()
        assert r.resolve("AAA", "2007-01-01") is None
        assert r.unresolved == {"out_of_window": 1}

    def test_an_unknown_ticker_is_REFUSED_and_counted(self):
        r = self.r()
        assert r.resolve("ZZZ", "2015-01-01") is None
        assert r.unresolved == {"unknown_ticker": 1}

    def test_OVERLAPPING_windows_are_ambiguous_rather_than_first_wins(self):
        from app.wealth_core_replay import IdentityResolver
        r = IdentityResolver([
            {"permaticker": "1", "ticker": "X",
             "first_price_date": "2000-01-01", "last_price_date": "2020-01-01"},
            {"permaticker": "2", "ticker": "X",
             "first_price_date": "2010-01-01", "last_price_date": None}])
        assert r.resolve("X", "2015-01-01") is None
        assert r.unresolved == {"ambiguous_ticker": 1}

    def test_a_SINGLE_owner_still_requires_interval_proof(self):
        """Owner count is not temporal evidence. Ignoring the interval for the
        common case would let a current label authorize every historical bar."""
        from app.wealth_core_replay import IdentityResolver
        r = IdentityResolver([{"permaticker": "9", "ticker": "SOLO",
                               "first_price_date": "2015-01-01",
                               "last_price_date": "2016-01-01"}])
        assert r.resolve("SOLO", "1999-01-01") is None
        assert r.unresolved == {"out_of_window": 1}

    def test_the_id_is_PREFIXED_so_it_cannot_be_read_as_a_symbol(self):
        from app.wealth_core_replay import SECURITY_ID_PREFIX, permanent_id
        assert permanent_id("199059") == "P:199059"
        assert SECURITY_ID_PREFIX == "P:"
        assert permanent_id(None) is None and permanent_id("  ") is None

    def test_resolution_is_deterministic_regardless_of_row_order(self):
        from app.wealth_core_replay import IdentityResolver
        fwd = IdentityResolver(self.ROWS)
        rev = IdentityResolver(list(reversed(self.ROWS)))
        for session in ("2002-01-01", "2015-01-01", "2023-01-01"):
            assert fwd.resolve("AAA", session) == rev.resolve("AAA", session)
            assert fwd.resolve("META", session) == rev.resolve("META", session)


# ── THE IDENTITY BOUNDARY, end to end ───────────────────────────────────────

class TestTerminalActionsCrossTheIdentityBoundary:
    """The defect an external audit found, and the shape of test that missed it.

    ACTIONS rows are keyed on the SYMBOL. Holdings, metadata and episodes are
    keyed on the PERMANENT id. When `load_meta` moved to permanent ids, the
    replay kept filtering ACTIONS with `known_tickers=set(meta)` — comparing
    `"OLD"` against `{"P:123"}` — so EVERY terminal action was dropped before
    reaching the engine. No cash merger paid, no write-off applied, no
    terms-less delisting blocking anything, and the run completed normally
    reporting an empty `terminal_results`.

    The unit tests above could not catch it: they call
    `terminal_events_from_actions` with a TICKER-keyed universe, which is a
    coherent contract in isolation and the wrong one at the boundary. So the
    tests here always cross it — a holding keyed `P:123`, an ACTIONS row saying
    `OLD`, and a resolver in between.
    """

    from app.wealth_core_replay import IdentityResolver  # noqa: E402

    ROWS = [
        {"permaticker": "123", "ticker": "OLD",
         "first_price_date": "2020-01-01", "last_price_date": None},
        {"permaticker": "456", "ticker": "ACQ",
         "first_price_date": "2020-01-01", "last_price_date": None},
    ]

    def resolver(self):
        from app.wealth_core_replay import IdentityResolver
        return IdentityResolver(self.ROWS)

    def test_an_ACTIONS_row_resolves_onto_the_PERMANENT_holding(self):
        """The exact reproduction: the universe is `{P:123}`, the row says
        `OLD`, and the event must still be emitted — against `P:123`."""
        got = terminal_events_from_actions(
            [action(ticker="OLD", value=54.0)], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver())
        assert len(got) == 1, (
            "the terminal action was filtered out — a ticker was compared "
            "against a permanent-id universe")
        assert got[0].security_id == "P:123"

    def test_WITHOUT_the_resolver_the_universe_filter_drops_everything(self):
        """The failing configuration, pinned so it cannot come back silently."""
        got = terminal_events_from_actions(
            [action(ticker="OLD", value=54.0)], SESSIONS,
            known_securities={"P:123"}, identity=None)
        assert got == [], (
            "without resolution a ticker cannot match a permanent-id universe; "
            "if this ever returns an event the filter is not doing its job")

    def test_the_buyer_security_is_not_mistaken_for_consideration(self):
        from stock_strategy_shared.wealth_core.feed import SecurityMeta
        meta = {"P:456": SecurityMeta(security_id="P:456", ticker="ACQ",
                                      permaticker="456")}
        got = terminal_events_from_actions(
            [action(ticker="OLD", action="acquisitionby", value=0.757,
                    contraticker="ACQ")], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver(), meta=meta)
        assert len(got) == 1
        t = got[0]
        assert t.security_id == "P:123"
        assert t.kind is TerminalKind.CASH_MERGER
        assert t.delivered_security_id is None
        assert t.delivered_ticker is None
        assert t.delivered_issuer_id is None
        assert "counterparty_ticker=ACQ" in t.reference

    def test_an_UNRESOLVABLE_buyer_is_provenance_not_delivered_identity(self):
        counts: dict = {}
        got = terminal_events_from_actions(
            [action(ticker="OLD", action="acquisitionby", value=0.757,
                    contraticker="NOSUCH")], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver(),
            unresolved=counts)
        assert len(got) == 1
        assert got[0].delivered_security_id is None
        complete, why = got[0].completeness(100)
        assert complete is False and why == "MISSING_CASH_PER_SHARE"
        assert counts == {}

    def test_an_UNRESOLVABLE_SOURCE_is_dropped_and_counted(self):
        counts: dict = {}
        got = terminal_events_from_actions(
            [action(ticker="GHOST", value=54.0)], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver(),
            unresolved=counts)
        assert got == []
        assert counts.get("terminal_source_unresolved") == 1

    def test_the_resolved_event_LANDS_ON_THE_PERMANENT_holding(self):
        """The end of the chain, and the assertion that would have failed
        loudest: resolve, then apply, and confirm the position is gone and the
        cash arrived. Every layer above can be right while this is broken."""
        st = PortfolioState.fresh(1_000.0, n_slots=2)
        st.slots[0].occupied_by = "P:123"
        st.episodes[0] = HoldingEpisode(
            security_id="P:123", ticker="OLD", issuer_id="ISS_1", slot_id=0,
            signal_date="2022-02-01", entry_date="2022-02-02",
            entry_raw_open=40.0, entry_split_adjusted_price=40.0,
            initial_shares=100, current_shares=100,
            episode_peak_split_adjusted_close=45.0, market_sessions_held=10)
        st.initialized = True

        events = terminal_events_from_actions(
            [action(ticker="OLD", value=54.0)], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver())
        res = apply_terminal(st, events[0], ledger=Ledger(),
                             session="2022-03-02", cfg=WealthCoreConfig())

        # The event REACHED the permanent holding — which is what this test is
        # about. It then blocks for want of terms (defect D2: the vendor states
        # a deal SIZE, never a per-share price), and that is a separate fact.
        assert res["blocked"] is True
        assert st.unresolved_terminals == {"P:123": "MISSING_CASH_PER_SHARE"}
        # PRESERVED, not terminated. An unknown outcome is not a loss, and the
        # position must remain available for a real resolution to arrive.
        assert "P:123" in st.held_security_ids()
        assert st.cash == pytest.approx(1_000.0)

    def test_a_terms_less_delisting_BLOCKS_the_PERMANENT_holding(self):
        """The other end of the same boundary: the block must land on the id the
        book is keyed by, or `unresolved_terminals` names a security nothing
        holds and admissions are never actually stopped."""
        st = PortfolioState.fresh(1_000.0, n_slots=2)
        st.slots[0].occupied_by = "P:123"
        st.episodes[0] = HoldingEpisode(
            security_id="P:123", ticker="OLD", issuer_id="ISS_1", slot_id=0,
            signal_date="2022-02-01", entry_date="2022-02-02",
            entry_raw_open=40.0, entry_split_adjusted_price=40.0,
            initial_shares=100, current_shares=100,
            episode_peak_split_adjusted_close=45.0, market_sessions_held=10)
        st.initialized = True

        events = terminal_events_from_actions(
            [action(ticker="OLD", action="delisted", value=None)], SESSIONS,
            known_securities={"P:123"}, identity=self.resolver())
        apply_terminal(st, events[0], ledger=Ledger(), session="2022-03-02",
                       cfg=WealthCoreConfig())

        assert st.unresolved_terminals == {"P:123": "MISSING_CASH_PER_SHARE"}
        assert "P:123" in st.held_security_ids()
