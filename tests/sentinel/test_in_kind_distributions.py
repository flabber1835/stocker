"""A spin-off's child value must never become a parent cash dividend."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel.core.spinoffs import SpinoffDistribution, SpinoffTermsRequired, require_supported_entitlements
from sentinel.feed.actions_map import dividends_from_actions
from sentinel.execution.reconcile import SAFE_NON_BOOK_ACTIONS
from test_production_state import _fresh, _advance, _published


def event(**kwargs):
    return SpinoffDistribution(
        session="2026-08-11", parent_ticker="ADP", parent_security_id="P:ADP",
        child_ticker="CDK", child_security_id="P:CDK", source_row_id="source-adp-cdk",
        value_evidence="10", **kwargs)


def test_adp_cdk_value_has_no_cash_authority_and_cash_distributions_remain_exact():
    from decimal import Decimal
    rows = [{"ticker": "ADP", "date": "2014-10-01", "action": "spinoffdividend", "value": "10"},
            {"ticker": "ADP", "date": "2014-10-01", "action": "dividend", "value": "0.1"},
            {"ticker": "ADP", "date": "2014-10-01", "action": "specialdividend", "value": "0.2"}]
    assert dividends_from_actions(rows, ["2014-10-01"]) == {("ADP", "2014-10-01"): Decimal("0.3")}
    assert "spinoffdividend" not in SAFE_NON_BOOK_ACTIONS


@pytest.mark.parametrize("distribution", [event(), event(child_shares_per_parent="1/3", child_price="30")])
def test_one_for_three_distribution_requires_reviewed_child_ownership(distribution):
    state = SimpleNamespace(wealth_core={"episodes": {"parent": {
        "security_id": "P:ADP", "ticker": "ADP", "current_shares": 300}}})
    original = deepcopy(state.wealth_core)
    with pytest.raises(SpinoffTermsRequired, match="CHILD_OWNERSHIP_REQUIRED"):
        require_supported_entitlements(state, [distribution])
    assert state.wealth_core == original


def test_canonical_kernel_checks_entitlement_before_any_accounting(monkeypatch):
    config, fresh = _fresh()
    prior = _advance(fresh, _published(), config)
    prior.wealth_core["episodes"]["parent"] = {
        "security_id": "P:ADP", "ticker": "ADP", "current_shares": 300}
    reached = []
    monkeypatch.setattr("sentinel.core.kernel.plan_session", lambda **_: reached.append(True))
    published = replace(_published("2026-08-11"), spinoff_distributions=(event(),))
    with pytest.raises(SpinoffTermsRequired):
        _advance(prior, published, config)
    assert not reached


def test_unheld_parent_has_no_entitlement():
    require_supported_entitlements(SimpleNamespace(wealth_core={"episodes": {}}), [event()])
