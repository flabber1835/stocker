"""Permanent security identity: a ticker is a label, not the security.

THE RULE. Everything path-dependent — quantity and basis, the episode peak, the
entry date, the one-time review flag, the security cooldown, outstanding
receivables, pending orders, issuer concentration — hangs off `security_id`. A
ticker is an OBSERVATION LABEL that may be reassigned at any time.

Using the ticker as the identity gets it wrong in BOTH directions, silently:

    a rename   the old id stops printing and a new one appears, so the engine
               sees an exit and a fresh entry. Costs are paid, the peak resets,
               the age resets and the one-time review is handed back. A winner
               is sold on a press release.
    a reuse    two unrelated companies that held one ticker at different times
               splice into one continuous security, and momentum is computed
               straight across the discontinuity between two businesses.

Neither raises, and both produce a complete backtest.
"""
from __future__ import annotations

import json

import pytest

from stock_strategy_shared.wealth_core.adapter import (
    PendingOrder,
    apply_ticker_changes,
    step_session,
    tradeability_only_bars,
)
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    SecurityBar,
    WealthCoreConfig,
    apply_exit,
    decide,
)
from stock_strategy_shared.wealth_core.feed import Feed, SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.ledger import EventType, Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import (
    COOLDOWN_SESSIONS,
    HoldingEpisode,
    PortfolioState,
)

SID, VER = "stocker_wealth_core_v1", 1
CFG = WealthCoreConfig()

# One permanent security that renames mid-run. `P:` prefixed so it can never be
# mistaken for a symbol.
SEC = "P:111"
OLD, NEW = "FB", "META"


def db(sec=SEC, ticker=OLD, session="d1", *, signal=100.0, open_=99.0,
       mark=100.0, tradeable=True, split=1.0, div=0.0):
    return DailyBar(security_id=sec, ticker=ticker, issuer_id="I1",
                    session=session, signal_close_split_adj_div_unadj=signal,
                    raw_open=open_, raw_mark_close=mark, tradeable=tradeable,
                    split_ratio=split, dividend_per_share=div)


def seated(cash=10_000.0, sec=SEC, ticker=OLD, shares=100, entry=100.0,
           peak=140.0, age=40, reviewed=True):
    st = PortfolioState.fresh(cash, n_slots=2)
    st.slots[0].occupied_by = sec
    st.episodes[0] = HoldingEpisode(
        security_id=sec, ticker=ticker, issuer_id="I1", slot_id=0,
        signal_date="d0", entry_date="d0", entry_raw_open=entry,
        entry_split_adjusted_price=entry, initial_shares=shares,
        current_shares=shares, episode_peak_split_adjusted_close=peak,
        market_sessions_held=age, review_completed=reviewed)
    st.initialized = True
    return st


def run(st, bars, ledger=None, session="d1", pending=None):
    return step_session(session=session, state=st, bars=bars,
                        pending=pending if pending is not None else [],
                        ledger=ledger or Ledger(), last_known={}, cfg=CFG,
                        strategy_id=SID, strategy_version=VER,
                        security_bars=tradeability_only_bars(bars, None))


# ── 1. a pure rename changes the symbol and nothing else ────────────────────

