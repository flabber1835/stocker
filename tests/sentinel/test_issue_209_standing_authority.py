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
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sentinel_universe SET sector='Industrials',"
            " snapshot_date='2026-09-30'"
        )
    conn.commit()

    standing = require_standing_observation_authority(
        conn, **_kwargs(document, now=expired))
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


def test_runtime_drift_still_stops_standing_authority(conn):
    document = claims(conn)
    activate(conn, document)
    kwargs = _kwargs(
        document, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    kwargs["runtime_identity"] = runtime_identity(
        runtime_digest="sha256:" + sha("0"))

    with pytest.raises(authority.AuthorityRefused, match="runtime image digest"):
        require_standing_observation_authority(conn, **kwargs)
