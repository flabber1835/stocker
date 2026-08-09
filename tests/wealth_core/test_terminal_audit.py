"""The PER-EPISODE TERMINAL AUDIT, and the one hash it is allowed to move.

WHAT THIS IS FOR. The 2021-2023 rehearsal carried $342,136.68 and settled
$342,419.72 — $283.04 apart — with no way to say which of the eight episodes
produced the difference. The audit exists to make that attributable, and these
tests exist because the audit is being added to a CERTIFIED artefact: the
re-pin is authorised for exactly ONE hash movement (`final_result`), so
"observability only" has to be a proven property rather than an intention.

The four things that must hold, and each fails in a different direction:

    the reconciliation identity      delta == S_settle*P_settle - S_carry*P_carry,
                                     including when a split moves the share count
    no OTHER hash moves              audit data is persisted but never hashed
    a restart keeps the provenance   a carry outliving a redeploy must still
                                     reconcile, or long graces are exactly the
                                     ones missing from the audit
    the field set is COMPLETE        a field discovered later costs a SECOND
                                     re-pin, which is what condition 6 forbids
"""
from __future__ import annotations

import json

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    step_session, tradeability_only_bars)
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.settlement import (
    C1_GRACE_SESSIONS, empty_counters)
from stock_strategy_shared.wealth_core.state import (
    _AUDIT_ONLY_STATE_KEYS, HoldingEpisode, PortfolioState)
from stock_strategy_shared.wealth_core.terminal import TerminalKind, TerminalTerms
from stock_strategy_shared.wealth_core.terminal_audit import (
    AUDIT_FIELDS, episode_audit, reconcile)

CFG = WealthCoreConfig()
SID, VER = "stocker_wealth_core_v1", 1


def db(sec="S1", session="d1", *, signal=100.0, open_=99.0, mark=100.0,
       split=1.0, tradeable=True):
    return DailyBar(security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
                    session=session, signal_close_split_adj_div_unadj=signal,
                    raw_open=open_, raw_mark_close=mark, tradeable=tradeable,
                    split_ratio=split, dividend_per_share=0.0,
                    unresolved_corporate_action=False)


def seated(cash=10_000.0, sec="S1", shares=10, entry=100.0, last_print="d0"):
    st = PortfolioState.fresh(cash)
    st.slots[0].occupied_by = sec
    st.episodes[0] = HoldingEpisode(sec, f"T{sec[1:]}", f"I{sec[1:]}", 0, "d0", "d0",
                                    entry, entry, shares, shares, entry)
    st.initialized = True
    if last_print:
        st.last_valid_mark_session[sec] = last_print
    return st


def terms(session="d1"):
    """Terms as the corpus actually produces them: a documented event with NO
    per-share consideration, which is every one of Sharadar's 19,216."""
    return TerminalTerms(session=session, security_id="S1",
                         kind=TerminalKind.CASH_MERGER,
                         reference="test/terms-pending")


def run(*, mid_grace_bars=(), carry_mark=90.0, shares=10):
    """Announce a terms-less event with no bar (so the carry takes `carry_mark`),
    play `mid_grace_bars`, then go quiet until the grace expires."""
    st, led = seated(shares=shares), Ledger()
    lk, counters = {"S1": carry_mark}, empty_counters()
    audits = []

    def _step(session, bars):
        res = step_session(session=session, state=st, bars=list(bars), pending=[],
                           ledger=led, last_known=lk, cfg=CFG, strategy_id=SID,
                           strategy_version=VER,
                           security_bars=tradeability_only_bars(list(bars), None),
                           terminal_terms=([terms()] if session == "d1" else []),
                           settlement_counters=counters)
        for r in res.terminal_results:
            if r.get("terminal_audit"):
                audits.append(r["terminal_audit"])
        return res

    _step("d1", [])
    for i, b in enumerate(mid_grace_bars):
        _step(f"m{i}", [b])
    for i in range(C1_GRACE_SESSIONS + 1):
        _step(f"q{i}", [])
    return st, led, counters, audits


# ── 1. the reconciliation identity ───────────────────────────────────────────