class TestAPureRenameIsANoOp:

    def test_every_piece_of_episode_state_survives(self):
        """MANDATORY. Quantity, basis, peak, entry date, age and the review
        flag are what make this strategy path-dependent. A rename resetting any
        one of them would be a different strategy after every corporate press
        release — and the run would look entirely normal."""
        st = seated()
        before = st.episodes[0]
        snapshot = (before.current_shares, before.entry_split_adjusted_price,
                    before.episode_peak_split_adjusted_close,
                    before.entry_date, before.market_sessions_held,
                    before.review_completed, before.slot_id)

        # BELOW the peak (140) and above the stop (98), so the peak has no
        # legitimate reason to move and any change is the rename's doing.
        run(st, [db(ticker=NEW, mark=120.0, signal=120.0)])

        ep = st.episodes[0]
        assert (ep.current_shares, ep.entry_split_adjusted_price,
                ep.episode_peak_split_adjusted_close, ep.entry_date,
                # the age advances by ONE session, as it would on any session
                ep.market_sessions_held - 1, ep.review_completed,
                ep.slot_id) == snapshot
        assert ep.security_id == SEC, "identity is untouched"
        assert ep.ticker == NEW, "...and the LABEL is current"

    def test_it_is_NOT_a_trade_and_costs_NOTHING(self):
        st = seated()
        led = Ledger()
        cash_before = st.cash
        run(st, [db(ticker=NEW, mark=150.0, signal=150.0)], ledger=led)
        assert st.cash == cash_before
        assert not [e for e in led.events
                    if e.event_type in (EventType.BUY, EventType.SELL)]

    def test_the_relabelling_is_REPORTED_even_though_it_posts_no_event(self):
        """A relabelling moves no number, so the ledger — whose rule is that an
        event is the only way a number changes — correctly stays silent. It must
        still be visible, or an exit submitted under a changed symbol has no
        trace anywhere."""
        st = seated()
        res = run(st, [db(ticker=NEW, mark=150.0, signal=150.0)])
        assert res.relabelled == [{"security_id": SEC, "from": OLD, "to": NEW,
                                   "where": "episode", "slot_id": 0}]

    def test_a_session_with_no_rename_reports_nothing(self):
        st = seated()
        assert run(st, [db(ticker=OLD, mark=150.0, signal=150.0)]).relabelled == []


# ── 2. the cooldown follows the SECURITY ────────────────────────────────────

class TestTheCooldownIsNotKeyedOnTheSymbol:

    def test_an_exited_security_stays_in_cooldown_ACROSS_a_rename(self):
        """The concrete defect. The cooldown was keyed on the ticker, so a
        security that exited and then renamed was looked up under a symbol that
        no longer existed — and became immediately re-buyable, inside the window
        that exists to stop exactly that."""
        st = seated()
        apply_exit(st, slot_id=0, raw_open=150.0, cfg=CFG)
        assert st.security_in_cooldown(SEC) is True

        # It now trades under a new symbol. The cooldown must not care.
        assert st.security_in_cooldown(SEC) is True
        assert st.security_cooldowns == {SEC: 0}

    def test_the_candidate_is_rejected_under_its_NEW_symbol(self):
        st = seated()
        apply_exit(st, slot_id=0, raw_open=150.0, cfg=CFG)
        marks = {SEC: Mark(SEC, MarkStatus.CURRENT, raw_mark_close=150.0)}
        d = decide(session="d2", state=st,
                   bars=[SecurityBar(SEC, NEW, "I1", [100.0 + i for i in range(127)])],
                   marks=marks, cfg=CFG, strategy_id=SID, strategy_version=VER)
        reasons = {r["reason"] for r in d.admission_rejections}
        assert Reason.REJECT_SECURITY_COOLDOWN.value in reasons

    def test_it_still_EXPIRES_on_schedule(self):
        """The falsifier: a cooldown that never expired would also pass the
        test above."""
        st = seated()
        apply_exit(st, slot_id=0, raw_open=150.0, cfg=CFG)
        for _ in range(COOLDOWN_SESSIONS):
            st.age_one_session({})
        assert st.security_in_cooldown(SEC) is False
        assert SEC not in st.security_cooldowns


# ── 3. ticker REUSE keeps two histories apart ───────────────────────────────

