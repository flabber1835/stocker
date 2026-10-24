"""The local execution change has one exact, owner-authorized source pair."""
from copy import deepcopy
from types import SimpleNamespace
import inspect

import pytest

from sentinel import authority, persistent_share_authority as upgrade
from sentinel import standing_observation_authority as standing
from sentinel import local_paper
from sentinel.strategy import production_strategy


@pytest.fixture
def case(monkeypatch):
    strategy = production_strategy()[1]
    assert authority.canonical_sha256(strategy) == upgrade.PERSISTENT_SHARE_STRATEGY
    identity = dict(deployment_id="test", broker="alpaca", broker_account_id="PAexact", takeover_epoch=1,
        environment=authority.PAPER_SCOPE, paper_base_url=authority.PAPER_BASE_URL)
    bindings = dict(strategy_identity_sha256=upgrade.SIGNED_PREDECESSOR,
        publication_policy=dict(implementation_sha256="policy", chain_root_sha256="root"),
        current_corpus=dict(data_version=1), current_metadata_snapshot=dict(snapshot_date="2026-10-01"))
    certificate = SimpleNamespace(authorization_mode=authority.PAPER_OBSERVATION_ONLY,
        allows=lambda mode: mode is authority.RolloutMode.CONTROLLER,
        claims=dict(permitted_operations=["AUTOMATION"], bindings=bindings), subject=identity,
        rollout=dict(to_mode="CONTROLLER", to_version=9), certificate_sha256="certificate", unattended_automation=True)
    bound = SimpleNamespace(**{k: v for k, v in identity.items() if k not in {"environment", "paper_base_url"}})
    monkeypatch.setattr(standing, "load_active_signed_certificate", lambda *a, **k: certificate)
    monkeypatch.setattr(standing.binding_mod, "require", lambda c: bound)
    monkeypatch.setattr(standing, "load_rollout_state", lambda c: SimpleNamespace(mode=authority.RolloutMode.CONTROLLER,
        version=9, certificate_sha256="certificate"))
    monkeypatch.setattr(local_paper, "require_bound_account", lambda c: True)
    monkeypatch.setattr(local_paper, "require_runtime", lambda *a: None)
    monkeypatch.setattr(local_paper, "require_execution_config", lambda *a: None)
    from sentinel import observation_authority
    monkeypatch.setattr(observation_authority, "current_metadata_snapshot_identity",
        lambda c: dict(snapshot_date="2026-10-22"))
    kwargs=dict(runtime_identity={}, strategy_identity=strategy, required_mode=authority.RolloutMode.CONTROLLER,
        required_operation="AUTOMATION", execution_config_sha256="config",
        publication_policy_implementation_sha256="policy", publication_chain_root_sha256="root",
        current_publication_version=4, automation_config_sha256="automation")
    return certificate, kwargs


def test_exact_local_transition_passes_real_standing_boundary(case):
    certificate, kwargs = case
    assert standing.require_standing_observation_authority(None, **kwargs) is certificate


@pytest.mark.parametrize("field", ["strategy", "wealth_core_source_sha256", "controller_rule_sha256",
    "wealth_core_config_sha256", "data_semantics_source_sha256", "universe", "market_input_policy",
    "startup_policy", "cash_distribution_policy"])
def test_any_other_strategy_or_source_refuses(case, field):
    _certificate, kwargs = case
    kwargs["strategy_identity"] = {**kwargs["strategy_identity"], field: "changed"}
    with pytest.raises(authority.AuthorityRefused, match="strategy identity"):
        standing.require_standing_observation_authority(None, **kwargs)


def test_other_signed_predecessor_refuses(case):
    certificate, kwargs = case
    certificate.claims["bindings"]["strategy_identity_sha256"] = "f"*64
    with pytest.raises(authority.AuthorityRefused, match="strategy identity"):
        standing.require_standing_observation_authority(None, **kwargs)


def test_normal_release_has_no_exception(case, monkeypatch):
    certificate, kwargs = case
    monkeypatch.setattr(local_paper, "require_bound_account", lambda c: False)
    monkeypatch.setattr(standing, "runtime_artifact_identity", lambda r: dict(git_commit="commit",runtime_image_digest="image",test_image_digest="test"))
    certificate.claims["bindings"].update(git_commit="commit",runtime_image_digest="image",test_image_digest="test",runtime_identity_sha256=None)
    with pytest.raises(authority.AuthorityRefused, match="strategy identity"):
        standing.require_standing_observation_authority(None, **kwargs)


@pytest.mark.parametrize("guard", ["require_runtime", "require_execution_config"])
def test_local_runtime_and_execution_guards_still_refuse(case, monkeypatch, guard):
    _certificate, kwargs = case
    def refuse(*a): raise authority.AuthorityRefused("actual local identity refused")
    monkeypatch.setattr(local_paper, guard, refuse)
    with pytest.raises(authority.AuthorityRefused, match="actual local identity"):
        standing.require_standing_observation_authority(None, **kwargs)


def test_controller_rollout_cannot_change(case):
    certificate, kwargs = case
    certificate.rollout["to_version"] = 10
    with pytest.raises(authority.AuthorityRefused, match="controller rollout"):
        standing.require_standing_observation_authority(None, **kwargs)


def test_hash_pair_guard_removal_is_detected(case, monkeypatch):
    monkeypatch.setattr(upgrade, "allows_execution_transition", lambda *a: True)
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        test_any_other_strategy_or_source_refuses(case, "controller_rule_sha256")
