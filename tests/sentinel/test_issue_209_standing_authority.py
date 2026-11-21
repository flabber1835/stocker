from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentinel import authority
from sentinel.standing_observation_authority import (
    require_standing_observation_authority,
)
from tests.sentinel.test_paper_observation_authority import (
    ROOTS,
    activate,
    claims,
    conn,
    pg,
    runtime_identity,
    sha,
    publish_metadata_snapshot,
)


def _kwargs(document, *, now):
    return {
        "runtime_identity": runtime_identity(),
        "strategy_identity": {"strategy": "current"},
        "required_mode": authority.RolloutMode.CONTROLLER,
        "required_operation": "AUTOMATION",
        "execution_config_sha256": sha("3"),
        "publication_policy_implementation_sha256": sha("8"),
        "publication_chain_root_sha256": document["bindings"]
            ["current_corpus"]["publication_chain_root_sha256"],
        "current_publication_version": 81,
        "automation_config_sha256": sha("4"),
        "now": now,
        "trust_roots": ROOTS,
    }


def test_nominal_expiry_does_not_stop_unchanged_paper_trial(conn):
    document = claims(conn)
    digest = activate(conn, document)
    expired = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # Diagnostic/default loading still reports the nominal observation window
    # as expired. Standing paper operation uses a narrower explicit authority
    # path rather than globally disabling certificate-time validation.
    with pytest.raises(authority.AuthorityRefused, match="expired"):
        authority.load_active_signed_certificate(
            conn, now=expired, trust_roots=ROOTS)

    standing = require_standing_observation_authority(
        conn, **_kwargs(document, now=expired))
    assert standing.certificate_sha256 == digest
    assert standing.authorization_mode == authority.PAPER_OBSERVATION_ONLY


def test_newer_metadata_does_not_require_certificate_rotation(conn):
    document = claims(conn)
    activate(conn, document)
    expired = datetime(2026, 10, 1, tzinfo=timezone.utc)

    # A forward trial must accept ordinary future TICKERS evolution once the
    # normal ingest/publication/readiness path has made it current authority.
    # Model the real path: a new immutable snapshot in a new published run.
    current_version = publish_metadata_snapshot(
        conn, snapshot_date="2026-09-30", sector="Industrials")

    kwargs = _kwargs(document, now=expired)
    kwargs["current_publication_version"] = current_version
    standing = require_standing_observation_authority(conn, **kwargs)
    assert standing.authorization_mode == authority.PAPER_OBSERVATION_ONLY


def test_explicit_revocation_still_stops_standing_authority(conn):
    document = claims(conn)
    digest = activate(conn, document)
    authority.revoke_signed_certificate(
        conn, certificate_sha256=digest, reason="operator stop")

    with pytest.raises(authority.AuthorityRefused, match="revoked"):
        require_standing_observation_authority(
            conn,
            **_kwargs(
                document,
                now=datetime(2026, 10, 1, tzinfo=timezone.utc),
            ),
        )


def test_automated_broker_checks_share_chain_work_and_recheck_revocation(conn, monkeypatch):
    from sentinel import standing_observation_authority as standing
    from sentinel.execution import authority_gate as gateway
    from sentinel.execution.contract import BrokerAccountIdentity
    from sentinel.execution.guarded import AutomationExecutionGrant, BrokerOperation
    from sentinel.feed import store

    document = claims(conn)
    bindings = document['bindings']
    bindings['execution_config_sha256'] = authority.canonical_sha256(
        authority.execution_config_identity(paper_base_url=authority.PAPER_BASE_URL))
    bindings['publication_policy']['implementation_sha256'] = (
        gateway.publication_policy_implementation_sha256())
    digest = activate(conn, document)
    expired = datetime(2026, 10, 1, tzinfo=timezone.utc)
    certificates = []
    chains = []

    def load(fresh, *, now, allow_expired_observation_safety, **_trust):
        certificates.append(fresh)
        return authority.load_active_signed_certificate(
            fresh, now=expired, trust_roots=ROOTS,
            allow_expired_observation_safety=allow_expired_observation_safety)

    original_chain = gateway.require_publication_chain

    def verify_chain(fresh, **kwargs):
        chains.append(fresh)
        root = original_chain(fresh, **kwargs)
        if len(chains) == 2:
            authority.revoke_signed_certificate(
                conn, certificate_sha256=digest, reason='revoked during second guard invocation')
        return root

    monkeypatch.setattr(gateway, 'load_active_signed_certificate', load)
    monkeypatch.setattr(standing, 'load_active_signed_certificate', load)
    monkeypatch.setattr(gateway, 'require_publication_chain', verify_chain)
    check = gateway.build_fresh_execution_check(
        connection_factory=lambda: store.connect(conn.info.dsn),
        paper_base_url=authority.PAPER_BASE_URL, runtime_identity=runtime_identity,
        strategy_identity=lambda: {'strategy': 'current'},
        validate_grant=lambda *args: None, automation_config_sha256=sha('4'),
        publish_operational_evidence=False)
    grant = AutomationExecutionGrant(operation_scope='EXECUTE', cycle_id='private-cycle',
        control_generation=1, holder_id='holder', fence_token=1,
        broker_account_id='paper-123', takeover_epoch=1, rollout_mode='CONTROLLER',
        rollout_version=2, certificate_sha256=digest)
    check(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)
    assert len(chains) == 1 and certificates == chains * 2

    with pytest.raises(authority.AuthorityRefused, match='revoked'):
        check(grant, BrokerOperation.IDENTIFY_ACCOUNT, BrokerAccountIdentity('alpaca', 'paper-123'))
    before, after = chains
    assert before is not after and certificates == [before, before, after, after]


def test_standing_combined_permission_keeps_automation_config_check(conn):
    document = claims(conn)
    activate(conn, document)
    kwargs = _kwargs(document, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    kwargs['required_operation'] = ('AUTOMATION', 'EXECUTE_READ')
    kwargs['automation_config_sha256'] = sha('0')
    with pytest.raises(authority.AuthorityRefused, match='automation configuration'):
        require_standing_observation_authority(conn, **kwargs)


def test_runtime_drift_still_stops_standing_authority(conn):
    document = claims(conn)
    activate(conn, document)
    kwargs = _kwargs(
        document, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    kwargs["runtime_identity"] = runtime_identity(
        runtime_digest="sha256:" + sha("0"))

    with pytest.raises(authority.AuthorityRefused, match="runtime image digest"):
        require_standing_observation_authority(conn, **kwargs)


def test_panel_uses_standing_observation_lifecycle_semantics():
    import inspect
    from sentinel.panel import sources

    source = inspect.getsource(sources._authority_lifecycle)  # noqa: SLF001
    assert "PAPER_OBSERVATION_ONLY" in source
    assert "c.expires_at > clock_timestamp()" in source