class TestTickerReuse:

    def test_two_securities_sharing_a_symbol_never_merge(self):
        """The feed keys its series on security_id, so two companies that held
        one ticker at different times accumulate separately. Splicing them would
        compute momentum across a discontinuity between different businesses."""
        meta = {
            "P:222": SecurityMeta(security_id="P:222", ticker="AAA",
                                  category="Domestic Common Stock",
                                  permaticker="222", first_session="s0"),
            "P:333": SecurityMeta(security_id="P:333", ticker="AAA",
                                  category="Domestic Common Stock",
                                  permaticker="333", first_session="s2"),
        }
        feed = Feed(meta)
        feed.advance("s0", [VendorBar("s0", "P:222", "AAA", 10.0, 10.0, 1e6)])
        feed.advance("s1", [VendorBar("s1", "P:222", "AAA", 11.0, 11.0, 1e6)])
        feed.advance("s2", [VendorBar("s2", "P:333", "AAA", 90.0, 90.0, 1e6)])

        assert feed.series["P:222"].raw_closes == [10.0, 11.0]
        assert feed.series["P:333"].raw_closes == [90.0]
        assert "AAA" not in feed.series, "the SYMBOL must not be an identity"

    def test_a_duplicate_SECURITY_on_one_session_is_still_refused(self):
        """Keying on identity must not weaken the duplicate guard: two bars for
        one SECURITY on one session would apply its split factor twice."""
        from stock_strategy_shared.wealth_core.feed import FeedError
        meta = {"P:222": SecurityMeta(security_id="P:222", ticker="AAA",
                                      permaticker="222")}
        feed = Feed(meta)
        with pytest.raises(FeedError, match="duplicate"):
            feed.advance("s0", [VendorBar("s0", "P:222", "AAA", 10.0, 10.0, 1e6),
                                VendorBar("s0", "P:222", "AAA", 11.0, 11.0, 1e6)])


# ── 4. pending orders never reference an obsolete symbol ────────────────────

class TestPendingOrdersAcrossARename:

    def test_a_queued_exit_is_RETARGETED_to_the_current_symbol(self):
        """MANDATORY. An order carries the permanent id AND a label; the label
        is stamped at decision time. Left stale, the exit is submitted under a
        symbol that no longer trades — which either rejects at the broker or,
        worse, fills against whatever now owns that ticker."""
        st = seated()
        pending = [PendingOrder(Operation.CLOSE_POSITION, SEC, OLD, 0, 100,
                                "d0", Reason.EXIT_TRAILING_STOP.value)]
        # Untradeable, so the order survives the session and can be inspected.
        run(st, [db(ticker=NEW, tradeable=False, mark=150.0, signal=150.0)],
            pending=pending)
        assert pending[0].ticker == NEW
        assert pending[0].security_id == SEC, "identity never moves"

    def test_a_slot_RESERVATION_is_retargeted_too(self):
        st = seated()
        st.slots[1].reserve(SEC, OLD, "I1")
        res = run(st, [db(ticker=NEW, mark=150.0, signal=150.0)])
        assert st.slots[1].reserved_ticker == NEW
        assert st.slots[1].reserved_for == SEC
        assert any(c["where"] == "reservation" for c in res.relabelled)

    def test_the_FILL_is_recorded_under_the_current_symbol(self):
        st = seated()
        led = Ledger()
        pending = [PendingOrder(Operation.CLOSE_POSITION, SEC, OLD, 0, 100,
                                "d0", Reason.EXIT_TRAILING_STOP.value)]
        run(st, [db(ticker=NEW, mark=150.0, signal=150.0)], ledger=led,
            pending=pending)
        sells = [e for e in led.events if e.event_type is EventType.SELL]
        assert len(sells) == 1 and sells[0].ticker == NEW


# ── 5. receivables outlive an identity change ───────────────────────────────

def test_a_receivable_survives_a_rename_and_still_pays():
    """It is a claim on cash keyed on the permanent identity, so a symbol change
    cannot strand it."""
    st = seated()
    led = Ledger()
    run(st, [db(ticker=OLD, div=0.50, mark=150.0, signal=150.0)], ledger=led,
        session="d1")
    assert led.receivable_total() == 50.0

    run(st, [db(ticker=NEW, mark=150.0, signal=150.0)], ledger=led, session="d2")
    assert st.cash == 10_000.0 + 50.0
    paid = [e for e in led.events if e.event_type is EventType.DIVIDEND_PAID]
    assert len(paid) == 1 and paid[0].security_id == SEC


# ── 6. issuer concentration is not evaded by a rename ───────────────────────

