#!/usr/bin/env python3
"""Hardened entrypoint layered over sentinel_autonomous_deploy.

The core module contains the deployment state machine.  This driver owns the
adversarial/restart rules that need database history rather than just current
active state: abandoned staged issuer generations, administrative predecessor
rotation, exact private-key identity, exact plan re-read, vendor-freshness
waiting, and optional durable predecessor signing-key revocation.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Mapping, Optional, Sequence, Tuple

import sentinel_autonomous_deploy as core


_CANONICAL_EXPOSURE = re.compile(r"^(?:0|1|0\.[0-9]{0,17}[1-9])$")
_PUBLICATION_STABILIZATION_POLLS = 2


class Config(core.Config):
    def __init__(self, env: Mapping[str, str]) -> None:
        super().__init__(env)
        if _CANONICAL_EXPOSURE.fullmatch(self.max_exposure) is None:
            raise core.DeployRefused(
                "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE must use the canonical "
                "certificate spelling: 0, 1, or a non-zero decimal such as 0.75")
        self.revoke_previous_signing_key = core._as_bool(
            env.get("SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY", "0"),
            name="SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY")
        self.data_retry_seconds = core._int(
            env.get("SENTINEL_DEPLOY_DATA_RETRY_SECONDS", "300"),
            name="SENTINEL_DEPLOY_DATA_RETRY_SECONDS",
            minimum=30, maximum=3600)
        self.data_wait_timeout_seconds = core._int(
            env.get("SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS", "43200"),
            name="SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS",
            minimum=300, maximum=86400)


class AutonomousDeploy(core.AutonomousDeploy):
    predecessor_key_id: str = ""

    def _readiness_verdict(self) -> Mapping:
        """Read the exact readiness object as JSON without parsing terminal prose."""
        code = r'''
import json, os
from sentinel.feed import operational_snapshot, readiness, rolling_go_inputs, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    rolling_go_inputs.require_schemas(c)
    with rolling_go_inputs.pinned(c) as current:
        if not rolling_go_inputs.is_rolling(current):
            raise RuntimeError("ROLLING_PUBLICATION_REQUIRED")
        operational_snapshot.require_alpaca_openfigi(c, current)
        result = rolling_go_inputs.assessment(c, current)
    readiness.save_snapshot(c, result)
    checks = [
        {'name': item.name, 'status': item.status,
         'detail': item.detail, 'value': item.value}
        for item in result.checks
    ]
    print(json.dumps({
        'ready': bool(result.ready),
        'rolling': True,
        'checks': checks,
        'failures': [item for item in checks if item['status'] == 'FAIL'],
    }, default=str))
finally:
    c.rollback(); c.close()
'''.strip()
        result = self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
            *self._retained_reader_args(),
            "--entrypoint", "python", "sentinel", "-c", code],
            capture=True)
        verdict = core._json_output(result, label="data readiness")
        if not isinstance(verdict.get("ready"), bool):
            raise core.DeployRefused(
                "structured data readiness has no boolean ready verdict")
        checks = verdict.get("checks")
        failures = verdict.get("failures")
        if not isinstance(checks, list) or not isinstance(failures, list):
            raise core.DeployRefused(
                "structured data readiness has no check/failure list")
        for item in checks + failures:
            if (not isinstance(item, dict)
                    or not str(item.get("name") or "")
                    or not str(item.get("status") or "")):
                raise core.DeployRefused(
                    "structured data readiness contains a malformed check")
        return verdict

    def _write_deployment_state(self, state: str, *, attempt: int,
                                failures) -> None:
        """Retain the staged/waiting fact beside the deployment evidence."""
        payload = {
            "schema": core.DEPLOY_SCHEMA,
            "state": state,
            "updated_at": core._utc_text(core._utcnow()),
            "git_commit": self.commit,
            "attempt": int(attempt),
            "failures": list(failures or []),
        }
        path = self.attempt_dir / "deployment-state.json"
        temporary = self.attempt_dir / "deployment-state.json.tmp"
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8")
        temporary.replace(path)

    def _assert_wait_fence(self) -> None:
        status = self._automation_status()
        if (status.get("enabled") is not False
                or status.get("kill_switch_engaged") is not True):
            raise core.DeployRefused(
                "WAITING_FOR_DATA lost the required disabled+kill automation fence")

    def _refuse_data_readiness(self, verdict: Mapping, *, attempt: int,
                               reason: str) -> None:
        failures = verdict.get("failures") or []
        self._base_cli(["check-data"], check=False)
        self._write_deployment_state(
            "DATA_REFUSED", attempt=attempt, failures=failures)
        names = ", ".join(
            str(item.get("name") or "UNKNOWN") for item in failures)
        raise core.DeployRefused("%s: %s" % (reason, names or "UNKNOWN"))

    def refresh_data(self) -> None:
        """The installation owner may renew inputs only under its durable fence."""
        self._assert_wait_fence()
        verdict = self._readiness_verdict()
        if verdict.get("rolling") is not True:
            raise core.DeployRefused("operational deployment requires rolling Alpaca inputs")
        if verdict.get("ready") is not True:
            self._refuse_data_readiness(verdict, attempt=1, reason="rolling GO publication is not ready")
        self._base_cli(["check-data"])
        self.runner.run(self.base_compose + ["up", "-d", "sentinel-panel"])
        self._write_deployment_state("DATA_READY", attempt=1, failures=[])

    def _verify_signing_key_is_trusted(self) -> None:
        """Before transition, prove the private key itself matches an ACTIVE root."""
        key_mount = (
            "type=bind,src=%s,dst=/signing-key,readonly" % self.cfg.signing_key)
        code = r'''
import sys
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from sentinel.authority import key_id_for_public_key, load_trust_roots
from tools.sentinel_certificate_issuer import _load_private_key
key = _load_private_key(Path('/signing-key'))
public = key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)
actual = key_id_for_public_key(public)
assert actual == sys.argv[1], 'configured private key does not match key id'
root = load_trust_roots().get(actual)
assert root is not None, 'configured signing key is not a committed trust root'
assert root.status == 'ACTIVE', 'configured signing key is not an ACTIVE trust root'
now = datetime.now(timezone.utc)
assert root.not_before <= now < root.not_after, 'configured signing root is outside its validity interval'
print(actual)
'''.strip()
        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--mount", key_mount, "--entrypoint", "python",
            "sentinel-test:latest", "-c", code, self.cfg.signing_key_id])

    def _admin_authority_state(self) -> Mapping:
        code = r'''
import json, os
from sentinel.feed import store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
cur = c.cursor()
cur.execute("SELECT highest_issuer_generation,active_certificate_sha256 FROM sentinel_administrative_authority_state WHERE id=1")
row = cur.fetchone()
highest = int(row[0]) if row else 0
active = str(row[1]) if row and row[1] else None
cur.execute("SELECT COALESCE(MAX(issuer_generation),0) FROM sentinel_signed_administrative_certificates")
installed = int(cur.fetchone()[0])
print(json.dumps({'highest_issuer_generation':highest,'max_installed_issuer_generation':installed,'active_certificate_sha256':active}))
c.rollback(); c.close()
'''.strip()
        result = self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel-authorized-cli", "-c", code],
            capture=True)
        return core._json_output(result, label="administrative authority state")

    def ensure_ownership(self) -> None:
        self.phase("ownership: verify canonical PostgreSQL account binding")
        status = self._status()
        state = core.validate_owned_status(status, self.cfg)
        if state == "OWNED":
            return

        self.phase("ownership: one-time strict empty-account enrollment")
        authority_state = self._admin_authority_state()
        generation = max(
            int(authority_state.get("highest_issuer_generation") or 0),
            int(authority_state.get("max_installed_issuer_generation") or 0),
        ) + 1
        predecessor = authority_state.get("active_certificate_sha256")
        if predecessor is not None and re.fullmatch(
                r"[0-9a-f]{64}", str(predecessor)) is None:
            raise core.DeployRefused(
                "active administrative certificate identity is malformed")

        candidate = self.attempt_dir / "empty-binding-candidate.json"
        cert = self.attempt_dir / "empty-binding-certificate.json"
        candidate_id = "empty-bind-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-empty-paper-binding-candidate",
            "--certificate-id", candidate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before-delay-seconds", str(self.cfg.not_before_margin),
            "--reviewer", self.cfg.reviewer,
            "--ticket", "%s-empty-%d" % (
                self.cfg.ticket_prefix, generation)], capture=True)
        candidate.write_text(result.stdout, encoding="utf-8")
        document = json.loads(result.stdout)
        claims = document["claims"]
        if claims.get("supersedes_certificate_sha256") != predecessor:
            raise core.DeployRefused(
                "empty-binding candidate predecessor differs from durable "
                "administrative authority")
        actual_not_before = claims["not_before"]
        digest = self._sign(
            tool="tools.sentinel_empty_account_authority",
            candidate=candidate, output=cert,
            confirmation="--confirm-issue-admin-bind-empty")
        print('  enrollment permission issued; this permission cannot submit orders', flush=True)
        self._authorized_cli([
            "install-administrative-certificate", "--certificate",
            self._authorized_artifact(cert), "--confirm-certificate-sha256",
            digest, "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id, "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-install-administrative-certificate"])
        self._wait_for(actual_not_before)
        activate = [
            "activate-administrative-certificate",
            "--certificate-sha256", digest,
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-activate-administrative-certificate"]
        if predecessor:
            activate.extend([
                "--confirm-supersedes-certificate-sha256", str(predecessor)])
        self._authorized_cli(activate)

        inspected = core._json_output(self._authorized_cli([
            "inspect-empty-paper-account", "--deployment-id",
            self.cfg.deployment_id, "--expect-account", self.cfg.account_id],
            capture=True), label="empty account inspection")
        if (inspected.get("approval_ready") is not True
                or inspected.get("observation_complete") is not True
                or inspected.get("positions") != []
                or inspected.get("working_open_orders") != []):
            raise core.DeployRefused(
                "unbound account is not provably complete, empty, and stable; "
                "inherited books are never auto-migrated")
        self._authorized_cli([
            "bind-empty-paper-account", "--deployment-id",
            self.cfg.deployment_id, "--expect-account", self.cfg.account_id,
            "--notes", "autonomous strict-empty enrollment"])
        core.validate_owned_status(self._status(), self.cfg)

    def _execution_authority_state(self) -> Mapping:
        """Use max installed generation so abandoned STAGED certs cannot trap reruns."""
        code = r'''
import json, os
from sentinel.feed import store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
cur = c.cursor()
cur.execute("SELECT highest_issuer_generation,active_certificate_sha256 FROM sentinel_execution_authority_state WHERE id=1")
row = cur.fetchone()
highest = int(row[0]) if row else 0
active = str(row[1]) if row and row[1] else None
cur.execute("SELECT COALESCE(MAX(issuer_generation),0) FROM sentinel_signed_execution_certificates")
installed = int(cur.fetchone()[0])
key_id = None
if active:
    cur.execute("SELECT key_id FROM sentinel_signed_execution_certificates WHERE certificate_sha256=%s", (active,))
    key_row = cur.fetchone()
    key_id = str(key_row[0]) if key_row else None
print(json.dumps({'highest_issuer_generation':max(highest,installed),'active_highest_issuer_generation':highest,'max_installed_issuer_generation':installed,'active_certificate_sha256':active,'active_key_id':key_id}))
c.rollback(); c.close()
'''.strip()
        result = self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel-authorized-cli", "-c", code],
            capture=True)
        state = core._json_output(result, label="execution authority state")
        self.predecessor_key_id = str(state.get("active_key_id") or "")
        return state

    def rotate_observation_authority(self) -> Tuple[str, str]:
        verdict = self._readiness_verdict()
        if verdict.get("ready") is not True:
            self._refuse_data_readiness(
                verdict, attempt=1, reason="data readiness changed before authority creation")
        result = super().rotate_observation_authority()
        predecessor_key = self.predecessor_key_id
        if (self.cfg.revoke_previous_signing_key and predecessor_key
                and predecessor_key != self.cfg.signing_key_id):
            self.phase("authority: durably revoke predecessor signing key")
            self._authorized_cli([
                "revoke-system-key", "--key-id", predecessor_key,
                "--reason", "autonomous signing-key rotation completed",
                "--confirm-revoke-system-key"])
        return result

    def prepare_activate_start(self, certificate_sha256: str,
                               decision_session: str) -> Mapping:
        timing = self.assert_activation_timing(decision_session)
        opening_cutoff = self._activation_backup_cutoff(timing)
        self.quiesce_activation_writers()
        self.phase("plan: prepare and re-read one exact durable paper plan")
        prepare_args = [
            "prepare-paper-plan", "--through", decision_session,
            "--warmup-sessions", "252", "--expect-account",
            self.cfg.account_id]
        if (self.reviewed_validation is not None
                and self.reviewed_validation.mode == "dual"):
            prepare_args.append("--reviewed-informational-dual")
        prepare_args += self._initial_paper_recovery_args()
        prepared, fee_deadline = self._prepare_activation_plan(
            prepare_args, certificate_sha256, decision_session, timing)
        current = self._check_prepared_activation_plan(prepared, decision_session)

        if fee_deadline:
            self._native_fee_wait_seconds(fee_deadline)
        self.phase(
            "automation: activate behind kill with financial services stopped")
        self._activation_backup_cli([
            "activate-paper-automation",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--confirm-old-writer-fenced", "--actor", self.cfg.actor,
            "--reason", "autonomous deployment",
            "--confirm-enable-unattended-alpaca-paper-automation"],
            certificate_sha256=certificate_sha256, deadline=fee_deadline, cutoff=opening_cutoff,
            decision_session=decision_session)
        killed = self._automation_status()
        if (killed.get("enabled") is not True
                or killed.get("kill_switch_engaged") is not True
                or killed.get("certificate_sha256") != certificate_sha256):
            raise core.DeployRefused(
                "automation control did not retain the expected kill fence")
        self.verify_operator_services()
        self.establish_activation_backup()
        self.assert_activation_timing(decision_session)
        self._require_activation_writers_stopped()
        from sentinel_activation_recovery import authorize_requested
        if fee_deadline:
            self._native_fee_wait_seconds(fee_deadline)
        authorize_requested(self, certificate_sha256, decision_session)
        if fee_deadline:
            self._native_fee_wait_seconds(fee_deadline)
        self._activation_backup_cli([
            "release-paper-automation-kill-switch",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--actor", self.cfg.actor,
            "--reason", "autonomous deployment verified",
            "--confirm-release-unattended-paper-kill-switch"],
            certificate_sha256=certificate_sha256, enabled=True, deadline=fee_deadline, cutoff=opening_cutoff,
            decision_session=decision_session)
        self.start_activated_runtime(certificate_sha256, decision_session)
        return current


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Every historical operator entry selects the same software-only boundary.
    from sentinel_installation_phase import main as installation_main
    return installation_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
