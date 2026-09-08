#!/usr/bin/env python3
"""Remove golden-path checks whose subject was the underfunded SEC_BUST order.

The corrected kernel intentionally prevents that order from being created.  The
reservation/restart invariant is now exercised by a dedicated, fully-funded
fixture in test_slot_funding.py instead of modifying the golden market path to
recreate the defect.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = ROOT / "tests/wealth_core/test_restart_matrix.py"
text = p.read_text()


def delete_once(old: str) -> None:
    global text
    if old not in text:
        return
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"expected exactly one obsolete block, found {n}")
    text = text.replace(old, "", 1)


delete_once(
    '    "reserved_but_unfilled_entry": HALTED_UNTRADEABLE.start + 1,\n'
    '    "reserved_across_many_dead_sessions": HALTED_UNTRADEABLE.start + 6,\n'
)

delete_once('''    def test_a_slot_is_reserved_by_an_unfilled_entry(self, g):
        r, _ = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert r.state.reserved_security_ids()

    def test_the_reservation_has_survived_many_dead_sessions(self, g):
        r, pend = self.state_at(g, CUTS["reserved_across_many_dead_sessions"])
        assert r.state.reserved_security_ids()
        assert max(p.sessions_waiting for p in pend) >= 4

''')

delete_once('''    def test_an_entry_order_is_queued(self, g):
        _, pend = self.state_at(g, CUTS["reserved_but_unfilled_entry"])
        assert any(p.operation.value == "OPEN_SLOT_POSITION" for p in pend)

''')

delete_once('        ("corrupt_reservations", 169, "decision", False),\n')

# A helper that mutates reservations may remain useful for future dedicated
# scenarios.  What must disappear is every assertion tied to the obsolete
# SEC_BUST reservation/cut.
for stale in (
    'CUTS["reserved_but_unfilled_entry"]',
    'CUTS["reserved_across_many_dead_sessions"]',
    '("corrupt_reservations", 169, "decision", False)',
):
    if stale in text:
        raise RuntimeError(f"obsolete golden reservation reference remains: {stale}")

p.write_text(text)
print("removed obsolete golden reservation checks")