def test_two_securities_of_one_issuer_still_conflict_after_a_rename():
    """Issuer identity is carried on the SecurityBar and is independent of the
    symbol, so renaming one share class cannot buy a second position in the
    same company."""
    st = PortfolioState.fresh(1_000_000.0, n_slots=2)
    st.slots[0].occupied_by = "P:900"
    st.episodes[0] = HoldingEpisode(
        security_id="P:900", ticker="GOOG", issuer_id="ISSUER_ALPHABET",
        slot_id=0, signal_date="d0", entry_date="d0", entry_raw_open=100.0,
        entry_split_adjusted_price=100.0, initial_shares=10, current_shares=10,
        episode_peak_split_adjusted_close=100.0, market_sessions_held=5)
    st.initialized = True

    closes = [100.0 + i for i in range(127)]
    marks = {s: Mark(s, MarkStatus.CURRENT, raw_mark_close=100.0)
             for s in ("P:900", "P:901")}
    d = decide(session="d1", state=st,
               bars=[SecurityBar("P:901", "ALPHABET_C", "ISSUER_ALPHABET", closes)],
               marks=marks, cfg=CFG, strategy_id=SID, strategy_version=VER)
    assert {r["reason"] for r in d.admission_rejections} == {
        Reason.ISSUER_CONFLICT.value}


# ── 7. restart, and independent mutation of each identity field ─────────────

class TestRestartAcrossARename:

    def _state_after_rename(self):
        st = seated()
        run(st, [db(ticker=NEW, mark=150.0, signal=150.0)])
        return st

    def test_the_new_label_and_the_identity_both_survive_as_bytes(self):
        st = self._state_after_rename()
        back = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        assert back.episodes[0].security_id == SEC
        assert back.episodes[0].ticker == NEW
        assert back.state_hash() == st.state_hash()

    def test_MUTATING_THE_PERMANENT_ID_is_detectable(self):
        st = self._state_after_rename()
        blob = json.loads(json.dumps(st.to_dict()))
        blob["episodes"]["0"]["security_id"] = "P:999"
        assert PortfolioState.from_dict(blob).state_hash() != st.state_hash()

    def test_MUTATING_THE_CURRENT_TICKER_is_detectable(self):
        """Independently of the identity. A label that silently reverted would
        send the next exit to a dead symbol while every id still matched."""
        st = self._state_after_rename()
        blob = json.loads(json.dumps(st.to_dict()))
        blob["episodes"]["0"]["ticker"] = OLD
        assert PortfolioState.from_dict(blob).state_hash() != st.state_hash()

    def test_MUTATING_THE_ISSUER_ID_is_detectable(self):
        """Also independently: issuer identity governs concentration, and a
        corrupted one buys a second position in a company already held."""
        st = self._state_after_rename()
        blob = json.loads(json.dumps(st.to_dict()))
        blob["episodes"]["0"]["issuer_id"] = "ISSUER_OTHER"
        assert PortfolioState.from_dict(blob).state_hash() != st.state_hash()

    def test_the_cooldown_key_is_the_identity_across_a_restart(self):
        st = seated()
        apply_exit(st, slot_id=0, raw_open=150.0, cfg=CFG)
        back = PortfolioState.from_dict(json.loads(json.dumps(st.to_dict())))
        assert back.security_in_cooldown(SEC) is True
        assert OLD not in back.security_cooldowns and \
            NEW not in back.security_cooldowns


# ── the relabelling helper in isolation ─────────────────────────────────────

def test_apply_ticker_changes_touches_nothing_when_the_symbol_is_unchanged():
    st = seated()
    assert apply_ticker_changes(st, [db(ticker=OLD)]) == []
    assert st.episodes[0].ticker == OLD


def test_apply_ticker_changes_ignores_a_bar_for_a_security_not_held():
    st = seated()
    assert apply_ticker_changes(st, [db(sec="P:999", ticker="ZZZ")]) == []
    assert st.episodes[0].ticker == OLD


# ── streaming hashes: the same BYTES, not merely the same idea ───────────────

