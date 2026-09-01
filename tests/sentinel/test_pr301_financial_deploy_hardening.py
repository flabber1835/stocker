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
        assert self.statement == (
            "SELECT pg_current_xact_id()::text,"
            " substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8)")
        return self.row


class _XidConnection:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _XidCursor(self.row)


def test_publication_binds_branch_unique_wrap_safe_pitr_target():
    # xid8 4294968296 is epoch 1, 32-bit xid 1000. PostgreSQL recovery matches
    # the latter; retaining the former plus a same-epoch base constraint prevents
    # xid wraparound ambiguity, while the explicit timeline prevents PITR forks
    # from redirecting recovery to a different transaction 1000.
    evidence = publication._publication_recovery_target(
        _XidConnection(("4294968296", "00000011")))
    assert evidence == {
        "schema": "sentinel.corpus-publication-pitr/2",
        "source_xid8": "4294968296",
        "source_xid_epoch": 1,
        "recovery_target_xid": "1000",
        "recovery_target_timeline": "0x00000011",
        "required_base_xid_epoch": 1,
        "recovery_target_inclusive": True,
        "recovery_target_action": "promote",
    }


@pytest.mark.parametrize("row", [
    (None, "00000001"),
    ("1000", None),
    ("1000", "not-a-timeline"),
    (str((1 << 32) + 2), "00000001"),
])
def test_publication_refuses_missing_or_ambiguous_pitr_authority(row):
    with pytest.raises(publication.CorpusIncoherent):
        publication._publication_recovery_target(_XidConnection(row))


def test_physical_base_backup_records_pitr_epoch_and_timeline_identity():
    script = (ROOT / "scripts/sentinel-base-backup.sh").read_text()
    assert "PITR_BEFORE=\"$(pitr_source_row)\"" in script
    assert "PITR_AFTER=\"$(pitr_source_row)\"" in script
    assert "base backup crossed a 32-bit transaction-id epoch" in script
    assert "base backup crossed a PostgreSQL WAL timeline" in script
    assert "sentinel-pitr-base-identity" in script
    assert "schema=sentinel.base-backup-pitr/1" in script
    assert "xid_epoch=%s" in script
    assert "timeline=0x%s" in script


def test_strict_recovered_order_policy_refuses_prefix_only_ownership():
    order = SimpleNamespace(
        client_key="sntl-deadbeef",
        instrument=SimpleNamespace(security_id="SEC:AAA"),
    )
    with pytest.raises(journal.RecoveredOrderConflict, match="prefix"):
        ownership.refuse_unauthenticated_recovered_order(
            object(), order, deployment=object())


def test_runtime_falsifier_exercises_strict_policy_through_fresh_process():
    script = (ROOT / "scripts/test-pr301-runtime-boundaries.sh").read_text()
    assert "SENTINEL_RECOVERED_ORDER_AUTHORITY=STRICT_V1" in script
    assert (
        "journal.adopt_recovered_order is "
        "policy.refuse_unauthenticated_recovered_order" in script)
    assert "journal.RecoveredOrderConflict" in script


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


def test_authorized_cli_repairs_only_certificate_readability_before_start():
    doc = yaml.safe_load(
        (ROOT / "docker-compose.sentinel-automation.yml").read_text())
    helper = doc["services"]["sentinel-authority-permissions"]
    assert helper["network_mode"] == "none"
    assert helper["user"] == "0:0"
    assert helper["cap_drop"] == ["ALL"]
    assert set(helper["cap_add"]) == {"DAC_OVERRIDE", "FOWNER"}
    assert helper["security_opt"] == ["no-new-privileges:true"]
    command = "\n".join(str(item) for item in helper["command"])
    assert "find /authority -type d -exec chmod 0711" in command
    assert "-name '*-certificate.json' -exec chmod 0644" in command
    cli = doc["services"]["sentinel-authorized-cli"]
    assert cli["depends_on"]["sentinel-authority-permissions"] == {
        "condition": "service_completed_successfully",
    }


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
