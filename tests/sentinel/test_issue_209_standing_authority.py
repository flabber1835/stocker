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


def test_nominal_expiry_stops_ordinary_paper_trial_authority(conn):
    document = claims(conn)
    activate(conn, document)
    expired = datetime(2026, 10, 1, tzinfo=timezone.utc)

    with pytest.raises(authority.AuthorityRefused, match="expired"):
        authority.load_active_signed_certificate(
            conn, now=expired, trust_roots=ROOTS)

    with pytest.raises(authority.AuthorityRefused, match="expired"):
        require_standing_observation_authority(
            conn, **_kwargs(document, now=expired))


def test_newer_metadata_is_accepted_while_certificate_is_valid(conn):
    document = claims(conn)
    activate(conn, document)
    valid_now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    # A forward trial accepts ordinary future TICKERS evolution once the normal
    # ingest/publication/readiness path has made it current authority. This does
    # not extend the certificate's signed lifetime.
    current_version = publish_metadata_snapshot(
        conn, snapshot_date="2026-08-24", sector="Industrials")

    kwargs = _kwargs(document, now=valid_now)
    kwargs["current_publication_version"] = current_version
    standing = require_standing_observation_authority(conn, **kwargs)
    assert standing.authorization_mode == authority.PAPER_OBSERVATION_ONLY


def test_explicit_revocation_still_stops_observation_authority(conn):
    document = claims(conn)
    digest = activate(conn, document)
    authority.revoke_signed_certificate(
        conn, certificate_sha256=digest, reason="operator stop")

    with pytest.raises(authority.AuthorityRefused, match="revoked"):
        require_standing_observation_authority(
            conn,
            **_kwargs(
                document,
                now=datetime(2026, 8, 25, tzinfo=timezone.utc),
            ),
        )


def test_runtime_drift_still_stops_observation_authority(conn):
    document = claims(conn)
    activate(conn, document)
    kwargs = _kwargs(
        document, now=datetime(2026, 8, 25, tzinfo=timezone.utc))
    kwargs["runtime_identity"] = runtime_identity(
        runtime_digest="sha256:" + sha("0"))

    with pytest.raises(authority.AuthorityRefused, match="runtime image digest"):
        require_standing_observation_authority(conn, **kwargs)


def test_panel_uses_bounded_observation_lifecycle_semantics():
    import inspect
    from sentinel.panel import sources

    source = inspect.getsource(sources._authority_lifecycle)  # noqa: SLF001
    assert "PAPER_OBSERVATION_ONLY" in source
    assert "c.expires_at > clock_timestamp()" in source