class TestTheReconciliationIdentity:
    """Acceptance condition 4, revised 2026-08-09: recompute both notionals from
    the persisted CONTEMPORANEOUS shares and prices, and prove the per-episode
    differences sum to the reported figure exactly."""

    def test_a_quiet_carry_reconciles_to_ZERO(self):
        """The base case, and the reason the rehearsal's difference is 0.08%
        rather than large: a delisted security stops printing, so most carries
        settle at the very mark they were carried at."""
        _, _, c, audits = run()
        a, = audits
        assert a["carry_notional"] == pytest.approx(900.0)
        assert a["settlement_notional"] == pytest.approx(900.0)
        assert a["notional_delta"] == pytest.approx(0.0)
        assert a["grace_prints"] == [] and a["grace_splits"] == []
        assert reconcile(audits)["residual"] == pytest.approx(0.0)

    def test_a_mid_grace_PRICE_MOVE_is_attributed_to_the_price(self):
        _, _, c, audits = run(mid_grace_bars=[db(session="m0", mark=92.0,
                                                 signal=92.0)])
        a, = audits
        assert a["shares_at_carry"] == a["shares_at_settlement"] == 10
        assert a["carry_price"] == pytest.approx(90.0)
        assert a["settlement_price"] == pytest.approx(92.0)
        assert a["notional_delta"] == pytest.approx(20.0)
        assert [p["price"] for p in a["grace_prints"]] == [92.0]
        assert a["grace_split_multiplier"] == 1.0

    def test_a_mid_grace_SPLIT_is_attributed_to_the_share_count(self):
        """THE case that forced the two-share-count schema. Neither share count
        alone reconstructs this: 10*(46-90) = -440 and 20*(46-90) = -880, and
        the true answer is +20."""
        _, _, c, audits = run(mid_grace_bars=[db(session="m0", split=2.0,
                                                mark=46.0, signal=46.0)])
        a, = audits
        assert a["shares_at_carry"] == 10 and a["shares_at_settlement"] == 20
        assert a["grace_split_multiplier"] == pytest.approx(2.0)
        assert a["grace_splits"][0]["shares_before"] == 10
        assert a["grace_splits"][0]["shares_after"] == 20
        assert a["notional_delta"] == pytest.approx(20.0)
        assert a["notional_delta"] != pytest.approx(10 * (46.0 - 90.0))
        assert a["notional_delta"] != pytest.approx(20 * (46.0 - 90.0))

    def test_the_delta_is_the_difference_of_the_two_NOTIONALS(self):
        """Stated as the identity itself rather than as an expected number, so
        it holds for any scenario rather than for the ones written here."""
        for bars in ([], [db(session="m0", mark=92.0, signal=92.0)],
                     [db(session="m0", split=2.0, mark=46.0, signal=46.0)],
                     [db(session="m0", split=3.0, mark=31.0, signal=31.0)]):
            _, _, _, audits = run(mid_grace_bars=bars)
            a, = audits
            assert a["notional_delta"] == pytest.approx(
                a["shares_at_settlement"] * a["settlement_price"]
                - a["shares_at_carry"] * a["carry_price"]), bars

    def test_the_audit_agrees_with_the_SETTLEMENT_COUNTERS(self):
        """The audit must reconcile the very totals that produced the $283.04,
        or it is measuring a different population and proves nothing about it."""
        for bars in ([], [db(session="m0", mark=92.0, signal=92.0)],
                     [db(session="m0", split=2.0, mark=46.0, signal=46.0)]):
            _, _, c, audits = run(mid_grace_bars=bars)
            rec = reconcile(audits)
            assert rec["carried_notional_total"] == pytest.approx(
                c["pending_terms_carried_notional"]), bars
            assert rec["settled_notional_total"] == pytest.approx(
                c["derived_last_mark_settlements_notional"]), bars
            assert rec["residual"] == pytest.approx(0.0), bars

    def test_a_TRUNCATING_split_still_reconciles(self):
        """`apply_splits` truncates (`int(before * ratio)`), so an odd share
        count under a 3-for-2 does not deliver the stated ratio. The recorded
        before/after counts are what keep that from reading as a pricing error."""
        _, _, c, audits = run(shares=15,
                              mid_grace_bars=[db(session="m0", split=1.5,
                                                 mark=60.0, signal=60.0)])
        a, = audits
        assert a["shares_at_carry"] == 15 and a["shares_at_settlement"] == 22
        assert a["grace_splits"][0]["ratio"] == pytest.approx(1.5)
        assert a["notional_delta"] == pytest.approx(22 * 60.0 - 15 * 90.0)
        assert reconcile(audits)["residual"] == pytest.approx(0.0)


