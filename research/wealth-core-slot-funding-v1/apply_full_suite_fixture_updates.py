#!/usr/bin/env python3
"""Migrate remaining unit fixtures to explicit funded entry reservations.

These tests manufacture pending-entry state directly to exercise cooldown,
identity, dividend, issuer-rebinding, and restart behavior.  Under the corrected
kernel such state is only valid when it carries a positive cash claim.  The
golden restart case that depended specifically on the old underfunded SEC_BUST
order is retired; funded-entry restart coverage lives in test_slot_funding.py.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text()
    if new and new in text:
        return
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{path}: expected exactly one anchor, found {n}")
    p.write_text(text.replace(old, new, 1))


# Cooldown timing only needs every unrelated slot to stay unavailable.  An
# occupied sentinel does that without inventing a queued BUY or a fake cash
# reservation in a zero-cash fixture.
replace_once(
    "tests/wealth_core/test_cooldown_timing.py",
    '''    for slot_id, slot in state.slots.items():
        if slot_id != 5:
            slot.reserve(
                f"BLOCKED-{slot_id}",
                f"BLOCKED-{slot_id}",
                f"BLOCKED-ISSUER-{slot_id}",
            )
''',
    '''    for slot_id, slot in state.slots.items():
        if slot_id != 5:
            slot.occupied_by = f"BLOCKED-{slot_id}"
''',
)

# This dividend-ordering fixture manually queues a 10-share S2 entry.  Give the
# queue the decision-time budget it claims to have; 10 shares at the synthetic
# $100 decision price plus 10 bps = $1,001.
replace_once(
    "tests/wealth_core/test_dividends.py",
    '''        pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "S2", "T2", 1, 10,
                                "d0", Reason.ENTRY_DURABLE_RANK.value)]
        bars = [bar("S1", div=0.50), bar("S2", div=5.00)]
''',
    '''        pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "S2", "T2", 1, 10,
                                "d0", Reason.ENTRY_DURABLE_RANK.value)]
        st.reserve_slot(1, "S2", "T2", "I2", 1_001.0)
        bars = [bar("S1", div=0.50), bar("S2", div=5.00)]
''',
)

# A rename test constructs reservation state only to verify label retargeting.
replace_once(
    "tests/wealth_core/test_identity.py",
    '        st.slots[1].reserve(SEC, OLD, "I1")\n',
    '        st.slots[1].reserve(SEC, OLD, "I1", 100.0)\n',
)

# Issuer-rebinding fixtures all queue exactly 10 shares at a $10 synthetic open.
# $100.10 is therefore the exact cost-inclusive budget for the claimed order.
replace_once(
    "tests/wealth_core/test_issuer_rebinding.py",
    '    state.reserve_slot(slot, sec, sec, issuer)\n',
    '    state.reserve_slot(slot, sec, sec, issuer, 100.10)\n',
)

# The historical golden restart cut still straddles a real CLOSE order, so it
# remains a valid serialization/restart boundary.  Its old OPEN was the
# underfunded SEC_BUST reservation that this branch intentionally prevents.
replace_once(
    "tests/wealth_core/test_golden_fixture.py",
    '''        kinds = {p.operation.value for p in pending}
        assert "CLOSE_POSITION" in kinds, "no exit order straddles the boundary"
        assert "OPEN_SLOT_POSITION" in kinds, "no entry order straddles it"
        assert first.state.reserved_security_ids(), "no slot is reserved"
''',
    '''        kinds = {p.operation.value for p in pending}
        assert "CLOSE_POSITION" in kinds, "no exit order straddles the boundary"
        # The old OPEN here was an underfunded SEC_BUST admission and is
        # deliberately absent under the corrected economics.  Funded pending-
        # entry restart coverage lives in test_slot_funding.py.
''',
)

obsolete = '''    def test_dropping_the_reservation_across_the_restart_REORDERS_the_slot(self):
        """A mutation proof that the reservation is load-bearing.

        Without it the resumed run re-hands the reserved slot to the same
        candidate — the duplicate-orders defect, arriving by the restart route.

        THE ASSERTION IS ON THE ORDER STREAM, NOT THE TERMINAL STATE, and that
        is a correction rather than a weakening. This test used to compare the
        damaged run's final state hash against the one-shot run's, which no
        longer differs: the duplicate entry is emitted, reaches the open, finds
        the cash already spent by the original order, and is cancelled
        UNAFFORDABLE_AT_OPEN. The book converges because a SECOND safeguard
        catches what the reservation missed.

        Asserting on state would therefore report "the reservation is not
        load-bearing", which is false — it is doing its job one layer earlier.
        Asserting on the orders says what actually happens, and keeps saying it
        if the affordability rule is ever changed.
        """
        g = golden_scenario()
        clean = self._resume(g)
        damaged = self._resume(g, corrupt=self._drop_reservations)

        def entries(run, sec):
            return [o for s in run.sessions if s.decision
                    for o in s.decision.to_dict()["operations"]
                    if o["operation"] == "OPEN_SLOT_POSITION"
                    and o["security_id"] == sec]

        reserved = "SEC_BUST"
        assert not entries(clean, reserved), (
            "the intact reservation must stop the resumed run re-selecting the "
            "security whose entry is already queued")
        dupes = entries(damaged, reserved)
        assert dupes, "the corruption produced no duplicate — nothing is guarded"
        assert dupes[0]["slot_id"] == 0, "and it claims the very same slot"

        assert any(c["security_id"] == reserved
                   and c["reason"] == "UNAFFORDABLE_AT_OPEN"
                   for s in damaged.sessions for c in s.cancelled), (
            "the duplicate must be caught at the fill by the affordability "
            "rule; if it fills, the position doubles")

    @staticmethod
    def _drop_reservations(blob):
        for slot in blob["slots"].values():
            slot["reserved_for"] = None
            slot["reserved_ticker"] = None
            slot["reserved_issuer"] = None

'''
replace_once(
    "tests/wealth_core/test_golden_fixture.py",
    obsolete,
    '''    # The former SEC_BUST reservation mutation was a mutation of the
    # superseded underfunded-entry behavior.  The corrected cash-reservation
    # mutation/restart falsifiers are in test_slot_funding.py.

''',
)

print("migrated remaining fixtures to explicit funded reservations")
