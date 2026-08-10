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

    def test_every_CASH_field_is_POPULATED_on_a_carried_cash_settlement(self):
        """Present-but-None would satisfy the test above while answering none of
        the questions the audit exists to answer.

        The non-cash fields are exempt BY KIND, not by convenience: a cash
        settlement delivered no shares, so `shares_delivered` is absent because
        there were none — which is a different statement from "not recorded".
        `settlement_kind` is what tells the two apart, and it is required here.
        """
        _, _, _, audits = run(mid_grace_bars=[db(session="m0", split=2.0,
                                                 mark=46.0, signal=46.0)])
        a, = audits
        non_cash_only = {"delivered_security_id", "delivered_ticker",
                         "shares_delivered", "exchange_ratio",
                         "cash_consideration", "cash_in_lieu"}
        for f in AUDIT_FIELDS:
            if f in non_cash_only:
                assert a[f] is None, f"{f} should be absent on a cash settlement"
            else:
                assert a[f] is not None, f
        assert a["ticker"] == "T1" and a["security_id"] == "S1"
        assert a["event_session"] == "d1"
        assert a["event_kind"] == "CASH_MERGER"
        assert a["settlement_kind"] == "cash"
        assert a["episode_continues"] is False
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

    def test_a_CONVERSION_is_typed_and_bucketed_rather_than_unreconciled(self):
        """Owner decision 2026-08-09: a carried episode paid in SHARES is
        reconciled in its own terms, not left as a hole.

        It must not enter the cash sum — differencing "no cash" against the
        carry would report a total loss of the carried value, the same
        fabricated write-off the incomplete-terms block exists to prevent,
        arriving through the audit instead of through the waterfall. So it is
        typed `non_cash`, its cash legs and share leg are stated separately, and
        the cash totals still balance without it.
        """
        cashy = episode_audit(
            security_id="S0", ticker="T0", event_session="d1",
            event_kind="CASH_MERGER",
            carry={"carry_session": "d1", "shares_at_carry": 10,
                   "carry_price": 90.0},
            settlement_session="q9",
            settlement_method="LAST_TRUSTWORTHY_MARK",
            shares_at_settlement=10, settlement_price=92.0)
        conv = episode_audit(
            security_id="S1", ticker="T1", event_session="d1",
            event_kind="CONVERSION",
            carry={"carry_session": "d1", "shares_at_carry": 10,
                   "carry_price": 90.0},
            settlement_session="q9", settlement_method="EXACT_TERMS",
            shares_at_settlement=10, settlement_price=None,
            delivered_security_id="S2", delivered_ticker="T2",
            shares_delivered=14, exchange_ratio=1.435,
            cash_consideration=0.0, cash_in_lieu=52.5,
            episode_continues=True)

        assert conv["settlement_kind"] == "non_cash"
        assert conv["notional_delta"] is None
        assert conv["episode_continues"] is True

        rec = reconcile([cashy, conv])
        assert rec["unreconciled_episodes"] == [], (
            "a conversion is accounted for by TYPE; leaving it unreconciled "
            "would block a re-pin that has nothing wrong with it")
        assert rec["non_cash_episodes"] == 1
        assert rec["non_cash_carried_notional"] == pytest.approx(900.0)
        assert rec["non_cash_cash_legs"] == pytest.approx(52.5)
        assert rec["non_cash_detail"][0]["delivered_security_id"] == "S2"
        assert rec["non_cash_detail"][0]["shares_delivered"] == 14
        # The CASH totals balance over the cash episode alone — the conversion
        # neither inflates nor deflates them.
        assert rec["cash_settled_episodes"] == 1
        assert rec["carried_notional_total"] == pytest.approx(900.0)
        assert rec["settled_notional_total"] == pytest.approx(920.0)
        assert rec["residual"] == pytest.approx(0.0)

    def test_an_episode_in_NEITHER_bucket_is_reported_unreconciled(self):
        """The backstop. `unreconciled_episodes` is the list that must be empty
        before the re-pin, so it has to be able to become non-empty — an audit
        arriving without a `settlement_kind` (an older serialised run, or a new
        kind nobody bucketed) must surface rather than be counted as cash."""
        orphaned = {"security_id": "S9", "carried": True,
                    "carry_notional": 900.0, "settlement_notional": None,
                    "notional_delta": None}
        rec = reconcile([orphaned])
        assert rec["unreconciled_episodes"] == ["S9"]

    def test_every_declared_KIND_belongs_to_exactly_one_bucket(self):
        """Totality, in the shape `settlement.counter_for` already uses: a new
        kind must not be able to slip through uncounted. Without this the
        backstop above is unreachable in practice and would rot."""
        from stock_strategy_shared.wealth_core import terminal_audit as ta
        kinds = {ta.KIND_CASH, ta.KIND_ZERO, ta.KIND_NON_CASH, ta.KIND_MIXED}
        non_cash_bucket = {ta.KIND_NON_CASH, ta.KIND_MIXED}
        assert ta.CASH_SETTLING_KINDS | non_cash_bucket == kinds
        assert ta.CASH_SETTLING_KINDS & non_cash_bucket == set()

    def test_a_carried_CONVERSION_through_the_ENGINE_is_typed_and_rounded(self):
        """The path the eight rehearsal episodes could actually take, end to
        end: carried on a terms-less event, then EXACT conversion terms arrive.

        The rounding assertion is a REGRESSION. The delivered share count comes
        from a truncating entitlement split and so is only knowable after
        dispatch, and the first cut merged the raw result dict straight into the
        audit — which wrote money fields that never passed through `_money`. A
        cash-in-lieu of 49.0000000000002 reached `non_cash_cash_legs`, a
        REPORTED total, breaking this module's one-rounding-convention claim.
        """
        st, led = seated(), Ledger()
        lk, c = {"S1": 90.0}, empty_counters()
        step_session(session="d1", state=st, bars=[], pending=[], ledger=led,
                     last_known=lk, cfg=CFG, strategy_id=SID,
                     strategy_version=VER,
                     security_bars=tradeability_only_bars([], None),
                     terminal_terms=[terms()], settlement_counters=c)
        conv = TerminalTerms(
            session="d2", security_id="S1", kind=TerminalKind.CONVERSION,
            delivered_security_id="S2", delivered_ticker="T2",
            delivered_issuer_id="I2", exchange_ratio=1.435,
            cash_in_lieu_price_per_delivered_share=140.0,
            reference="test/converted")
        res = step_session(session="d2", state=st, bars=[], pending=[],
                           ledger=led, last_known=lk, cfg=CFG, strategy_id=SID,
                           strategy_version=VER,
                           security_bars=tradeability_only_bars([], None),
                           terminal_terms=[conv], settlement_counters=c)
        a, = [r["terminal_audit"] for r in res.terminal_results
              if r.get("terminal_audit")]

        assert a["settlement_kind"] == "non_cash"
        assert a["episode_continues"] is True
        assert a["delivered_security_id"] == "S2"
        assert a["shares_delivered"] == 14      # floor(10 * 1.435)
        assert a["notional_delta"] is None, (
            "a conversion differenced against its carry would report a total "
            "loss of the carried value — a fabricated write-off")
        assert a["cash_in_lieu"] == pytest.approx(49.0)
        assert a["cash_in_lieu"] == round(a["cash_in_lieu"], 2), (
            "money reached the audit without passing through the module's "
            "single rounding convention")

        rec = reconcile([a])
        assert rec["unreconciled_episodes"] == []
        assert rec["non_cash_cash_legs"] == round(rec["non_cash_cash_legs"], 2)
        # The episode is still HELD, under the delivered identity.
        assert 0 in st.episodes and st.episodes[0].security_id == "S2"

    def test_the_kind_is_read_from_the_ACTION_not_guessed_from_the_price(self):
        """A CASH_MERGER with unreadable terms settles at a cash PROXY and is
        still `cash`; a CONVERSION has no cash price because it was paid in
        shares. Both lack exact terms, and only the action type separates
        them — inferring from the price alone would collapse the two."""
        from stock_strategy_shared.wealth_core.terminal_audit import (
            settlement_kind_for)
        assert settlement_kind_for("CASH_MERGER", 92.0) == "cash"
        assert settlement_kind_for("CONVERSION", None) == "non_cash"
        assert settlement_kind_for("CASH_PLUS_STOCK", 5.0) == "mixed"
        assert settlement_kind_for("WRITE_OFF", None) == "zero"
        assert settlement_kind_for(None, 0.0) == "zero"      # C2 orphan


