"""The ACTIONS -> terminal-event mapping, pinned against the canonical one.

Every rule here was a defect found the hard way, so the tests are named after
what each one cost. The pin is the important one: this is a faithful port, and a
port that drifts is worse than no port — it agrees on the easy rows and diverges
on exactly the ones that were hard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))

from sentinel.core import terminal as T  # noqa: E402
from stock_strategy_shared.wealth_core.terminal import TerminalKind  # noqa: E402

S = "2024-06-03"


def row(**kw):
    base = {"ticker": "AAA", "action": "delisted", "value": None,
            "contraticker": None, "contraname": None}
    base.update(kw)
    return base


class TestTheRulesAndWhatTheyCost:
    def test_a_terminal_action_with_NO_TERMS_blocks_rather_than_writing_off(self):
        """Mapping `delisted` to a write-off fabricates a total loss. Every
        admission is 4% of EQUITY, so an invented zero permanently shrinks every
        position opened afterwards — while the run stays plausible throughout."""
        t = T.terminal_from_action(row(), S, security_id="P1")
        assert t.kind is TerminalKind.CASH_MERGER
        assert t.cash_per_share is None, "a zero here would be an invented term"

    def test_value_is_a_DEAL_SIZE_and_never_reaches_a_ratio_or_price(self):
        """Read as an exchange ratio, a TMHC holder would have been delivered
        6,768.8 shares per share."""
        t = T.terminal_from_action(
            row(action="acquisitionby", value=6768.8, contraticker="BRK.A"),
            S, security_id="P1")
        assert t.exchange_ratio is None
        assert t.cash_per_share is None
        assert "6768.8" in t.reference, "the deal value belongs in provenance"

    def test_NA_is_a_SENTINEL_not_a_counterparty(self):
        """`or None` passes 'N/A' through as truthy. Every terminal row then took
        the security-for-security branch and blocked — all 19,216 of them."""
        assert T.vendor_symbol("N/A") is None
        t = T.terminal_from_action(row(contraticker="N/A"), S, security_id="P1")
        assert t.kind is TerminalKind.CASH_MERGER, "'N/A' must not name a security"
        assert t.delivered_ticker is None

    @pytest.mark.parametrize("sentinel", ["N/A", "NA", "NONE", "NULL", "-", "--",
                                          "", "   ", None])
    def test_every_absence_spelling_is_absence(self, sentinel):
        assert T.vendor_symbol(sentinel) is None

    def test_an_UNATTRIBUTABLE_action_is_not_emitted_at_all(self):
        """Applying a terminal event to a security nobody can name is worse than
        missing one: terms carrying a ticker match no holding, so it would
        silently return NOT_HELD."""
        assert T.terminal_from_action(row(), S, security_id=None) is None

    def test_a_PUBLIC_buyer_does_not_prove_delivered_consideration(self):
        t = T.terminal_from_action(row(action="mergerto", contraticker="XYZ"),
                                   S, security_id="P1")
        assert t.kind is TerminalKind.CASH_MERGER
        assert t.delivered_ticker is None
        assert t.exchange_ratio is None
        assert "counterparty_ticker=XYZ" in t.reference

    def test_the_ACQUIRER_side_is_NOT_terminal_for_this_security(self):
        """A false termination destroys a live holding."""
        for action in ("acquisitionof", "mergerfrom"):
            assert T.terminal_from_action(row(action=action), S,
                                          security_id="P1") is None

    def test_an_UNKNOWN_action_is_non_terminal(self):
        """The safe direction: a missed termination blocks and is visible."""
        assert T.terminal_from_action(row(action="somethingnew"), S,
                                      security_id="P1") is None

    @pytest.mark.parametrize("action", sorted(T.TERMINAL_ACTIONS))
    def test_every_TARGET_side_action_terminates(self, action):
        assert T.terminal_from_action(row(action=action), S,
                                      security_id="P1") is not None
