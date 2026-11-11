"""Configuration boundaries for the explicit backed PAPER market BUY policy."""
from decimal import Decimal as D, localcontext

import pytest

from sentinel import authority, local_paper
from sentinel.execution import market_buy_policy, protected_limits
from sentinel.execution.target_reprojection import TargetProjectionRefused


MARKET_ENV = {
    "ALPACA_BASE_URL": authority.PAPER_BASE_URL,
    "SENTINEL_PAPER_BUY_POLICY": market_buy_policy.MARKET_MODE,
    "SENTINEL_PAPER_BUY_CAP_BPS": "",
    "SENTINEL_PAPER_DEBUG_WINDOW": "",
    local_paper.MODE_ENV: local_paper.MODE,
    local_paper.ACCOUNT_ENV: "PATEST",
    local_paper.BACKUP_POLICY_ENV: local_paper.BACKUP_POLICY,
}


def test_market_policy_accepts_only_explicit_backed_owner_paper():
    market = market_buy_policy.MarketBuyPolicy.from_env(MARKET_ENV)
    assert market == market_buy_policy.MarketBuyPolicy()
    for selection in ("", protected_limits.PROTECTED_MODE):
        assert market_buy_policy.MarketBuyPolicy.from_env(
            dict(MARKET_ENV, SENTINEL_PAPER_BUY_POLICY=selection)) is None


@pytest.mark.parametrize("key,value,error", [
    ("ALPACA_BASE_URL", "https://api.alpaca.markets", "PAPER endpoint"),
    (local_paper.MODE_ENV, "", "backed owner PAPER"),
    (local_paper.BACKUP_POLICY_ENV, "", "backed owner PAPER"),
    (local_paper.ACCOUNT_ENV, "LIVEACCOUNT", "backed owner PAPER"),
    ("SENTINEL_PAPER_BUY_CAP_BPS", "0", "protected BUY cap"),
    ("SENTINEL_PAPER_DEBUG_WINDOW", "{}", "protected debug window"),
])
def test_market_policy_refuses_mismatched_scope_and_limit_inputs(key, value, error):
    with pytest.raises(TargetProjectionRefused, match=error):
        market_buy_policy.MarketBuyPolicy.from_env(dict(MARKET_ENV, **{key: value}))


def test_market_policy_decoding_requires_exact_typed_terms():
    policy = market_buy_policy.MarketBuyPolicy()
    assert policy.from_dict(policy.to_dict()) == policy
    with pytest.raises(TargetProjectionRefused, match="terms are unsupported"):
        policy.from_dict(dict(policy.to_dict(), max_unresolved_buys=True))


def test_market_cost_is_exact_independently_of_decimal_context():
    with localcontext() as context:
        context.prec = 4
        assert market_buy_policy.estimated_market_buy_cost(D(22), D("56.21")) == D("1249.9862")
    with pytest.raises(TargetProjectionRefused, match="positive whole shares"):
        market_buy_policy.estimated_market_buy_cost(D("0.5"), D("56.21"))


def test_market_identity_has_distinct_version_and_requires_actual_config(monkeypatch):
    for key, value in MARKET_ENV.items():
        monkeypatch.setenv(key, value)
    market = authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL)
    policy = market_buy_policy.MarketBuyPolicy()
    assert market["schema"] == "sentinel.paper-execution-config/3"
    assert market["market_buy_policy"] == policy.to_dict()
    assert market["market_buy_policy_sha256"] == policy.fingerprint()
    assert protected_limits.ProtectedLimitPolicy.from_env() is None
    market_hash = authority.canonical_sha256(market)
    local_paper.validate_execution_policy(market_hash)
    with pytest.raises(authority.AuthorityRefused, match="requires the Alpaca PAPER endpoint"):
        authority.execution_config_identity(paper_base_url="https://api.alpaca.markets")

    monkeypatch.setenv("SENTINEL_PAPER_BUY_POLICY", protected_limits.PROTECTED_MODE)
    monkeypatch.setenv("SENTINEL_PAPER_BUY_CAP_BPS", "100")
    protected = authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL)
    assert protected["schema"] == "sentinel.paper-execution-config/2"
    assert protected["protected_buy_policy"] == protected_limits.ProtectedLimitPolicy(100).to_dict()
    with pytest.raises(RuntimeError, match="differs from actual policy"):
        local_paper.validate_execution_policy(market_hash)
    local_paper.validate_execution_policy(authority.canonical_sha256(protected))

    monkeypatch.delenv("SENTINEL_PAPER_BUY_POLICY")
    monkeypatch.delenv("SENTINEL_PAPER_BUY_CAP_BPS")
    legacy = authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL)
    assert legacy["schema"] == "sentinel.paper-execution-config/1"
    assert set(legacy) == {"schema", "scope", "paper_base_url", "broker", "adapter", "trust_roots_sha256"}
    assert len({market_hash, authority.canonical_sha256(protected), authority.canonical_sha256(legacy)}) == 3


def test_market_selection_requires_a_different_automation_control_binding():
    from sentinel.automation.model import AutomationConfig
    from sentinel.automation_runtime import config_from_env

    legacy = config_from_env({})
    protected = config_from_env(dict(
        MARKET_ENV, SENTINEL_PAPER_BUY_POLICY=protected_limits.PROTECTED_MODE,
        SENTINEL_PAPER_BUY_CAP_BPS="100"))
    market = config_from_env(MARKET_ENV)
    assert legacy.fingerprint == protected.fingerprint == AutomationConfig().fingerprint
    assert "market_buy_policy_sha256" not in legacy.model_dump(exclude_none=True)
    assert market.market_buy_policy_sha256 == market_buy_policy.MarketBuyPolicy().fingerprint()
    assert market.fingerprint != legacy.fingerprint