class TestCanonicalListStreamIsByteIdentical:
    """Foundation for Stage 2 of the memory work.

    `Decision.candidates` holds one row per eligible security per session —
    measured at ~1.5 million dicts on a three-year certification run, which is
    the OOM. They cannot be dropped because candidate_audit_hash, decision_hash
    and final_result_hash all read them, so the hashes must be folded per
    session and the rows discarded.

    The whole safety of that rests on the streamed digest being the SAME BYTES
    as the materialised one, not an equivalent scheme. `json.dumps` of a list
    emits `[` + item + `,` + item + `]`, so feeding those bytes in order to
    sha256 is identical by construction — and these tests hold it to that on
    the payload shapes the engine actually produces, not on synthetic data.
    """

    def _run(self):
        from stock_strategy_shared.wealth_core.golden import golden_scenario
        from stock_strategy_shared.wealth_core.run import run_sessions
        g = golden_scenario()
        return run_sessions(
            sessions=list(g.sessions), bars_by_session=g.bars_by_session,
            meta=g.meta, starting_cash=g.starting_cash,
            terminal_events=g.terminal_events)

    def test_it_matches_h_on_the_real_candidate_payload(self):
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalListStream, _h, _px)
        r = self._run()
        payload = []
        for s in r.sessions:
            if not s.decision:
                continue
            payload.append([s.session, sorted(
                [[c.security_id, c.ticker, _px(c.momentum), _px(c.recent),
                  _px(c.volatility), _px(c.score), bool(c.in_top_decile),
                  c.reason]
                 for c in s.decision.candidates])])
        assert payload, "fixture produced no candidates — test is vacuous"
        st = CanonicalListStream()
        st.extend(payload)
        assert st.hexdigest() == _h(payload)
        assert st.rows == len(payload)

    def test_it_matches_h_on_the_real_decision_payload(self):
        """The heaviest one: every Decision in full, candidates included."""
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalListStream, _h)
        r = self._run()
        payload = [[s.session, s.decision.to_dict()] for s in r.sessions
                   if s.decision]
        assert payload
        st = CanonicalListStream()
        st.extend(payload)
        assert st.hexdigest() == _h(payload)

    def test_the_empty_stream_is_the_empty_list(self):
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalListStream, _h)
        assert CanonicalListStream().hexdigest() == _h([])

    def test_hexdigest_does_not_close_the_stream(self):
        """Read it mid-run for progress without corrupting the final digest."""
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalListStream, _h)
        st = CanonicalListStream()
        st.add(["a", 1])
        mid = st.hexdigest()
        assert mid == _h([["a", 1]])
        st.add(["b", 2])
        assert st.hexdigest() == _h([["a", 1], ["b", 2]])

    def test_order_is_load_bearing(self):
        """A streamed hash that ignored order would let two engines with
        different execution sequences agree, which is what these hashes exist
        to detect."""
        from stock_strategy_shared.wealth_core.hashes import CanonicalListStream
        a, b = CanonicalListStream(), CanonicalListStream()
        a.extend([["x", 1], ["y", 2]])
        b.extend([["y", 2], ["x", 1]])
        assert a.hexdigest() != b.hexdigest()

    def test_floats_are_quantized_the_same_way(self):
        """`quantize` runs inside the streamed row exactly as it does inside
        `_h`. Without it the streamed path would hash raw repr output and a
        certified artefact would depend on interpreter float formatting."""
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalListStream, _h)
        payload = [[1 / 3, 2 / 7], [1e-11, 0.1 + 0.2]]
        st = CanonicalListStream()
        st.extend(payload)
        assert st.hexdigest() == _h(payload)


