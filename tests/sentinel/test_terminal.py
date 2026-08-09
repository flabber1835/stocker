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

CANONICAL = ROOT / "services" / "backtester" / "app" / "wealth_core_replay.py"
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

    def test_a_PUBLIC_acquirer_names_the_delivered_security(self):
        t = T.terminal_from_action(row(action="mergerto", contraticker="XYZ"),
                                   S, security_id="P1")
        assert t.kind is TerminalKind.CONVERSION
        assert t.delivered_ticker == "XYZ"
        assert t.exchange_ratio is None, "the ratio is not in the table"

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


class TestItHasNotDriftedFromTheCANONICAL:
    """A port that drifts agrees on the easy rows and diverges on the hard ones."""

    def _canonical(self):
        """Extract the canonical definitions by AST and exec them in isolation.

        NOT importlib: the backtester module pulls in sqlalchemy and a package
        context it does not have here, and the first version of this test SKIPPED
        on that — 11 silent skips on the guard whose entire job is to catch
        drift. A drift guard that can skip is not a guard.

        NOT a hand-built globals dict either: the version before that failed 11
        ways because the harness itself diverged. This takes the exact top-level
        definitions the function closes over, from the service's own source, and
        gives them the REAL shared types.
        """
        import ast
        import enum

        from stock_strategy_shared.wealth_core.terminal import (
            TerminalKind as _TK, TerminalTerms as _TT)

        src = CANONICAL.read_text()
        tree = ast.parse(src)
        wanted = {"ActionSide", "TERMINAL_ACTION_SIDES", "TERMINAL_ACTIONS",
                  "_VENDOR_SENTINELS", "vendor_symbol", "terminal_from_action"}
        picked = []
        for node in tree.body:
            name = getattr(node, "name", None)
            if name is None and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = ([node.target] if isinstance(node, ast.AnnAssign)
                           else node.targets)
                name = next((t.id for t in targets if isinstance(t, ast.Name)), None)
            if name in wanted:
                picked.append(node)
        missing = wanted - {getattr(n, "name", None) or
                            (n.targets[0].id if isinstance(n, ast.Assign)
                             else n.target.id) for n in picked}
        assert not missing, (
            f"the canonical source no longer defines {sorted(missing)} — the "
            f"port cannot be pinned against something that moved. Find where it "
            f"went before trusting sentinel/core/terminal.py.")

        ns = {"Enum": enum.Enum, "TerminalKind": _TK, "TerminalTerms": _TT,
              "Optional": __import__("typing").Optional, "__name__": "_canonical"}
        exec(compile(ast.Module(body=picked, type_ignores=[]),
                     str(CANONICAL), "exec"), ns)
        return ns["terminal_from_action"]

    @pytest.mark.parametrize("kw", [
        {},
        {"action": "acquisitionby", "value": 6768.8, "contraticker": "BRK.A"},
        {"action": "acquisitionby", "value": 9792.6, "contraticker": "N/A"},
        {"action": "mergerto", "contraticker": "XYZ"},
        {"action": "bankruptcyliquidation"},
        {"action": "regulatorydelisting", "value": 0.0},
        {"action": "voluntarydelisting", "value": 0.2},
        {"action": "acquisitionof"},
        {"action": "mergerfrom", "contraticker": "AAA"},
        {"action": "split"},
        {"value": 0.0, "contraticker": "--"},
    ])
    def test_same_verdict_as_the_backtester(self, kw):
        canonical = self._canonical()
        mine = T.terminal_from_action(row(**kw), S, security_id="P1")
        theirs = canonical(row(**kw), S, security_id="P1")
        if theirs is None or mine is None:
            assert mine is theirs is None
            return
        assert mine.kind == theirs.kind
        assert mine.cash_per_share == theirs.cash_per_share
        assert mine.exchange_ratio == theirs.exchange_ratio
        assert mine.delivered_ticker == theirs.delivered_ticker
        assert mine.reference == theirs.reference

    def test_the_action_vocabularies_MATCH(self):
        src = CANONICAL.read_text()
        for action in T.TERMINAL_ACTIONS:
            assert f'"{action}": ActionSide.TARGET' in src
        assert "acquisitionof" not in T.TERMINAL_ACTIONS