# ── 2. it moves no hash it is not allowed to move ────────────────────────────

class TestTheAuditMovesNoOtherHash:
    """The re-pin is authorised for ONE movement. `state_hash` covers
    `to_dict()` and `daily_state_hash` chains one per session, so provenance
    stored naively would move three hashes and the authorisation would not
    cover it."""

    def test_carry_provenance_does_not_move_the_STATE_hash(self):
        st = PortfolioState.fresh(10_000.0)
        before = st.state_hash()
        st.terminal_carry_audit["S1"] = {
            "carry_session": "d1", "shares_at_carry": 10, "carry_price": 90.0,
            "grace_prints": [{"session": "m0", "price": 92.0}]}
        st.last_valid_mark_session["S1"] = "d0"
        assert st.state_hash() == before, (
            "audit provenance reached the state hash, so adding it moves "
            "daily_state and final_state as well — three movements, not one")

    def test_the_audit_keys_are_PERSISTED_even_though_unhashed(self):
        """The other half. Excluded from the hash but NOT from the blob: a carry
        can outlive a redeploy, and provenance lost on restart would be missing
        from precisely the long graces most worth auditing."""
        st = PortfolioState.fresh(10_000.0)
        st.terminal_carry_audit["S1"] = {"carry_price": 90.0,
                                         "shares_at_carry": 10}
        st.last_valid_mark_session["S1"] = "d0"
        back = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        assert back.terminal_carry_audit == st.terminal_carry_audit
        assert back.last_valid_mark_session == st.last_valid_mark_session

    def test_hash_payload_is_to_dict_minus_EXACTLY_the_audit_keys(self):
        """Pins the exclusion list to the two keys it is meant to hold. A prefix
        or naming convention here would silently capture the next field somebody
        names badly, and excluding a REAL state field from the hash is a parity
        check that passes when it should fail."""
        st = PortfolioState.fresh(10_000.0)
        assert set(st.to_dict()) - set(st.hash_payload()) == _AUDIT_ONLY_STATE_KEYS
        assert _AUDIT_ONLY_STATE_KEYS == {"terminal_carry_audit",
                                          "last_valid_mark_session"}

    def test_the_final_state_report_carries_no_audit_bookkeeping(self):
        """`final_state` sits inside the `final_result` hash.
        `last_valid_mark_session` holds one entry per HELD security, terminal or
        not, so leaving it in would widen the re-pin from "the terminal audit"
        to "mark bookkeeping for the whole book"."""
        st = seated()
        st.last_valid_mark_session["S1"] = "d0"
        st.terminal_carry_audit["S1"] = {"carry_price": 90.0}
        assert "last_valid_mark_session" not in st.hash_payload()
        assert "terminal_carry_audit" not in st.hash_payload()


# ── 3. a restart mid-grace ───────────────────────────────────────────────────

