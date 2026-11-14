"""Fractional owned fills use the already-authenticated rational action terms."""
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from sentinel.execution import reconcile
from sentinel.execution.states import CommandState as S
from tests.sentinel.test_fractional_execution import dollars, NOW, AAA, projection
from tests.sentinel.test_fractional_flow import fractional_environment


def test_reverse_split_retains_exact_fractional_entitlement_without_rounding():
    event = reconcile.CorporateActionEvent(
        security_id=AAA.security_id, ticker=AAA.symbol, session=date(2026, 8, 13),
        action="split", value=D("0.03333333333333333"), contraticker=None,
        source_row_id="native-1-for-30", reason="authenticated scalar action",
        canonical_multiplier=D("0.03333333333333333"), canonical_numerator=1, canonical_denominator=30)
    actions = reconcile.CorpusActionLookup(date(2026, 8, 12),
        {AAA.security_id: ((event.session, event.canonical_multiplier),)}, scalar_events=(event,))
    purchase = replace(dollars(filled="0.9", state=S.FILLED), created_at=NOW)
    assert reconcile.expected_book_from_commands((purchase,), actions) == {AAA.security_id: D("0.03")}
    # Reading the same immutable evidence again cannot apply the event twice.
    assert reconcile.expected_book_from_commands((purchase,), actions) == {AAA.security_id: D("0.03")}


def test_rational_action_guard_falsifier(monkeypatch):
    from sentinel.execution import commands
    from tests.sentinel.test_order_terms_schema import _compiled
    monkeypatch.setattr(commands, "filled_share_units", _compiled(
        commands.filled_share_units, "if evidence:", "if False:"))
    with pytest.raises(AssertionError):
        test_reverse_split_retains_exact_fractional_entitlement_without_rounding()


def test_historical_whole_order_gets_exact_split_under_selected_fractional_policy(monkeypatch):
    from sentinel.execution.commands import filled_share_units
    from tests.sentinel.test_fractional_execution import cmd
    from types import SimpleNamespace
    from fractions import Fraction
    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", " FRACTIONAL_MARKET_DAY_V1 ")
    evidence = {"security_id": AAA.security_id, "source_row_id": "native-split",
                "action": "split", "value": "0.03333333333333333", "canonical_multiplier": "0.03333333333333333",
                "canonical_numerator": 1, "canonical_denominator": 30}
    action = SimpleNamespace(session=date(2026, 8, 13), to_dict=lambda: evidence)
    actions = SimpleNamespace(scalar_evidence_for=lambda ids: (action,))
    purchase = replace(cmd(qty="27", filled="27", state=S.FILLED), created_at=NOW)
    assert filled_share_units(purchase, actions=actions, multiplier=D(evidence["canonical_multiplier"])) == Fraction(9, 10)


def test_recovered_close_uses_exact_action_evidence(monkeypatch):
    from sentinel.execution import fractional_progress, feed_actions
    from sentinel.execution.target_reprojection import TargetProjectionRefused
    event = reconcile.CorporateActionEvent(
        security_id=AAA.security_id, ticker=AAA.symbol, session=date(2026, 8, 13),
        action="split", value=D("0.03333333333333333"), contraticker=None,
        source_row_id="native-1-for-30", reason="authenticated scalar action",
        canonical_multiplier=D("0.03333333333333333"), canonical_numerator=1, canonical_denominator=30)
    actions = reconcile.CorpusActionLookup(date(2026, 8, 12),
        {AAA.security_id: ((event.session, event.canonical_multiplier),)}, scalar_events=(event,))
    def lookup(conn, *, start, end):
        assert start == date(2026, 8, 12) and end == date(2026, 8, 13)
        return actions
    monkeypatch.setattr(feed_actions, "action_lookup", lookup)
    kwargs = dict(conn=None, projection=projection(), targets={AAA.security_id: D("0.9")},
        through=event.session, multipliers={AAA.security_id: event.canonical_multiplier})
    aged, evidence = fractional_progress.age_targets(**kwargs)
    assert aged == {AAA.security_id: D("0.03")} and evidence == [event.to_dict()]
    with pytest.raises(TargetProjectionRefused, match="authenticated history"):
        fractional_progress.age_targets(**{**kwargs, "multipliers": {AAA.security_id: D(2)}})


def test_close_rational_action_falsifier(monkeypatch):
    from sentinel.execution import fractional_progress
    from tests.sentinel.test_order_terms_schema import _compiled
    monkeypatch.setattr(fractional_progress, "age_targets", _compiled(fractional_progress.age_targets,
        "factor = share_action_factor(security_id=sid, multiplier=expected.get(sid, Decimal(1)), evidence=events)",
        "factor = Fraction(expected.get(sid, Decimal(1)))"))
    with pytest.raises(AssertionError):
        test_recovered_close_uses_exact_action_evidence(monkeypatch)
