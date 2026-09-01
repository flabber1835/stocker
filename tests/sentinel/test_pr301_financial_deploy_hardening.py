from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sentinel.execution import journal
from sentinel.execution import recovered_order_policy as ownership
from sentinel.feed import publication


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))


class _XidCursor:
    def __init__(self, row):
        self.row = row
        self.statement = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=None):
        self.statement = statement

    def fetchone(self):
        assert self.statement == "SELECT pg_current_xact_id()::text"
        return self.row


class _XidConnection:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _XidCursor(self.row)


def test_publication_binds_exact_pitr_transaction_target():
    evidence = publication._publication_recovery_target(
        _XidConnection(("4294968296",)))
    assert evidence == {
        "schema": "sentinel.corpus-publication-pitr/1",
        "recovery_target_xid": "4294968296",
        "recovery_target_action": "promote-after",
    }


def test_publication_refuses_missing_pitr_transaction_authority():
    with pytest.raises(publication.CorpusIncoherent):
        publication._publication_recovery_target(_XidConnection((None,)))


def test_strict_recovered_order_policy_refuses_prefix_only_ownership():
    order = SimpleNamespace(
        client_key="sntl-deadbeef",
        instrument=SimpleNamespace(security_id="SEC:AAA"),
    )
    with pytest.raises(journal.RecoveredOrderConflict, match="prefix"):
        ownership.refuse_unauthenticated_recovered_order(
            object(), order, deployment=object())


def test_authorized_services_enable_strict_ownership_and_kernel_hardening():
    doc = yaml.safe_load(
        (ROOT / "docker-compose.sentinel-automation.yml").read_text())
    authority = doc["x-sentinel-authorized-environment"]
    assert authority["SENTINEL_RECOVERED_ORDER_AUTHORITY"] == "STRICT_V1"

    for name in (
        "sentinel-authorized-cli",
        "sentinel-automation",
        "sentinel-alert-dispatcher",
        "sentinel-shadow",
    ):
        service = doc["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]


def test_standby_broker_service_uses_same_strict_authority_and_hardening():
    doc = yaml.safe_load(
        (ROOT / "docker-compose.sentinel-automation-standby.yml").read_text())
    automation = doc["services"]["sentinel-automation-standby"]
    assert automation["environment"]["SENTINEL_RECOVERED_ORDER_AUTHORITY"] == "STRICT_V1"
    for name in ("sentinel-automation-standby", "sentinel-alert-dispatcher-standby"):
        service = doc["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]


def test_ordinary_python_services_have_same_kernel_hardening():
    doc = yaml.safe_load((ROOT / "docker-compose.sentinel.yml").read_text())
    for name in ("sentinel", "sentinel-panel"):
        service = doc["services"][name]
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]


def test_deployable_image_has_fixed_non_root_user_and_test_lens_reenters_root():
    runtime = (ROOT / "Dockerfile.sentinel").read_text()
    test_image = (ROOT / "Dockerfile.sentinel-test").read_text()
    assert "USER 10001:10001" in runtime
    assert "useradd --system --uid 10001 --gid 10001" in runtime
    assert "FROM ${SENTINEL_IMAGE}" in test_image
    assert "USER root" in test_image


def test_autonomous_deploy_migrates_existing_audit_volume_before_bootstrap():
    launcher = (ROOT / "scripts/sentinel-autonomous-deploy.sh").read_text()
    migration = (ROOT / "scripts/sentinel-state-volume-permissions.sh").read_text()
    call = "bash scripts/sentinel-state-volume-permissions.sh"
    assert call in launcher
    assert launcher.index(call) < launcher.index(
        'exec "$PYTHON" scripts/sentinel_autonomous_deploy_bootstrap.py')
    assert 'VOLUME="sentinel_sentinel_state"' in migration
    assert 'chown -R 10001:10001 /sentinel-state' in migration
    assert '--network none' in migration
