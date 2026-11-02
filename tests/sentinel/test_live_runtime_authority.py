"""LIVE public enrollment observes actual binding/runtime and fresh file changes."""
from dataclasses import replace
import hashlib

import pytest

from sentinel.binding import AccountBinding
from sentinel.authority import live_runtime as runtime
from sentinel.authority.canonical import _b64url_encode, canonical_json_bytes
from sentinel.authority.live import AuthorityRefused, require_live_adapter_admission
from sentinel.authority.model import RolloutMode, RolloutState
from tests.sentinel.live_authority_fixtures import live_fixture, signed_live


def runtime_fixture(tmp_path, monkeypatch):
    fixture = live_fixture()
    bound = AccountBinding(fixture.subject.deployment_id, "alpaca-live", fixture.subject.account_id, 1)
    rollout = RolloutState(RolloutMode.PINNED_1_00, 1)
    monkeypatch.setattr(runtime.binding, "require", lambda conn: bound)
    monkeypatch.setattr(runtime.repository, "load_rollout_state", lambda conn: rollout)
    monkeypatch.setattr(runtime.ProtectedLimitPolicy, "from_env", lambda: None)
    root = fixture.roots[fixture.key_id]
    enrollment = {
        "schema": runtime.ENROLLMENT_SCHEMA,
        "roots": [{"key_id": fixture.key_id, "public_key": _b64url_encode(fixture.public_key),
                   "not_before": root.not_before.isoformat(), "not_after": root.not_after.isoformat(),
                   "status": "ENROLLED", "scope": "LIVE_EXECUTION"}],
        "revoked_certificate_sha256": [],
    }
    roots_path = tmp_path / "public-live-roots.json"
    certificate_path = tmp_path / "public-live-certificate.json"
    roots_path.write_bytes(canonical_json_bytes(enrollment))
    observed = {
        "deployment_artifacts": {"schema": "sentinel.runtime-artifacts/1", "git_commit": "1" * 40,
                                 "runtime_image_digest": "sha256:" + "2" * 64,
                                 "test_image_digest": "sha256:" + "3" * 64},
        "identity_hash": "4" * 64,
        "environment": {"compatible": True, "pins_match": True, "sources_known": True, "pin_drift": {},
                        "sentinel_source": {"hash": "5" * 64}},
    }
    strategy = {"schema": "offline-selected-strategy/1", "selection": "original"}
    context = runtime._context(fixture.subject, runtime_identity=observed, strategy_identity=strategy,
                               roots_path=roots_path, rollout=rollout, automation_config_sha256=None)
    claims = {**fixture.claims, "runtime_bindings": dict(context.runtime_bindings)}
    certificate_path.write_bytes(signed_live(claims, fixture.private_key, fixture.key_id))
    fixture.runtime, fixture.strategy, fixture.enrollment = observed, strategy, enrollment
    fixture.roots_path, fixture.certificate_path = roots_path, certificate_path
    fixture.bound, fixture.rollout, fixture.claims = bound, rollout, claims
    fixture.env = {runtime.CERTIFICATE_PATH_ENV: str(certificate_path),
                   runtime.TRUST_ROOTS_PATH_ENV: str(roots_path)}
    return fixture


def load(fixture, **kwargs):
    return runtime.load_live_adapter_admission(
        object(), base_url="https://api.alpaca.markets", runtime_identity=fixture.runtime,
        strategy_identity=fixture.strategy, env=fixture.env, now=fixture.now, **kwargs)


