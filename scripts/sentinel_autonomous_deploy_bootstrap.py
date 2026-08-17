#!/usr/bin/env python3
"""Zero-guess bootstrap for the autonomous Sentinel paper deployer.

For an existing owned deployment this recovers facts that are already durable or
observable instead of requiring the operator to duplicate them into .env:

* deployment id and paper account id come from canonical PostgreSQL `status`;
* runtime registry repository comes from the existing automation container or a
  promoted local authorized image;
* the test repository defaults to the same namespace/name plus `-test`;
* signing key id is derived from the configured private key inside the exact new
  network-disabled test image and must match an ACTIVE committed trust root.

A private signing-key *path* is never guessed from arbitrary files.  If no
explicit variable is set, only a short set of documented conventional secret
locations is considered, and exactly one must exist.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Dict, Mapping, Optional, Sequence

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
    try:
        compose = _compose_args(env)
        result = _run(compose + [
            "--profile", "cli", "run", "--rm", "-T", "sentinel", "status"],
            env=env, check=False)
        if result.returncode != 0:
            return None
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else None
    except (core.DeployRefused, json.JSONDecodeError):
        return None


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
    # Prefer the exact image reference of the existing unattended service.  `-a`
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

    # Fallback to a locally promoted authorized image.  RepoDigests are
    # immutable registry evidence; a plain `sentinel-authorized:latest` is not.
    inspected = _run([
        "docker", "image", "inspect", "sentinel-authorized:latest",
        "--format", "{{json .RepoDigests}}"], env=env, check=False)
    if inspected.returncode == 0:
        try:
            digests = json.loads(inspected.stdout)
        except json.JSONDecodeError:
            digests = []
        for item in digests or []:
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


def discover(env: Mapping[str, str]) -> Dict[str, str]:
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

    key = _signing_key_path(resolved)
    if key is not None:
        resolved["SENTINEL_DEPLOY_SIGNING_KEY_FILE"] = str(key)
    if not str(resolved.get("SENTINEL_DEPLOY_SIGNING_KEY_ID", "")).strip():
        # HardenedDeploy replaces AUTO with the private key's derived key id
        # before the transition boundary, after proving the root is ACTIVE.
        resolved["SENTINEL_DEPLOY_SIGNING_KEY_ID"] = "AUTO"

    resolved.setdefault(
        "SENTINEL_AUTHORITY_ARTIFACTS_DIR", "artifacts/sentinel/authority")
    return resolved


class BootstrapDeploy(hardened.AutonomousDeploy):
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
        completed = self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--mount", key_mount, "--entrypoint", "python",
            "sentinel-test:latest", "-c", code, self.cfg.signing_key_id],
            capture=True)
        actual = (completed.stdout or "").strip().splitlines()[-1]
        if not actual.startswith("ed25519-sha256:"):
            raise core.DeployRefused("could not derive the Ed25519 signing key id")
        self.cfg.signing_key_id = actual


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = core.argparse.ArgumentParser(
        description="Bootstrap and fully deploy Sentinel ALPACA PAPER")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args(argv)
    if args.explain:
        print(
            "discover existing durable identity -> git/build/test/push -> "
            "kill/backup/schema/data -> certificate/key rotation -> plan -> "
            "activate killed -> start -> release -> heartbeat proof")
        return 0
    try:
        env = discover(core.merged_environment())
        # Process environment is authoritative to the underlying core/driver;
        # do not write discovered facts to .env until the final PASS receipt.
        os.environ.update(env)
        cfg = hardened.Config(env)
        if not (core.ROOT / ".git").exists():
            raise core.DeployRefused(
                "autonomous deploy must run from a Git checkout")
        head = _run(["git", "rev-parse", "HEAD"], env=env).stdout.strip()
        attempt = core._attempt_dir(
            cfg, head if core._HEX40.fullmatch(head) else "pending")
        runner = core.Runner(env, attempt / "commands.log")
        with core.DeploymentLock(
                cfg.authority_dir / "autonomous-deploy.lock"):
            BootstrapDeploy(cfg, runner, attempt).run()
        return 0
    except core.DeployRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("REFUSED: deployment interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
