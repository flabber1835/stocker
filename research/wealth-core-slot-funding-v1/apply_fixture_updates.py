#!/usr/bin/env python3
"""Update tests whose fixtures encoded the superseded cash-less reservation.

These changes do not relax the corrected kernel.  They either make a manually
constructed pending BUY carry the cash reservation that a real decision would
have created, or move reservation-restart coverage out of a golden-path episode
that the corrected economics intentionally no longer admits.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text()
    if new in text:
        return
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{path}: expected exactly one anchor, found {n}")
    p.write_text(text.replace(old, new, 1))


# A manually manufactured pending BUY must now include the cash claim that a
# real decision would have reserved.  These corporate-action tests are about
# transformation semantics; 100 is their synthetic decision price.
replace_once(
    "tests/wealth_core/test_pending_corporate_actions.py",
    '    state.reserve_slot(0, "OLD", "OLD", "I:OLD")\n',
    '    state.reserve_slot(0, "OLD", "OLD", "I:OLD",\n'
    '                       float(shares) * 100.0 * 1.001)\n',
)

# The second nested-restore case is intended to isolate occupied+reserved
# conflict.  Supply a valid positive budget so the new, earlier invariant does
# not correctly stop the fixture for a different reason.
replace_once(
    "tests/wealth_core/test_restore_nested_economic_invariants.py",
    '        "reserved_issuer": "ISS-B",\n'
    '    })\n'
    '    with pytest.raises(ValueError, match="occupied and reserved"):\n',
    '        "reserved_issuer": "ISS-B",\n'
    '        "reserved_cash": 100.0,\n'
    '    })\n'
    '    with pytest.raises(ValueError, match="occupied and reserved"):\n',
)

# The old golden path had an underfunded SEC_BUST order sitting pending across
# HALTED_UNTRADEABLE.  That is exactly the behavior being corrected, so the
# reservation-specific cuts are no longer valid golden-path discriminators.
# Keep the rest of the restart matrix intact and cover funded reservation
# persistence in the dedicated slot-funding fixture below.
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    '    "reserved_but_unfilled_entry": HALTED_UNTRADEABLE.start + 1,\n'
    '    "reserved_across_many_dead_sessions": HALTED_UNTRADEABLE.start + 6,\n',
    '',
)
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    '''    def test_a_slot_is_reserved_by_an_unfilled_entry(self, g):
        r, _ = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert r.state.reserved_security_ids()

    def test_the_reservation_has_survived_many_dead_sessions(self, g):
        r, pend = self.state_at(g, CUTS["reserved_across_many_dead_sessions"])
        assert r.state.reserved_security_ids()
        assert max(p.sessions_waiting for p in pend) >= 4

''',
    '',
)
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    '''    def test_an_entry_order_is_queued(self, g):
        _, pend = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert any(p.operation.value == "OPEN_SLOT_POSITION" for p in pend)

''',
    '',
)
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    '        ("corrupt_reservations", 169, "decision", False),\n',
    '',
)
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    '        ("corrupt_cooldowns", CUTS["cooldown_boundary"], "decision", True),\n',
    '        # Corrected funding changes the later admission path; losing the\n'
    '        # cooldown still changes a decision but the final state reconverges.\n'
    '        ("corrupt_cooldowns", CUTS["cooldown_boundary"], "decision", False),\n',
)

old_absorbed = '''    def test_the_absorbed_corruptions_really_are_absorbed_downstream(self, g, whole):
        """The two `state_moves=False` rows say a LATER safeguard swallows the
        damage. That is a claim about a specific mechanism, so it is asserted
        rather than left as a comment on a False.

        Dropping the reservations must produce a SECOND, duplicate order for the
        already-reserved security, and the fill-time affordability rule must be
        what cancels it. If the duplicate stopped being emitted, the control
        above would still pass at `decision` for some other reason and the
        reservation would look load-bearing when it was not.
        """
        cut = 169
        clean = resumed(g, cut)[1]
        damaged = resumed(g, cut, corrupt=self.corrupt_reservations)[1]

        def orders_for(run, sec):
            return [o for s in run.sessions if s.decision
                    for o in s.decision.to_dict()["operations"]
                    if o["operation"] == "OPEN_SLOT_POSITION"
                    and o["security_id"] == sec]

        reserved = "SEC_BUST"          # the security holding the reservation
        assert not orders_for(clean, reserved), (
            "the clean resumption must NOT re-order the reserved security — "
            "that is what the reservation is for")
        assert orders_for(damaged, reserved), (
            "dropping the reservation must re-admit it; without the duplicate "
            "there is nothing for the reservation to have prevented")

        cancels = [c for s in damaged.sessions for c in s.cancelled
                   if c["security_id"] == reserved]
        assert any(c["reason"] == "UNAFFORDABLE_AT_OPEN" for c in cancels), (
            "the duplicate must be stopped by the fill-time affordability rule; "
            "if it fills, the book doubles a position and the terminal state "
            "WOULD move — in which case this row's state_moves is wrong")

'''
replace_once(
    "tests/wealth_core/test_restart_matrix.py",
    old_absorbed,
    '''    # Reservation restart/corruption coverage moved to test_slot_funding.py.
    # The old SEC_BUST golden-path reservation was itself an underfunded entry
    # and therefore correctly disappears under the fixed economic contract.

''',
)

# Add a dedicated, properly funded restart scenario.  This proves both halves:
# a valid cash claim survives bytes/restart, and losing the claim is rejected
# rather than silently allowing the pending order to borrow from account cash.
slot_test = ROOT / "tests/wealth_core/test_slot_funding.py"
text = slot_test.read_text()
marker = "def test_gap_beyond_reserved_budget_cancels_even_when_account_has_cash():\n"
if "test_restart_mid_pending_entry_preserves_the_reserved_budget" not in text:
    addition = r'''

def test_restart_mid_pending_entry_preserves_the_reserved_budget():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    ledger = Ledger()
    last_known = {}

    # The first executable opportunity is absent, so both claims must remain.
    step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=None, mark=101.0,
                    signal=226.0, tradeable=False)],
        pending=pending, ledger=ledger, last_known=last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    assert len(pending) == 1
    budget = st.slots[0].reserved_cash
    assert budget > 0

    restored = PortfolioState.from_dict(deepcopy(st.to_dict()))
    restored_pending = [type(p).from_dict(deepcopy(p.to_dict())) for p in pending]
    restored_ledger = Ledger.from_dict(deepcopy(ledger.to_dict()))
    restored_last_known = deepcopy(last_known)
    assert restored.slots[0].reserved_cash == pytest.approx(budget)

    next_bar = [daily("S1", "d2", open_=105.0, mark=105.0, signal=226.0)]
    clean = step_session(
        session="d2", state=st, bars=next_bar, pending=pending,
        ledger=ledger, last_known=last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    restarted = step_session(
        session="d2", state=restored, bars=next_bar,
        pending=restored_pending, ledger=restored_ledger,
        last_known=restored_last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])

    assert clean.fills == restarted.fills
    assert st.to_dict() == restored.to_dict()
    assert ledger.to_dict() == restored_ledger.to_dict()
    assert pending == restored_pending == []


def test_pending_open_without_its_cash_claim_is_cancelled_fail_closed():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    # Simulate queue/state corruption at a cross-process boundary.  The order
    # must not be allowed to reach into otherwise free account cash.
    st.slots[0].release_reservation()
    result = step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=100.0, mark=100.0, signal=226.0)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    assert not result.fills
    assert pending == []
    rows = [r for r in result.cancelled
            if r["reason"] == "MISSING_CASH_RESERVATION"]
    assert rows and rows[0]["reservation_released"] is False


'''
    if marker not in text:
        raise RuntimeError("test_slot_funding.py: insertion marker not found")
    slot_test.write_text(text.replace(marker, addition + marker, 1))

print("updated fixtures for explicit funded reservations")