def test_public_loader_defaults_disabled_and_rejects_paper_binding(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    with pytest.raises(AuthorityRefused, match="SENTINEL_LIVE_CERTIFICATE_PATH"):
        runtime.load_live_adapter_admission(object(), base_url="https://api.alpaca.markets",
            runtime_identity=fixture.runtime, strategy_identity=fixture.strategy, env={}, now=fixture.now)
    monkeypatch.setattr(runtime.binding, "require", lambda conn: replace(fixture.bound, broker="alpaca"))
    with pytest.raises(AuthorityRefused, match="LIVE account binding"):
        load(fixture)


def test_current_context_is_computed_from_independent_runtime_and_rollout(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    admission = load(fixture)
    assert admission.context.runtime_bindings["runtime_image_digest"] == fixture.runtime["deployment_artifacts"]["runtime_image_digest"]
    assert admission.context.runtime_bindings["sentinel_source_sha256"] == "5" * 64
    verified = require_live_adapter_admission(admission, base_url="https://api.alpaca.markets", now=fixture.now)
    assert verified.subject.account_id == fixture.bound.broker_account_id
    fixture.runtime["environment"]["sentinel_source"]["hash"] = "6" * 64
    with pytest.raises(AuthorityRefused, match="current runtime"):
        require_live_adapter_admission(admission, base_url="https://api.alpaca.markets", now=fixture.now)


def test_adapter_rereads_revocation_and_certificate_files(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    admission = load(fixture)
    fixture.enrollment["revoked_certificate_sha256"] = [hashlib.sha256(fixture.certificate_path.read_bytes()).hexdigest()]
    fixture.roots_path.write_bytes(canonical_json_bytes(fixture.enrollment))
    with pytest.raises(AuthorityRefused, match="revoked"):
        require_live_adapter_admission(admission, base_url="https://api.alpaca.markets", now=fixture.now)


def test_adapter_rereads_durable_subject_and_rollout(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    admission = load(fixture)
    monkeypatch.setattr(runtime.binding, "require", lambda conn: replace(fixture.bound, takeover_epoch=2))
    with pytest.raises(AuthorityRefused, match="exact current account"):
        require_live_adapter_admission(admission, base_url=fixture.subject.base_url, now=fixture.now)
    monkeypatch.setattr(runtime.binding, "require", lambda conn: fixture.bound)
    rollout = RolloutState(RolloutMode.PINNED_1_00, 2)
    monkeypatch.setattr(runtime.repository, "load_rollout_state", lambda conn: rollout)
    with pytest.raises(AuthorityRefused, match="current runtime"):
        require_live_adapter_admission(admission, base_url=fixture.subject.base_url, now=fixture.now)
    current = runtime._context(fixture.subject, runtime_identity=fixture.runtime,
        strategy_identity=fixture.strategy, roots_path=fixture.roots_path,
        rollout=rollout, automation_config_sha256=None)
    claims = {**fixture.claims, "runtime_bindings": dict(current.runtime_bindings)}
    fixture.certificate_path.write_bytes(signed_live(claims, fixture.private_key, fixture.key_id))
    assert require_live_adapter_admission(admission, base_url=fixture.subject.base_url,
        now=fixture.now).claims.runtime_bindings == dict(current.runtime_bindings)


def test_adapter_rereads_issuer_disable_and_changed_certificate(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    admission = load(fixture)
    fixture.enrollment["roots"][0]["status"] = "DISABLED"
    fixture.roots_path.write_bytes(canonical_json_bytes(fixture.enrollment))
    with pytest.raises(AuthorityRefused, match="enrolled"):
        require_live_adapter_admission(admission, base_url="https://api.alpaca.markets", now=fixture.now)
    fixture.enrollment["roots"][0]["status"] = "ENROLLED"
    fixture.roots_path.write_bytes(canonical_json_bytes(fixture.enrollment))
    fixture.certificate_path.write_bytes(b'{"schema":"changed"}')
    with pytest.raises(AuthorityRefused, match="schema"):
        require_live_adapter_admission(admission, base_url="https://api.alpaca.markets", now=fixture.now)


def test_invalid_runtime_and_oversized_public_files_refuse(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    fixture.runtime["environment"]["compatible"] = False
    with pytest.raises(AuthorityRefused, match="not certified"):
        load(fixture)
    fixture.runtime["environment"]["compatible"] = True
    fixture.roots_path.write_bytes(b"x" * (runtime.MAX_CERTIFICATE_BYTES + 1))
    with pytest.raises(AuthorityRefused, match="byte bound"):
        load(fixture)


def test_automatic_and_manual_contexts_and_rollout_do_not_replay(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    verified = runtime.require_current_live_authority(object(), base_url="https://api.alpaca.markets",
        runtime_identity=fixture.runtime, strategy_identity=fixture.strategy,
        required_operation="AUTOMATION", env=fixture.env, now=fixture.now)
    assert verified.subject == fixture.subject
    with pytest.raises(AuthorityRefused, match="current runtime"):
        load(fixture, automation_config_sha256="7" * 64)
    with pytest.raises(AuthorityRefused, match="requested durable rollout"):
        runtime.require_current_live_authority(object(), base_url="https://api.alpaca.markets",
            runtime_identity=fixture.runtime, strategy_identity=fixture.strategy,
            required_operation="EXECUTE_READ", required_mode="CONTROLLER", env=fixture.env, now=fixture.now)


def test_shared_configuration_does_not_promote_a_manual_certificate(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    fixture.claims["permitted_operations"] = ["READ", "SUBMIT", "CANCEL"]
    fixture.certificate_path.write_bytes(signed_live(fixture.claims, fixture.private_key, fixture.key_id))
    with pytest.raises(AuthorityRefused, match="does not allow"):
        runtime.require_current_live_authority(object(), base_url="https://api.alpaca.markets",
            runtime_identity=fixture.runtime, strategy_identity=fixture.strategy,
            required_operation="AUTOMATION", env=fixture.env, now=fixture.now)


def test_context_binds_independently_selected_live_issuer_policy(tmp_path, monkeypatch):
    from sentinel.execution import issuer_admission
    fixture = runtime_fixture(tmp_path, monkeypatch)
    admission = load(fixture)
    original = issuer_admission.policy_sha256
    seen = []
    def changed(subject):
        seen.append(subject)
        assert subject["broker"] == "alpaca-live"
        assert original(subject) == issuer_admission.LIVE_POLICY_SHA256
        return "a" * 64
    monkeypatch.setattr(issuer_admission, "policy_sha256", changed)
    with pytest.raises(AuthorityRefused, match="current runtime"):
        require_live_adapter_admission(admission, base_url=fixture.subject.base_url, now=fixture.now)
    assert seen


def test_enrollment_parser_rejects_paper_root_record_and_duplicate_identity(tmp_path, monkeypatch):
    fixture = runtime_fixture(tmp_path, monkeypatch)
    fixture.enrollment["roots"][0]["scope"] = "ALPACA_PAPER"
    fixture.roots_path.write_bytes(canonical_json_bytes(fixture.enrollment))
    with pytest.raises(AuthorityRefused, match="root record"):
        load(fixture)
    fixture.enrollment["roots"][0]["scope"] = "LIVE_EXECUTION"
    fixture.enrollment["roots"].append(dict(fixture.enrollment["roots"][0]))
    fixture.roots_path.write_bytes(canonical_json_bytes(fixture.enrollment))
    with pytest.raises(AuthorityRefused, match="root identity"):
        load(fixture)