class TestTheSETTLEMENT_MethodDominatesTheAnnouncedAction:
    """Found in the 2021-2023 rehearsal output, 2026-08-09.

    All eight terminal episodes settled via LAST_TRUSTWORTHY_MARK — a cash
    proxy — but five had been ANNOUNCED as conversions. Typing off `event_kind`
    filed those five as `non_cash`, which bucketed them OUT of the cash
    reconciliation. `reconcile` then reported:

        residual              0.00
        unreconciled_episodes []

    while covering 3 of 8 episodes and $132,057 of $342,137. Every green light
    on, and 61% of the money outside the check.

    That is the exact failure `unreconciled_episodes` exists to prevent,
    arriving through the CLASSIFIER rather than through a missing field. An
    episode is hardest to notice when it has been confidently filed in the wrong
    place rather than left out.

    An ANNOUNCEMENT says what was intended; only the SETTLEMENT says what
    happened. A documented conversion whose terms were never readable settles at
    a cash proxy exactly like any other unreadable termination — and only
    EXACT_TERMS can deliver shares, because nothing else states a ratio.
    """

    def test_a_CONVERSION_settled_at_a_PROXY_is_cash(self):
        from stock_strategy_shared.wealth_core.terminal_audit import (
            settlement_kind_for)
        assert settlement_kind_for("CONVERSION", 92.0,
                                   "LAST_TRUSTWORTHY_MARK") == "cash"
        assert settlement_kind_for("CONVERSION", 92.0,
                                   "EXECUTABLE_PRINT") == "cash"

    def test_a_CONVERSION_on_EXACT_TERMS_is_still_non_cash(self):
        from stock_strategy_shared.wealth_core.terminal_audit import (
            settlement_kind_for)
        assert settlement_kind_for("CONVERSION", None,
                                   "EXACT_TERMS") == "non_cash"
        assert settlement_kind_for("CASH_PLUS_STOCK", 5.0,
                                   "EXACT_TERMS") == "mixed"

    def test_a_proxy_settling_at_ZERO_is_still_zero(self):
        from stock_strategy_shared.wealth_core.terminal_audit import (
            settlement_kind_for)
        assert settlement_kind_for("CONVERSION", 0.0,
                                   "LAST_TRUSTWORTHY_MARK") == "zero"
        assert settlement_kind_for(None, 0.0, "ZERO_ORPHAN") == "zero"

    def test_the_REHEARSAL_population_reconciles_in_ONE_bucket(self):
        """The rehearsal's shape, reconstructed: eight episodes, all settled at
        the last trustworthy mark, five announced as conversions. Every one must
        land in the cash bucket, and the deltas must sum to the reported
        difference rather than to a fraction of it."""
        audits = []
        for i in range(8):
            audits.append(episode_audit(
                security_id=f"P:{i}", ticker=f"T{i}", event_session="d1",
                event_kind=("CONVERSION" if i < 5 else "CASH_MERGER"),
                carry={"carry_session": "d1", "shares_at_carry": 100,
                       "carry_price": 90.0},
                settlement_session="q9",
                settlement_method="LAST_TRUSTWORTHY_MARK",
                shares_at_settlement=100, settlement_price=91.0))
        rec = reconcile(audits)
        assert rec["cash_settled_episodes"] == 8, (
            "episodes announced as conversions but settled at a cash proxy were "
            "bucketed out of the reconciliation")
        assert rec["non_cash_episodes"] == 0
        assert rec["cash_coverage_fraction"] == 1.0
        assert rec["notional_delta_total"] == pytest.approx(8 * 100 * 1.0)
        assert rec["residual"] == pytest.approx(0.0)

    def test_reconcile_REPORTS_how_much_it_actually_covered(self):
        """`residual: 0.00` is a claim about whatever ended up in the cash
        bucket. Without a coverage figure it is a statement about an unstated
        subset, which is how a reconciliation covering 3 of 8 episodes read as
        complete."""
        cashy = episode_audit(
            security_id="A", ticker="A", event_session="d1",
            event_kind="CASH_MERGER",
            carry={"shares_at_carry": 10, "carry_price": 90.0},
            settlement_session="q", settlement_method="LAST_TRUSTWORTHY_MARK",
            shares_at_settlement=10, settlement_price=91.0)
        conv = episode_audit(
            security_id="B", ticker="B", event_session="d1",
            event_kind="CONVERSION",
            carry={"shares_at_carry": 10, "carry_price": 90.0},
            settlement_session="q", settlement_method="EXACT_TERMS",
            shares_at_settlement=10, settlement_price=None,
            delivered_security_id="C", shares_delivered=14,
            episode_continues=True)
        rec = reconcile([cashy, conv])
        assert rec["cash_coverage_fraction"] == 0.5
        assert rec["carried_notional_all_kinds"] == pytest.approx(1800.0)
        assert rec["carried_notional_total"] == pytest.approx(900.0), (
            "the cash total must remain the CASH total; the all-kinds figure is "
            "what shows the reader the difference")
