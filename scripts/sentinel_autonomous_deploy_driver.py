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
from sentinel.feed import readiness, store
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    result = readiness.check_readiness(c)
    readiness.save_snapshot(c, result)
    checks = [
        {'name': item.name, 'status': item.status,
         'detail': item.detail, 'value': item.value}
        for item in result.checks
    ]
    print(json.dumps({
        'ready': bool(result.ready),
        'checks': checks,
        'failures': [item for item in checks if item['status'] == 'FAIL'],
    }, default=str))
finally:
    c.rollback(); c.close()
'''.strip()
        result = self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
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

    def _freshness_wait_requirements(
            self, verdict: Mapping) -> Optional[Tuple[Tuple[str, ...], int]]:
        """Return the exact vendor evidence needed for retryable staleness.

        A failure merely NAMED freshness is not enough. Calendar-unavailable,
        anomalous-ahead, and malformed freshness states are not publication lag.
        The retryable state is a normal, evaluable corpus that is behind by one
        or more named closed sessions, with a passing frontier population check
        that supplies the same 80%-of-recent-median materiality floor readiness
        will enforce after ingest.
        """
        failures = verdict.get("failures") or []
        if (len(failures) != 1
                or str(failures[0].get("name") or "") != "freshness"):
            return None
        value = failures[0].get("value")
        if not isinstance(value, dict):
            return None
        missing = value.get("missing_sessions")
        if (value.get("evaluable") is not True
                or value.get("ahead") is True
                or not isinstance(missing, list)
                or not missing):
            return None
        sessions = tuple(str(item) for item in missing if str(item))
        if len(sessions) != len(missing) or list(sessions) != sorted(sessions):
            return None

        population = next(
            (item for item in (verdict.get("checks") or [])
             if str(item.get("name") or "") == "frontier population"), None)
        population_value = (
            population.get("value") if isinstance(population, dict) else None)
        minimum = (population_value.get("minimum")
                   if isinstance(population_value, dict) else None)
        if (not isinstance(population, dict)
                or population.get("status") != "PASS"
                or not isinstance(minimum, int)
                or minimum <= 0):
            raise core.DeployRefused(
                "freshness-only wait has no trustworthy frontier-population floor")
        return sessions, minimum

    def _vendor_publication_probe(
            self, sessions: Sequence[str], minimum_rows: int) -> Mapping:
        """Read-only probe for usable missing-session SEP and SPY evidence.

        A raw ticker count is too optimistic: the real ingest drops rows with no
        permanent identity or no positive as-traded close. Count distinct
        security IDs that satisfy those same two admission rules against the
        currently published resolver, and require a positive finite SPY
        `closeadj`. Only then is one full authoritative daily ingest warranted.
        """
        requested = tuple(str(item) for item in sessions)
        if not requested or list(requested) != sorted(requested):
            raise core.DeployRefused(
                "vendor publication probe sessions are malformed")
        if not isinstance(minimum_rows, int) or minimum_rows <= 0:
            raise core.DeployRefused(
                "vendor publication probe minimum is malformed")
        code = r'''
import json, math, os, sys
from sentinel.feed import sharadar, store, universe
sessions = tuple(x for x in sys.argv[1].split(',') if x)
targets = set(sessions)
seen = {session: set() for session in sessions}
c = store.connect(os.environ['SENTINEL_DATABASE_URL'])
try:
    resolver = universe.load_resolver(c).resolve
    params = sharadar.date_params(sessions[0], sessions[-1])
    for row in sharadar.fetch_table(sharadar.SEP, params):
        session = str(row.get('date') or '')
        if session not in targets:
            continue
        ticker = str(row.get('ticker') or '').strip().upper()
        try:
            raw = float(row.get('closeunadj'))
        except (TypeError, ValueError):
            raw = float('nan')
        sid = resolver(ticker, session) if ticker else None
        if sid is not None and math.isfinite(raw) and raw > 0:
            seen[session].add(str(sid))
finally:
    c.rollback(); c.close()
spy = set()
spy_params = {'ticker': 'SPY', **sharadar.date_params(sessions[0], sessions[-1])}
for row in sharadar.fetch_table(sharadar.SFP, spy_params):
    session = str(row.get('date') or '')
    if session not in targets:
        continue
    try:
        value = float(row.get('closeadj'))
    except (TypeError, ValueError):
        value = float('nan')
    if math.isfinite(value) and value > 0:
        spy.add(session)
