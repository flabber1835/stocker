#!/usr/bin/env python3
"""Zero-guess bootstrap for the Sentinel fenced installer.

For an existing owned deployment this recovers facts that are already durable or
observable instead of requiring the operator to duplicate them into .env:

* deployment id and paper account id come from canonical PostgreSQL `status`;
* runtime registry repository comes from the existing automation container or a
  promoted local authorized image;
* the test repository defaults to the same namespace/name plus `-test`;
* signing key id is derived from the configured private key inside the exact new
  network-disabled test image and must match an ACTIVE committed trust root.

A private signing-key *path* is never guessed from arbitrary files. If no
explicit variable is set, only a short set of documented conventional secret
locations is considered, and exactly one must exist.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time
import sys
from typing import Dict, Mapping, Optional, Sequence
import urllib.error
import urllib.request

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_driver as hardened


_LOCAL_ONLY = frozenset({
    "sentinel", "sentinel-authorized", "sentinel-test", "latest",
})


def _run(argv, *, env, check=True):
    completed = subprocess.run(
        [str(x) for x in argv], cwd=str(core.ROOT), env=dict(env),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise core.DeployRefused(
            "bootstrap command failed: %s%s" % (
                " ".join(str(x) for x in argv),
                (" — " + " | ".join(detail[-3:])[:900]) if detail else ""))
    return completed


def _compose_args(env: Mapping[str, str]):
    result = _run(["bash", "scripts/sentinel-compose.sh", "--explain"], env=env)
    args = shlex.split(result.stdout.strip())
    if not args or "-f" not in args:
        raise core.DeployRefused("could not resolve the current Sentinel Compose graph")
    return ["docker", "compose"] + args


def _existing_status(env: Mapping[str, str]) -> Optional[Mapping]:
    """Read only the current canonical DB-backed status; absence is not guessed."""
    compose = _compose_args(env)
    result = _run(compose + [
        "--profile", "cli", "run", "--rm", "-T", "sentinel", "status"],
        env=env, check=False)
    if result.returncode != 0:
        return None
    # A successful but ambiguous identity observation is corruption, not
    # evidence of a fresh installation. Match the later integrity reader.
    return core._json_output(result, label='installed deployment discovery')


def _repository_from_image(reference: str) -> Optional[str]:
    value = str(reference or "").strip()
    if not value:
        return None
    if "@" in value:
        value = value.split("@", 1)[0]
    else:
        tail = value.rsplit("/", 1)[-1]
        if ":" in tail:
            value = value[:-(len(tail) - tail.rfind(":"))]
    if not value or value in _LOCAL_ONLY or "/" not in value:
        return None
    if re.search(r"\s", value):
        return None
    return value


def _existing_runtime_repository(env: Mapping[str, str]) -> Optional[str]:
    # Prefer the exact image reference of the existing unattended service. `-a`
    # matters: a deliberately killed/stopped deployment is still authoritative
    # evidence for where its last promoted runtime came from.
    ids = _run([
        "docker", "ps", "-aq",
        "--filter", "label=com.docker.compose.project=sentinel",
        "--filter", "label=com.docker.compose.service=sentinel-automation"],
        env=env, check=False).stdout.split()
    for container_id in ids:
        image = _run([
            "docker", "inspect", "--format", "{{.Config.Image}}", container_id],
            env=env, check=False)
        if image.returncode == 0:
            repo = _repository_from_image(image.stdout)
            if repo:
                return repo

    # Fallback to a locally promoted authorized image. RepoDigests are immutable
    # registry evidence; a plain `sentinel-authorized:latest` is not.
    inspected = _run([
        "docker", "image", "inspect", "sentinel-authorized:latest",
        "--format", "{{json .RepoDigests}}"], env=env, check=False)
    if inspected.returncode == 0:
        digests = core._json_value(inspected.stdout.encode('utf-8'),
                                  label='installed runtime repository discovery')
        if digests is None:
            return None  # Docker reports null for a local image without RepoDigests.
        if not isinstance(digests, list) or any(not isinstance(item, str) for item in digests):
            raise core.DeployRefused('installed runtime RepoDigests must be a string array')
        for item in digests:
            repo = _repository_from_image(item)
            if repo:
                return repo
    return None


def _signing_key_path(env: Mapping[str, str]) -> Optional[Path]:
    explicit = str(env.get("SENTINEL_DEPLOY_SIGNING_KEY_FILE", "")).strip()
    if explicit:
        return Path(explicit).expanduser()
    home = Path.home()
    conventional = [
        home / ".config" / "sentinel" / "signing-key.ed25519",
        home / ".config" / "sentinel" / "signing-key.pem",
        home / ".sentinel" / "signing-key.ed25519",
        home / ".sentinel" / "signing-key.pem",
    ]
    existing = [path for path in conventional if path.is_file()]
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        raise core.DeployRefused(
            "multiple conventional Sentinel signing keys exist; set "
            "SENTINEL_DEPLOY_SIGNING_KEY_FILE explicitly")
    return None


def discover(env: Mapping[str, str], *, installation_only: bool = False) -> Dict[str, str]:
    resolved = dict(env)
    status = _existing_status(resolved)
    if status and status.get("ownership") == "OWNED":
        deployment_id = str(status.get("deployment_id") or "").strip()
        account_id = str(status.get("broker_account_id") or "").strip()
        broker = str(status.get("broker") or "").strip()
        if broker != "alpaca" or not deployment_id or not account_id:
            raise core.DeployRefused(
                "existing OWNED status is incomplete or not the Alpaca binding")
        configured_deployment = str(resolved.get("SENTINEL_DEPLOYMENT_ID", "")).strip()
        configured_account = str(resolved.get("SENTINEL_PAPER_ACCOUNT_ID", "")).strip()
        if configured_deployment and configured_deployment != deployment_id:
            raise core.DeployRefused(
                "configured deployment id conflicts with canonical PostgreSQL binding")
        if configured_account and configured_account != account_id:
            raise core.DeployRefused(
                "configured paper account conflicts with canonical PostgreSQL binding")
        resolved["SENTINEL_DEPLOYMENT_ID"] = deployment_id
        resolved["SENTINEL_PAPER_ACCOUNT_ID"] = account_id

    if not str(resolved.get("SENTINEL_RUNTIME_IMAGE_REPOSITORY", "")).strip():
        repository = _existing_runtime_repository(resolved)
        if repository:
            resolved["SENTINEL_RUNTIME_IMAGE_REPOSITORY"] = repository
    runtime_repo = str(resolved.get("SENTINEL_RUNTIME_IMAGE_REPOSITORY", "")).strip()
    if runtime_repo and not str(resolved.get("SENTINEL_TEST_IMAGE_REPOSITORY", "")).strip():
        resolved["SENTINEL_TEST_IMAGE_REPOSITORY"] = runtime_repo + "-test"

    key = None if installation_only else _signing_key_path(resolved)
    if key is not None:
        resolved["SENTINEL_DEPLOY_SIGNING_KEY_FILE"] = str(key)
    if not str(resolved.get("SENTINEL_DEPLOY_SIGNING_KEY_ID", "")).strip():
        # BootstrapDeploy replaces AUTO with the private key's derived key id
        # before the transition boundary, after proving the root is ACTIVE.
        resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] = "AUTO"

    resolved.setdefault(
        "SENTINEL_AUTHORITY_ARTIFACTS_DIR", "artifacts/sentinel/authority")
    return resolved


def _backup_path(completed: subprocess.CompletedProcess) -> str:
    prefix = "verified_installation_backup:"
    values = [line[len(prefix):].strip() for line in (completed.stdout or '').splitlines()
              if line.startswith(prefix)]
    if len(values) == 1 and values[0]:
        return values[0]
    raise core.DeployRefused("base backup did not report its exact backup path")


def _safe_update_dotenv(path: Path, updates: Mapping[str, str]) -> None:
    """Atomically replace managed facts without weakening a secrets file.

    All duplicate managed assignments are collapsed to one value. Existing mode
    bits are preserved; a newly created .env starts at 0600.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    managed = {str(k): str(v) for k, v in updates.items()}
    emitted = set()
    out = []
    for line in lines:
        stripped = line.strip()
        candidate = re.sub(r"^export[ \t]+", "", stripped)
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else None
        if key in managed:
            if key not in emitted:
                out.append("%s=%s" % (key, managed[key]))
                emitted.add(key)
            continue
        out.append(line)
    remaining = sorted(set(managed) - emitted)
    if remaining:
        if out and out[-1] != "":
            out.append("")
        out.append("# Managed by scripts/sentinel-autonomous-deploy.sh after PASS.")
        out.extend("%s=%s" % (key, managed[key]) for key in remaining)

    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temporary = path.with_name(path.name + ".deploy.%d.tmp" % os.getpid())
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(str(temporary), mode)
        os.replace(str(temporary), str(path))
        directory_fd = os.open(
            str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class BootstrapDeploy(hardened.AutonomousDeploy):
    def read_paper_account(self) -> None:
        """Verify the exact account using the same cash-only contract as execution.

        Existing Sentinel redeploys may begin with positions; they do not need
        to be flat. Cash-only here means multiplier 1 and buying power equal to
        cash, which is the later preparation/execution contract as well.
        """
        self.phase("preflight: read-only Alpaca paper account identity")
        request = urllib.request.Request(
            core.PAPER_URL + "/v2/account",
            headers={
                "APCA-API-KEY-ID": core._require(self.env, "ALPACA_API_KEY"),
                "APCA-API-SECRET-KEY": core._require(
                    self.env, "ALPACA_SECRET_KEY"),
                "Accept": "application/json",
            }, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = core._json_value(response.read(), label='Alpaca paper account')
        except urllib.error.HTTPError as exc:
            if exc.code not in {401, 403, 408, 425, 429} and exc.code < 500:
                raise core.DeployRefused('Alpaca account protocol refused') from exc
            raise core.ActivationPending(
                "Alpaca paper account read returned HTTP %d" % exc.code) from exc
        except OSError as exc:
            raise core.ActivationPending(
                "Alpaca paper account read failed: %s" % type(exc).__name__) from exc
        core.require_canonical_paper_account(payload, self.cfg)
        if str(payload.get("status") or "").upper() != "ACTIVE":
            raise core.ActivationPending("Alpaca paper account is not ACTIVE")
        for flag in (
                "trading_blocked", "account_blocked",
                "trade_suspended_by_user"):
            if payload.get(flag) is not False:
                raise core.ActivationPending(
                    "Alpaca paper account flag %s is not false" % flag)
        try:
            multiplier = Decimal(str(payload["multiplier"]))
            equity = Decimal(str(payload["equity"]))
            cash = Decimal(str(payload["cash"]))
            buying_power = Decimal(str(payload["buying_power"]))
        except (KeyError, InvalidOperation) as exc:
            raise core.DeployRefused(
                "Alpaca paper account monetary fields are malformed") from exc
        if not all(x.is_finite() for x in (multiplier, equity, cash, buying_power)):
            raise core.DeployRefused(
                "Alpaca paper account contains non-finite monetary fields")
        if (multiplier != 1 or equity <= 0 or cash < 0 or buying_power < 0
                or abs(buying_power - cash) > Decimal("1.00")):
            raise core.ActivationPending(
                "Alpaca paper account does not satisfy Sentinel's cash-only execution contract")
        self.account_equity = equity

    def build_promote(self) -> None:
        if getattr(self, '_installation_only', False):
            from sentinel_installation_phase import InstallationDeploy
            return InstallationDeploy.build_promote(self)
        reviewed = self.reviewed_validation
        if (reviewed is not None
                and reviewed.test_image_digest == reviewed.runtime_image_digest):
            import sentinel_autonomous_deploy_ci_runtime as ci_runtime
            self.phase("select: exact signed CI runtime; no build, test rerun or push")
            self.resolve_compose()
            try:
                result = ci_runtime.verify_reviewed_runtime(
                    reviewed, env=self.env,
                    invoke=lambda argv, **kwargs: self.runner.run(
                        argv, capture=True, check=kwargs.get("check", False),
                        cwd=Path(kwargs["cwd"]), timeout=kwargs["timeout"]),
                    root=core.ROOT)
            except ci_runtime.CertifiedInstallRefused as exc:
                raise core.DeployRefused(str(exc)) from None
            self.runtime_repo_digest = str(result["certified_image"])
            self.runtime_digest = str(result["image_digest"])
            if self.runtime_repo_digest.split("@", 1)[0] != self.cfg.runtime_repository:
                raise core.DeployRefused("configured repository differs from signed runtime")
            self.test_repo_digest = self.runtime_repo_digest
            self.test_digest = self.runtime_digest
            self.cfg.test_repository = self.cfg.runtime_repository
            self._ci_single_runtime = True
            self.env.update({
                "SENTINEL_GIT_COMMIT": self.commit,
                "SENTINEL_RUNTIME_IMAGE_REF": self.runtime_repo_digest,
                "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
                "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
                "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
                "SENTINEL_FEED_AUTHORIZED": "DEPLOYED_REVIEWED_IMAGE_V1",
                "SENTINEL_FEED_SERVICE_MODE": "DEPLOY",
                "SENTINEL_FEED_GIT_COMMIT": self.commit,
                "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
                "SENTINEL_AUTHORITY_ARTIFACTS_DIR": str(self.cfg.authority_dir),
            })
            self.runner.env.update(self.env)
            (self.attempt_dir / "ci-certified-runtime.json").write_text(
                json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
            if reviewed.mode in {"dual", "paper"}:
                self._verify_signing_key_is_trusted()
                proof = core._json_output(self.runner.run(self._offline_tool_argv([], [
                    '-m', 'tools.sentinel_observation_authority', 'preflight']), capture=True),
                    label='selected observation issuer compatibility')
                if (proof.get('issuer_compatible') is not True
                        or proof.get('schema') not in {
                            'sentinel.paper-observation-warmup/2', 'sentinel.paper-observation-warmup/3',
                            'sentinel.paper-observation-warmup/4', 'sentinel.paper-observation-warmup/5',
                            'sentinel.paper-observation-warmup/6'}
                        or proof.get('feature_sessions') not in {252, 299}):
                    raise core.DeployRefused('selected observation issuer is incompatible')
            return
        super().build_promote()
        # From here onward even the ordinary read/write CLI service resolves to
        # the immutable runtime just promoted, rather than mutable sentinel:latest.
        self.env["SENTINEL_RUNTIME_IMAGE_REF"] = self.runtime_repo_digest
        self.runner.env["SENTINEL_RUNTIME_IMAGE_REF"] = self.runtime_repo_digest

    def _create_backup(self, *, restore_drill: bool, deadline=None) -> str:
        def run(argv, **kwargs):
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise core.DeployRefused("installation backup wait deadline exhausted")
                kwargs["timeout"] = remaining
            return self.runner.run(argv, **kwargs)

        created = run(
            ['bash', 'scripts/sentinel-install-backup.sh', '--restore',
             'full' if restore_drill else 'physical'], capture=True, stream=True)
        backup = _backup_path(created)
        return backup

    def quiesce_backup_and_migrate(self) -> None:
        first_kill = self._quiesce_database()
        code = (
            "import json,os; from sentinel import schema; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=3,statement_timeout_ms=5000);\n"
            "try:\n schema.require_runtime_schema(c); store.require_feed_schema(c)\n"
            "except schema.SchemaMigrationRefused:\n print(json.dumps({'schema_current':False}))\n"
            "else:\n print(json.dumps({'schema_current':True}))\n"
            "finally:\n c.rollback(); c.close()")
        proof = core._json_output(self.runner.run(self.base_compose + [
            '--profile', 'cli', 'run', '--rm', '-T', '--no-deps',
            '--entrypoint', 'python', 'sentinel', '-c', code], capture=True, timeout=30),
            label='installed schema compatibility')
        if type(proof.get('schema_current')) is not bool:
            raise core.DeployRefused('installed schema compatibility is malformed')
        if proof['schema_current']:
            self.phase('schema: unchanged; no migration, backup readiness check or replay')
        else:
            self.phase("durability: fresh pre-migration backup and physical replay")
            self._create_backup(restore_drill=False)
            self._migrate_schema()

        self._confirm_migrated_fence(first_kill)

    def _migrate_schema(self) -> None:
        self.phase("schema: explicit migration while automation is stopped")
        code = (
            "import os; from sentinel import schema,deployment_fence; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "deployment_fence.require(c); c.rollback(); "
            "schema.ensure_schema(c); store.migrate_schema(c); c.close(); "
            "print('schema migration PASS')")
        self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel", "-c", code])

    def _confirm_migrated_fence(self, first_kill) -> None:
        if not self._try_emergency_kill():
            raise core.DeployRefused(
                "durable automation kill could not be confirmed after schema migration")
        if not first_kill:
            print("  empty behavioral schema was proved before migration; durable kill is now confirmed")
        status_value = self._automation_status()
        if status_value.get("enabled"):
            self._base_cli([
                "deactivate-paper-automation", "--actor", self.cfg.actor,
                "--reason", "autonomous deployment configuration transition"])
            status_value = self._automation_status()
        if (status_value.get("enabled") is not False
                or status_value.get("kill_switch_engaged") is not True):
            raise core.DeployRefused(
                "automation did not reach disabled+killed deployment state")

    def _persist_deploy_facts(self, updates: Mapping[str, str]) -> None:
        _safe_update_dotenv(core.ENV_PATH, updates)

    def _post_deploy_backup(self) -> str:
        if getattr(self, '_activation_backup', None):
            return self._activation_backup
        return self._create_backup(restore_drill=True)

    def persist_success(self, health: Mapping) -> None:
        """Persist the exact reviewed activation mode after operational PASS."""
        self.phase("finalize: reuse verified recovery milestone, persist facts, and retain receipt")
        post_backup = self._post_deploy_backup()
        self.verify_operator_services()
        reviewed = self.reviewed_validation
        activation_mode = reviewed.mode if reviewed is not None else "paper"
        dual = activation_mode == "dual"
        receipt = {
            "schema": core.DEPLOY_SCHEMA,
            "completed_at": core._utc_text(core._utcnow()),
            "git_commit": self.commit,
            "runtime_image": self.runtime_repo_digest,
            "test_image": self.test_repo_digest,
            "deployment_id": self.cfg.deployment_id,
            "paper_account_id": self.cfg.account_id,
            "certificate_sha256": self.new_certificate,
            "predecessor_certificate_sha256": self.active_certificate or None,
            "control_generation": health.get("control_generation"),
            "leader_holder": health.get("leader_holder"),
            "fencing_token": health.get("fencing_token"),
            "leader_heartbeat_at": health.get("leader_heartbeat_at"),
            "policy_state": health.get("policy_state"),
            "operational_ready": health.get("operational_ready"),
            "activation_mode": activation_mode,
            "certified_performance_authority": (
                "BROKER_FREE_SHADOW_LEDGER" if dual else "PAPER_TRIAL"),
            "paper_accounting_authoritative": not dual,
            "post_deploy_backup": post_backup,
        }
        managed = {
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_REPOSITORY": self.cfg.test_repository,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
        }
        if reviewed is not None:
            managed.update({
                "SENTINEL_SHADOW_OBSERVATION_ENABLED": "1" if dual else "0",
                "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256": (
                    reviewed.source_identity_sha256),
                "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256": (
                    reviewed.bundle_sha256),
                "SENTINEL_REVIEWED_DEPLOYMENT_MODE": activation_mode,
                "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256": (
                    reviewed.shadow_configuration_sha256 or "" if dual else ""),
                "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256": (
                    reviewed.data_publication_sha256 or "" if dual else ""),
            })
            receipt.update({
                "reviewed_validation_bundle_sha256": reviewed.bundle_sha256,
                "validated_source_identity_sha256": reviewed.source_identity_sha256,
                "validated_shadow_config_sha256": (
                    reviewed.shadow_configuration_sha256 if dual else None),
                "validated_data_publication_sha256": (
                    reviewed.data_publication_sha256 if dual else None),
            })
        receipt['schema'] = 'sentinel.activation-receipt/1'
        path = self.attempt_dir / "activation-receipt.json"
        _safe_update_dotenv(core.ENV_PATH, managed)
        from sentinel_phase_records import publish_immutable
        publish_immutable(path, receipt)
        if dual:
            print(
                "\nDEPLOYMENT PASS: certified shadow plus reconciled Alpaca "
                "PAPER transport is operational")
            print(
                "performance authority: broker-free shadow ledger; PAPER "
                "accounting is display/reconciliation evidence only")
        else:
            print("\nDEPLOYMENT PASS: autonomous Alpaca PAPER trading is authorized and operational")
        print("receipt: %s" % path)

    def _verify_signing_key_is_trusted(self) -> None:
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
requested = sys.argv[1]
assert requested in {'AUTO', actual}, 'configured private key does not match key id'
root = load_trust_roots().get(actual)
assert root is not None, 'configured signing key is not a committed trust root'
assert root.status == 'ACTIVE', 'configured signing key is not an ACTIVE trust root'
now = datetime.now(timezone.utc)
assert root.not_before <= now < root.not_after, 'configured signing root is outside its validity interval'
print(actual)
'''.strip()
        completed = self.runner.run(self._offline_tool_argv(
            [key_mount], ["-c", code, self.cfg.signing_key_id]),
            capture=True)
        actual = (completed.stdout or "").strip().splitlines()[-1]
        if not actual.startswith("ed25519-sha256:"):
            raise core.DeployRefused("could not derive the Ed25519 signing key id")
        self.cfg.signing_key_id = actual


def _install_wallclock_independent_dual_overlay() -> None:
    """Extend this vetted bootstrap without changing the operator entrypoint."""
    # When executed as a script, bind the canonical module name to this exact
    # instance before importing the overlay. The overlay must patch the classes
    # and globals used by this running bootstrap, not a second imported copy.
    sys.modules.setdefault(
        "sentinel_autonomous_deploy_bootstrap", sys.modules[__name__])
    import sentinel_autonomous_deploy_install_entry as install_anytime  # noqa: PLC0415
    install_anytime._install_overlay()


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Every historical operator entry selects the same software-only boundary.
    from sentinel_installation_phase import main as installation_main
    return installation_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
