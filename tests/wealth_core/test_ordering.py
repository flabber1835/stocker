"""The two named ordering conventions, with deliberate ties.

Ties are constructed EXACTLY here — identical momentum, identical durable score
— because that is the only condition under which either rule does anything. A
test with distinct values passes whatever the comparator says and proves
nothing, which is how an ordering rule ends up unverified in the first place.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.engine import (
    Reason,
    SecurityBar,
    WealthCoreConfig,
    decide,
    score_universe,
)
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.ordering import (
    CANONICAL_PROFILE,
    ISSUER_CONFLICT_ADMISSION_TIE_BREAK,
    LEADERSHIP_BOUNDARY_TIE_BREAK,
    RULES,
)
from stock_strategy_shared.wealth_core.signals import DurableScore, rank_candidates
from stock_strategy_shared.wealth_core.state import PortfolioState

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def series(total_return: float, vol_kick: float = 0.0, n: int = 127):
    """A 127-close window whose 21-to-126 momentum is exactly `total_return`.

    Built backwards from the two endpoints the signal actually reads so two
    securities can be given IDENTICAL momentum while differing elsewhere — which
    is the whole point of these fixtures.
    """
    closes = [100.0] * n
    for i in range(n - 126, n - 21):
        closes[i] = 100.0 * (1.0 + total_return * (i - (n - 127)) / 105.0)
        closes[i] += vol_kick * ((i % 3) - 1)
    closes[n - 127] = 100.0
    closes[n - 22] = 100.0 * (1.0 + total_return)
    for i in range(n - 21, n):
        closes[i] = closes[n - 22] * 1.01           # positive recent return
    return closes


class TestTheRulesAreNamedAndSelfDescribing:

    def test_both_rules_exist_under_their_required_names(self):
        assert set(RULES) == {"leadership_boundary_tie_break",
                              "issuer_conflict_admission_tie_break"}

    def test_stable_identifiers_come_before_tickers(self):
        """A ticker is reassigned after a delisting and changes on a rebrand, so
        a tie broken on ticker is broken on a MUTABLE label: the same two
        securities can order differently across two runs of the same data
        because a vendor renamed one in between."""
        for rule in RULES.values():
            assert rule.fields.index("security_id") < rule.fields.index("ticker")

    def test_the_field_list_drives_the_comparator(self):
        """`fields` is not documentation — the sort key is built from it, so the
        description cannot drift away from the behaviour."""
        row = DurableScore("S2", "AAA", 0.5, 0.1, 0.3, 1.7, True, "")
        assert LEADERSHIP_BOUNDARY_TIE_BREAK.key(row) == (-0.5, "S2", "AAA")
        assert ISSUER_CONFLICT_ADMISSION_TIE_BREAK.key(row) == (-1.7, "S2", "AAA")


class TestLeadershipBoundaryTie:

    def bars(self, ids):
        # Every security gets the SAME return, so momentum ties across the whole
        # population and the cutoff falls in the middle of a tie.
        return [SecurityBar(sid, tkr, f"I_{sid}", series(0.40))
                for sid, tkr in ids]

    def test_an_exact_momentum_tie_is_broken_by_the_permanent_identifier(self):
        ids = [(f"SEC_{i:03d}", f"T{i:03d}") for i in range(40)]
        cfg = WealthCoreConfig(minimum_leadership_population=5)
        scored = score_universe(self.bars(ids), cfg)
        assert len({s.momentum for s in scored}) == 1, "the fixture must tie"
        chosen = sorted(s.security_id for s in scored if s.in_top_decile)
        assert chosen == [f"SEC_{i:03d}" for i in range(5)], (
            "the lowest security_ids win a pure tie — arbitrary, but FIXED, and "
            "the alternative is that input order chooses the book")

    def test_the_tie_break_does_not_depend_on_input_order(self):
        ids = [(f"SEC_{i:03d}", f"T{i:03d}") for i in range(40)]
        cfg = WealthCoreConfig(minimum_leadership_population=5)
        a = {s.security_id for s in score_universe(self.bars(ids), cfg)
             if s.in_top_decile}
        b = {s.security_id for s in
             score_universe(list(reversed(self.bars(ids))), cfg)
             if s.in_top_decile}
        assert a == b

    def test_a_ticker_rename_cannot_move_the_boundary(self):
        """The concrete failure the identifier ordering prevents."""
        ids = [(f"SEC_{i:03d}", f"T{i:03d}") for i in range(40)]
        renamed = [(sid, "ZZZ" if sid == "SEC_002" else tkr) for sid, tkr in ids]
        cfg = WealthCoreConfig(minimum_leadership_population=5)
        a = {s.security_id for s in score_universe(self.bars(ids), cfg)
             if s.in_top_decile}
        b = {s.security_id for s in score_universe(self.bars(renamed), cfg)
             if s.in_top_decile}
        assert a == b and "SEC_002" in a


class TestIssuerConflictTie:

    def test_an_exact_score_tie_is_broken_by_the_permanent_identifier(self):
        rows = [DurableScore("SEC_B", "BBB", 0.4, 0.1, 0.2, 2.0, True, ""),
                DurableScore("SEC_A", "AAA", 0.4, 0.1, 0.2, 2.0, True, "")]
        assert [r.security_id for r in rank_candidates(rows)] == ["SEC_A", "SEC_B"]
        assert [r.security_id for r in rank_candidates(list(reversed(rows)))] == \
            ["SEC_A", "SEC_B"]

    def conflicting(self):
        """Two securities, ONE issuer, identical windows — so they tie on
        momentum AND on durable score, and only the named rule separates them."""
        w = series(0.40)
        return [SecurityBar("SEC_A", "AAA", "ISSUER_X", w),
                SecurityBar("SEC_B", "BBB", "ISSUER_X", w)]

    def marks(self):
        return {s: Mark(s, MarkStatus.CURRENT, raw_mark_close=100.0)
                for s in ("SEC_A", "SEC_B")}

    def opening(self):
        """The INITIAL construction, where the budget is every free slot.

        Once a book is initialised the budget is one admission per session and
        `decide` breaks out of the candidate loop as soon as it is spent — so
        the second candidate is never examined and no conflict is recorded. That
        is correct (it was not rejected, it was not reached) and it means a
        conflict fixture has to be built on the opening, or on a session where
        the higher-ranked names are already held. The golden run exercises the
        second route; this exercises the first.
        """
        st = PortfolioState.fresh(1_000_000.0)
        st.initialized = False
        return st

    def test_only_one_of_an_issuer_is_admitted_and_the_loser_is_recorded(self):
        st = self.opening()
        d = decide(session="s", state=st, bars=self.conflicting(),
                   marks=self.marks(), cfg=CFG, strategy_id=SID, strategy_version=VER)
        entries = [o for o in d.operations
                   if o.reason is Reason.ENTRY_DURABLE_RANK]
        assert len(entries) == 1 and entries[0].security_id == "SEC_A"
        rej = [r for r in d.admission_rejections
               if r["reason"] == "ISSUER_CONFLICT"]
        assert len(rej) == 1 and rej[0]["security_id"] == "SEC_B"

    def test_the_complete_comparison_tuple_is_persisted_on_the_audit_row(self):
        """Recomputing it later gets THAT day's code, not the rule that applied."""
        st = self.opening()
        d = decide(session="s", state=st, bars=self.conflicting(),
                   marks=self.marks(), cfg=CFG, strategy_id=SID, strategy_version=VER)
        tb = next(r for r in d.admission_rejections
                  if r["reason"] == "ISSUER_CONFLICT")["tie_break"]
        assert tb["rule"] == "issuer_conflict_admission_tie_break"
        assert tb["fields"] == ["score", "security_id", "ticker"]
        assert set(tb["values"]) == {"score", "security_id", "ticker"}
        assert tb["values"]["security_id"] == "SEC_B"

    def test_the_audit_row_survives_serialisation(self):
        st = self.opening()
        d = decide(session="s", state=st, bars=self.conflicting(),
                   marks=self.marks(), cfg=CFG, strategy_id=SID, strategy_version=VER)
        blob = d.to_dict()["admission_rejections"]
        assert any("tie_break" in r for r in blob)

    def test_the_conflict_is_decided_at_ADMISSION_not_before_the_cutoff(self):
        """The certified correction: related securities are never removed from
        the leadership population, so both must appear as candidates."""
        st = self.opening()
        d = decide(session="s", state=st, bars=self.conflicting(),
                   marks=self.marks(), cfg=CFG, strategy_id=SID, strategy_version=VER)
        assert {c.security_id for c in d.candidates} == {"SEC_A", "SEC_B"}
        assert all(c.in_top_decile for c in d.candidates)


class TestTheProfileIsSelectableAndHashed:

    def test_the_profile_is_part_of_the_config_hash(self, monkeypatch):
        """So a run scored under one profile can never be mistaken for a run
        scored under another — which is what makes a future compatibility
        profile a deliberate change rather than a silent re-interpretation of
        every historical result."""
        from stock_strategy_shared.wealth_core import engine as eng
        base = WealthCoreConfig()
        assert base.ordering_profile == CANONICAL_PROFILE
        monkeypatch.setattr(eng, "KNOWN_PROFILES",
                            (CANONICAL_PROFILE, "frozen_prototype_v0"))
        other = WealthCoreConfig(ordering_profile="frozen_prototype_v0")
        assert other.config_hash() != base.config_hash(), (
            "two profiles hashing identically would let a re-pinned fixture "
            "silently claim to be the canonical run")

    def test_an_unknown_profile_is_refused_rather_than_defaulted(self):
        """Silently falling back to canonical would score a run under rules the
        caller explicitly did not ask for."""
        with pytest.raises(ValueError) as e:
            WealthCoreConfig(ordering_profile="frozen_prototype_v0")
        assert "canonical_2026_08" in str(e.value)