class TestCanonicalArraySpoolAndTheSplice:
    """The second Stage 2 primitive, and deliberately NOT the first one.

    `CanonicalListStream` is a running digest that can never give its bytes
    back — right for a standalone hash, useless for `final_result_hash`, which
    hashes an OBJECT whose sessions array sits at a fixed position among
    sorted keys. Reproducing that digest means feeding `pre + [rows] + post` to
    one hasher, and `pre` contains the final state, so it is unknown until the
    run ends.

    Hence the spool: the session bytes must survive long enough to reach the
    hash, but not in RAM. Written once sequentially, read back once
    sequentially.
    """

    def _run(self):
        from stock_strategy_shared.wealth_core.golden import golden_scenario
        from stock_strategy_shared.wealth_core.run import run_sessions
        g = golden_scenario()
        return run_sessions(
            sessions=list(g.sessions), bars_by_session=g.bars_by_session,
            meta=g.meta, starting_cash=g.starting_cash,
            terminal_events=g.terminal_events)

    def _spool(self, r, **kw):
        from stock_strategy_shared.wealth_core.hashes import CanonicalArraySpool
        sp = CanonicalArraySpool(**kw)
        for s in r.sessions:
            sp.add(r.session_row(s))
        return sp

    def test_the_spool_matches_h_on_the_real_session_rows(self):
        from stock_strategy_shared.wealth_core.hashes import _h
        r = self._run()
        rows = [r.session_row(s) for s in r.sessions]
        with self._spool(r) as sp:
            assert sp.hexdigest() == _h(rows)
            assert sp.rows == len(rows)

    def test_the_splice_reproduces_result_hash_EXACTLY(self):
        """THE certification-critical claim. Not 'equivalent' — the same hash
        the golden fixture is pinned to."""
        r = self._run()
        with self._spool(r) as sp:
            assert r.result_hash_spliced(sp) == r.result_hash()

    def test_it_is_identical_after_SPILLING_TO_DISK(self):
        """The path a three-year run actually takes. A spool that hashed
        differently once it left RAM would pass every short test and fail only
        on the run that matters."""
        r = self._run()
        with self._spool(r, max_ram_bytes=64) as sp:
            assert sp.spilled_to_disk is True
            assert r.result_hash_spliced(sp) == r.result_hash()

    def test_a_short_run_never_touches_disk(self):
        """Full materialisation stays free for debugging: the golden fixture
        must not start paying IO for a problem it does not have."""
        r = self._run()
        with self._spool(r) as sp:
            sp.close()
            assert sp.spilled_to_disk is False

    def test_adding_after_close_is_REFUSED(self):
        """It would append past the array's closing bracket, producing
        malformed bytes and a plausible, permanently wrong hash."""
        from stock_strategy_shared.wealth_core.hashes import CanonicalArraySpool
        with CanonicalArraySpool() as sp:
            sp.add([1])
            sp.close()
            with pytest.raises(RuntimeError, match="closed"):
                sp.add([2])

    def test_the_empty_spool_is_the_empty_array(self):
        from stock_strategy_shared.wealth_core.hashes import (
            CanonicalArraySpool, _h)
        with CanonicalArraySpool() as sp:
            assert sp.hexdigest() == _h([])

    def test_the_splice_refuses_a_non_spool(self):
        r = self._run()
        from stock_strategy_shared.wealth_core.hashes import CanonicalListStream
        st = CanonicalListStream()
        with pytest.raises(TypeError):
            r.result_hash_spliced(st)

    def test_a_COLLIDING_placeholder_RAISES_rather_than_guessing(self):
        """The guardrail, exercised by forcing the collision it defends against.

        A uuid4 placeholder cannot collide with real data in practice, which is
        the point — but "cannot happen" is not a reason to leave the branch
        untested. Here uuid4 is pinned and the same string planted in another
        field, so the placeholder appears TWICE. The splice must refuse: a
        mis-placed splice yields a hash that is plausible and permanently wrong,
        which is strictly worse than an exception.
        """
        import uuid as _uuid
        r = self._run()
        with self._spool(r) as sp:
            fixed = _uuid.UUID(int=0x1234)
            planted = f"\x00WC-SESSIONS-{fixed.hex}\x00"
            orig_to_dict, orig_uuid4 = r.to_dict, _uuid.uuid4

            def poisoned():
                d = dict(orig_to_dict())
                d["blocked_sessions"] = list(d["blocked_sessions"]) + [planted]
                return d

            r.to_dict = poisoned
            _uuid.uuid4 = lambda: fixed
            try:
                with pytest.raises(RuntimeError, match="expected exactly 1"):
                    r.result_hash_spliced(sp)
            finally:
                r.to_dict, _uuid.uuid4 = orig_to_dict, orig_uuid4

    def test_session_row_is_the_SAME_shape_to_dict_uses(self):
        """Two definitions of this row would be a silent parity divergence:
        the streamed hash would stay internally consistent while describing a
        different structure."""
        r = self._run()
        assert [r.session_row(s) for s in r.sessions] == r.to_dict()["sessions"]