class TestARestartMidGraceKeepsTheProvenance:

    def test_a_carry_that_survives_a_restart_still_reconciles(self):
        """The deploy restarts weekly and a grace runs ten sessions, so this is
        the ordinary case rather than an edge one. Provenance held only in
        memory would leave the longest carries unreconcilable."""
        st, led = seated(), Ledger()
        lk, c = {"S1": 90.0}, empty_counters()
        step_session(session="d1", state=st, bars=[], pending=[], ledger=led,
                     last_known=lk, cfg=CFG, strategy_id=SID,
                     strategy_version=VER,
                     security_bars=tradeability_only_bars([], None),
                     terminal_terms=[terms()], settlement_counters=c)
        assert st.terminal_carry_audit["S1"]["shares_at_carry"] == 10

        # The redeploy: state through JSON and back, as a restart really does.
        st = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        assert st.terminal_carry_audit["S1"]["carry_price"] == 90.0

        audits = []
        for i in range(C1_GRACE_SESSIONS + 1):
            res = step_session(session=f"q{i}", state=st, bars=[], pending=[],
                               ledger=led, last_known=lk, cfg=CFG,
                               strategy_id=SID, strategy_version=VER,
                               security_bars=tradeability_only_bars([], None),
                               settlement_counters=c)
            audits += [r["terminal_audit"] for r in res.terminal_results
                       if r.get("terminal_audit")]
        a, = audits
        assert a["carried"] is True
        assert a["carry_session"] == "d1"
        assert a["notional_delta"] is not None, (
            "the carry side was lost across the restart, so the episode can no "
            "longer be reconciled at all")
        assert reconcile(audits)["residual"] == pytest.approx(0.0)


# ── 4. the field set is complete ─────────────────────────────────────────────

class TestTheFieldSetIsFinal:
    """Condition 6 permits ONE re-pin. A field discovered after the hash has
    moved turns one deliberate movement into two, and a hash that moves twice
    for the same reason is a hash nobody trusts."""

    def test_every_declared_field_is_present_on_a_real_settlement(self):
        _, _, _, audits = run(mid_grace_bars=[db(session="m0", split=2.0,
                                                 mark=46.0, signal=46.0)])
        a, = audits
        assert set(a) == set(AUDIT_FIELDS), (
            f"missing {set(AUDIT_FIELDS) - set(a)}, extra {set(a) - set(AUDIT_FIELDS)}")

    def test_every_declared_field_is_POPULATED_on_a_carried_settlement(self):
        """Present-but-None would satisfy the test above while answering none of
        the questions the audit exists to answer."""
        _, _, _, audits = run(mid_grace_bars=[db(session="m0", split=2.0,
                                                 mark=46.0, signal=46.0)])
        a, = audits
        for f in AUDIT_FIELDS:
            assert a[f] is not None, f
        assert a["ticker"] == "T1" and a["security_id"] == "S1"
        assert a["event_session"] == "d1"
        assert a["event_kind"] == "CASH_MERGER"
        assert a["settlement_method"] == "LAST_TRUSTWORTHY_MARK"
        assert a["last_trustworthy_print_session"] == "d0"

    def test_an_UNCARRIED_settlement_has_no_delta_rather_than_a_zero_one(self):
        """A C2 orphan never had a carry. "There was nothing to reconcile" and
        "it reconciled to zero" are different statements, and only the second is
        a check that passed."""
        a = episode_audit(security_id="S1", ticker="T1", event_session=None,
                          event_kind=None, carry=None,
                          settlement_session="q9", settlement_method="ZERO_ORPHAN",
                          shares_at_settlement=10, settlement_price=0.0)
        assert a["carried"] is False
        assert a["carry_notional"] is None
        assert a["notional_delta"] is None
        assert a["settlement_notional"] == 0.0, (
            "an orphan zero is a DECISION and settles at exactly 0.0; None here "
            "would make it indistinguishable from an absent settlement")
        assert reconcile([a])["uncarried_settlements"] == 1

    def test_reconcile_REFUSES_to_hide_an_unreconcilable_episode(self):
        """A carried episode whose settlement has no cash notional — a
        CONVERSION, paid in shares. Summing its None as 0.0 would let the
        reconciliation appear to close while an episode's value went
        unaccounted, which is the exact failure condition 4 exists to catch."""
        a = episode_audit(
            security_id="S1", ticker="T1", event_session="d1",
            event_kind="CONVERSION",
            carry={"carry_session": "d1", "shares_at_carry": 10,
                   "carry_price": 90.0},
            settlement_session="q9", settlement_method="EXACT_TERMS",
            shares_at_settlement=10, settlement_price=None)
        rec = reconcile([a])
        assert rec["unreconciled_episodes"] == ["S1"]
        assert rec["residual"] != pytest.approx(0.0), (
            "the totals appeared to balance while an episode contributed a "
            "carry notional and no settlement notional")