print(json.dumps({
    'sep_usable_securities': {s: len(seen[s]) for s in sessions},
    'spy_sessions': sorted(spy),
}))
'''.strip()
        result = self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel", "-c", code,
            ",".join(requested)], capture=True)
        probe = core._json_output(result, label="Sharadar publication probe")
        counts = probe.get("sep_usable_securities")
        spy = probe.get("spy_sessions")
        if (not isinstance(counts, dict) or not isinstance(spy, list)
                or set(counts) != set(requested)
                or any(not isinstance(counts[s], int) or counts[s] < 0
                       for s in requested)):
            raise core.DeployRefused(
                "Sharadar publication probe returned malformed evidence")
        ready = (
            all(counts[session] >= minimum_rows for session in requested)
            and set(spy) == set(requested))
        return {
            "ready": ready,
            "minimum_usable_securities": minimum_rows,
            "sep_usable_securities": {s: counts[s] for s in requested},
            "spy_sessions": sorted(str(item) for item in spy),
        }

    def _write_deployment_state(self, state: str, *, attempt: int,
                                failures, vendor_probe=None) -> None:
        """Retain the staged/waiting fact beside the deployment evidence."""
        payload = {
            "schema": core.DEPLOY_SCHEMA,
            "state": state,
            "updated_at": core._utc_text(core._utcnow()),
            "git_commit": self.commit,
            "attempt": int(attempt),
            "failures": list(failures or []),
        }
        if vendor_probe is not None:
            payload["vendor_probe"] = dict(vendor_probe)
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

    def _wait_for_data(self, verdict: Mapping, *, deadline: float,
                       panel_started: bool) -> None:
        """Wait until the current corpus is ready, without repeated full ingests."""
        attempt = 1
        while True:
            self._assert_wait_fence()
            # Recompute every pass. A configured wait may cross another market
            # close, or another process may have advanced the corpus meanwhile.
            verdict = self._readiness_verdict()
            if verdict.get("ready") is True:
                self._base_cli(["check-data"])
                self._write_deployment_state(
                    "DATA_READY", attempt=attempt, failures=[])
                return
            requirements = self._freshness_wait_requirements(verdict)
            if requirements is None:
                self._refuse_data_readiness(
                    verdict, attempt=attempt,
                    reason="data readiness left the retryable "
                           "vendor-publication state")
            sessions, minimum_rows = requirements
            failures = verdict.get("failures") or []
            detail = str(
                failures[0].get("detail") or "freshness is not current")
            probe = self._vendor_publication_probe(sessions, minimum_rows)
            self._write_deployment_state(
                "WAITING_FOR_DATA", attempt=attempt, failures=failures,
                vendor_probe=probe)

            print("\nDEPLOYMENT STAGED: WAITING_FOR_DATA", flush=True)
            print("  automation: disabled and kill switch engaged", flush=True)
            print("  reason: %s" % detail, flush=True)
            counts = ", ".join(
                "%s=%d/%d" % (
                    session, probe["sep_usable_securities"][session],
                    minimum_rows) for session in sessions)
            print("  vendor usable SEP: %s" % counts, flush=True)
            print("  vendor SPY sessions: %s" %
                  (", ".join(probe["spy_sessions"]) or "none"), flush=True)

            if probe.get("ready") is True:
                # One authoritative ingest after direct evidence says the missing
                # cross-section is materially usable. If that cannot make the
                # corpus ready, ordinary publication lag is no longer a valid
                # diagnosis and the deployment refuses rather than churning.
                self._base_cli(["feed-daily"])
                verdict = self._readiness_verdict()
                if verdict.get("ready") is True:
                    self._base_cli(["check-data"])
                    self._write_deployment_state(
                        "DATA_READY", attempt=attempt, failures=[])
                    print(
                        "  data readiness recovered; continuing the same "
                        "deployment attempt", flush=True)
                    return
                self._refuse_data_readiness(
                    verdict, attempt=attempt,
                    reason="Sharadar showed materially usable missing sessions "
                           "but the corpus remained unready after ingest")

            remaining = int(max(0, deadline - time.monotonic()))
            if remaining <= 0:
                raise core.DeployRefused(
                    "timed out waiting for current Sharadar data; automation "
                    "remains fenced")
            sleep_for = min(self.cfg.data_retry_seconds, remaining)
            print(
                "  probing vendor again in %ds (wait budget %ds)" %
                (sleep_for, remaining), flush=True)
            time.sleep(sleep_for)
            attempt += 1

    def refresh_data(self) -> None:
        """Refresh once, or wait read-only through ordinary post-close lag."""
        self.phase("data: current daily ingest and full readiness contract")
        deadline = time.monotonic() + self.cfg.data_wait_timeout_seconds
        self._assert_wait_fence()
        verdict = self._readiness_verdict()
        requirements = self._freshness_wait_requirements(verdict)

        if requirements is None:
            # Preserve ordinary deployment semantics: one daily refresh repairs
            # restatements and gives non-freshness ingest faults one normal chance
            # to resolve. Only subsequent freshness-only lag enters the wait.
            self._base_cli(["feed-daily"])
            verdict = self._readiness_verdict()
            if verdict.get("ready") is True:
                self._base_cli(["check-data"])
                self.runner.run(
                    self.base_compose + ["up", "-d", "sentinel-panel"])
                self._write_deployment_state(
                    "DATA_READY", attempt=1, failures=[])
                return
            requirements = self._freshness_wait_requirements(verdict)
            if requirements is None:
                self._refuse_data_readiness(
                    verdict, attempt=1,
                    reason="current data readiness failed outside the "
                           "retryable vendor-publication state")

        self.runner.run(self.base_compose + ["up", "-d", "sentinel-panel"])
        self._wait_for_data(verdict, deadline=deadline, panel_started=True)

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

        now = core._utcnow()
        not_before = now + core.timedelta(seconds=self.cfg.not_before_margin)
        candidate = self.attempt_dir / "empty-binding-candidate.json"
        cert = self.attempt_dir / "empty-binding-certificate.json"
        candidate_id = "empty-bind-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-empty-paper-binding-candidate",
            "--certificate-id", candidate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before", core._utc_text(not_before),
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
        # Close the liveness gap between the data phase and authority phase. If a
        # session closes while ownership verification is running, return to the
        # same safe vendor-wait path before asking the candidate's own final gate.
        verdict = self._readiness_verdict()
        if verdict.get("ready") is not True:
            if self._freshness_wait_requirements(verdict) is None:
                self._refuse_data_readiness(
                    verdict, attempt=1,
                    reason="data readiness changed before authority creation")
            deadline = time.monotonic() + self.cfg.data_wait_timeout_seconds
            self._wait_for_data(verdict, deadline=deadline, panel_started=True)
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
        self.phase("plan: prepare and re-read one exact durable paper plan")
        prepared = core._json_output(self._authorized_cli([
            "prepare-paper-plan", "--through", decision_session,
            "--warmup-sessions", "252", "--expect-account",
            self.cfg.account_id], capture=True), label="prepared paper plan")
        current = core._json_output(self._base_cli(
            ["current-paper-plan"], capture=True), label="current paper plan")
        prepared_plan = prepared.get("plan") or {}
        current_plan = current.get("plan") or {}
        if prepared_plan.get("decision_session") != decision_session:
            raise core.DeployRefused(
                "prepared plan decision session differs from signed warmup")
        if current.get("database_authorities_match") is not True:
            raise core.DeployRefused(
                "current plan database authorities do not match")
        if (not prepared_plan.get("plan_id")
                or current_plan.get("plan_id") != prepared_plan.get("plan_id")
                or current_plan.get("decision_session") != decision_session):
            raise core.DeployRefused(
                "current plan re-read is not the exact plan just prepared")

        self.phase(
            "automation: activate behind kill, start pinned service, then release")
        self._authorized_cli([
            "activate-paper-automation",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--confirm-old-writer-fenced", "--actor", self.cfg.actor,
            "--reason", "autonomous deployment",
            "--confirm-enable-unattended-alpaca-paper-automation"])
        self.runner.run(self._authorized_compose() + [
            "--profile", "automation", "up", "-d", "sentinel-automation"])
        killed = self._automation_status()
        if (killed.get("enabled") is not True
                or killed.get("kill_switch_engaged") is not True
                or killed.get("certificate_sha256") != certificate_sha256):
            raise core.DeployRefused(
                "automation did not start behind the expected kill fence")
        self._authorized_cli([
            "release-paper-automation-kill-switch",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--actor", self.cfg.actor,
            "--reason", "autonomous deployment verified",
            "--confirm-release-unattended-paper-kill-switch"])
        return current


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = core.argparse.ArgumentParser(
        description="Fully autonomous fail-closed Sentinel ALPACA PAPER deployment")
    parser.add_argument(
        "--explain", action="store_true",
        help="print the enforced deployment phases and exit without deployment")
    args = parser.parse_args(argv)
    if args.explain:
        print(
            "git ff-only -> account read -> build/test/push -> kill/stop -> "
            "backup/restore -> schema -> daily/readiness(wait freshness only) -> "
            "ownership -> signed certificate/key rotation -> prepare -> "
            "activate killed -> start -> release -> heartbeat proof -> "
            "post-deploy backup")
        return 0
    try:
        env = core.merged_environment()
        cfg = Config(env)
        if not (core.ROOT / ".git").exists():
            raise core.DeployRefused(
                "autonomous deploy must run from a Git checkout")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(core.ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False).stdout.strip()
        attempt = core._attempt_dir(
            cfg, head if core._HEX40.fullmatch(head) else "pending")
        runner = core.Runner(env, attempt / "commands.log")
        with core.DeploymentLock(
                cfg.authority_dir / "autonomous-deploy.lock"):
            AutonomousDeploy(cfg, runner, attempt).run()
        return 0
    except core.DeployRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("REFUSED: deployment interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
