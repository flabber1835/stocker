"""Keep the exact opening-stability executable as the market policy predecessor."""

from sentinel import runtime_admission as admission, url_selected_source_basis as basis


def test_reviewed_market_policy_source_keeps_the_exact_opening_stability_predecessor():
    profile = basis._profile()
    revision = "5a49fa1b0e658bbb59dccda4089bb3ec1aada0e3"
    assert basis.MARKET_BUY_PREDECESSOR_REVISION == revision
    prior = profile["retained_predecessors"][revision]["files"]
    assert admission.source_closure(prior) == "082bc5ae6789dea75a193b4c49ba51b3e1123b49505bec62344de151afa09544"
    assert profile["authority_effect"] == "NONE"

    installed = profile["retained_predecessors"][basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION]["files"]
    assert set(installed) - set(prior) == {
        "execution/market_buy_policy.py", "execution/market_buy_sizing.py",
    }
    assert set(prior) <= set(installed)
    assert {name for name in prior if prior[name] != installed[name]} == {
        "authority/validation.py",
        "automation/model.py",
        "automation_runtime.py",
        "dual_plan_authority.py",
        "execution/account_status.py",
        "execution/certification.py",
        "execution/executor.py",
        "execution/guarded.py",
        "execution/opening_sizing.py",
        "execution/protected_limits.py",
        "execution/recovery.py",
        "local_paper.py",
        "panel/model.py",
        "panel/overview.py",
        "panel/sources.py",
        "paper/execution.py",
        "paper/preparation.py",
        "paper/targets.py",
        "paper/validation.py",
        "url_selected_source_basis.py",
    }
    current = admission._source_files(basis.PROFILE.parent)
    assert basis.predecessor_view(current, previous=prior) == prior
    edited = {**current, "execution/market_buy_policy.py": "0" * 64}
    assert basis.predecessor_view(edited, previous=prior) is edited
