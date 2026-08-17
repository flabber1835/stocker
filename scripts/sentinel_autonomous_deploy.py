#!/usr/bin/env python3
"""Convergent, fail-closed deployment for Sentinel ALPACA PAPER automation.

The launcher fast-forwards Git before entering here.  This program then builds
and tests exact images, promotes them to immutable registry digests, fences the
old automation, verifies backup/restore, migrates schema explicitly, refreshes
current data, rotates renewable signed paper authority, starts automation behind
its kill switch, releases that switch only after all earlier gates pass, and
finally proves a live leader heartbeat.

It NEVER resets/reseeds the behavioral database, never deletes volumes, never
runs migrate-account, never guesses an account binding, and never turns an
inherited unbound book into an empty-account enrollment.  Any failure after the
transition boundary attempts the minimal emergency fence and stops the
unattended container before returning non-zero.

Host requirement: Python 3.8.15+.  Certificate signing itself happens in the
newly built, network-disabled Sentinel test image with the private key mounted
read-only, so the NAS host does not need the cryptography package.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
import urllib.error
import urllib.request


MIN_PYTHON = (3, 8, 15)
if sys.version_info < MIN_PYTHON:  # pragma: no cover - launcher checks first
    sys.stderr.write("REFUSED: autonomous deploy requires Python 3.8.15+\n")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
PAPER_URL = "https://paper-api.alpaca.markets"
DEPLOY_SCHEMA = "sentinel.autonomous-paper-deployment/1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class DeployRefused(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_bool(value: str, *, name: str) -> bool:
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    raise DeployRefused("%s must be 0/1 or true/false" % name)


def _int(value: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise DeployRefused("%s must be an integer" % name) from exc
    if parsed < minimum or parsed > maximum:
        raise DeployRefused(
            "%s must be in [%d, %d]" % (name, minimum, maximum))
    return parsed


def load_dotenv(path: Path) -> Dict[str, str]:
    """Read literal KEY=VALUE records without executing shell syntax.

    Process environment wins later.  Unquoted `#` remains part of a value on
    purpose: treating it as a comment can silently truncate a database password.
    """
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise DeployRefused("%s:%d is not KEY=VALUE" % (path, number))
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
            raise DeployRefused("%s:%d has an invalid variable name" % (path, number))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace("\\\"", '"').replace("\\\\", "\\")
        values[key] = value
    return values


def merged_environment(path: Path = ENV_PATH) -> Dict[str, str]:
    env = dict(load_dotenv(path))
    env.update(os.environ)
    return env


def _require(env: Mapping[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise DeployRefused("%s is required in .env or the process environment" % name)
    return value


def _resolve_repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class Config:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = dict(env)
        self.deployment_id = _require(env, "SENTINEL_DEPLOYMENT_ID")
        self.account_id = _require(env, "SENTINEL_PAPER_ACCOUNT_ID")
        self.runtime_repository = _require(env, "SENTINEL_RUNTIME_IMAGE_REPOSITORY")
        self.test_repository = _require(env, "SENTINEL_TEST_IMAGE_REPOSITORY")
        self.signing_key_id = _require(env, "SENTINEL_DEPLOY_SIGNING_KEY_ID")
        self.signing_key = _resolve_repo_path(
            _require(env, "SENTINEL_DEPLOY_SIGNING_KEY_FILE"))
        self.authority_dir = _resolve_repo_path(
            _require(env, "SENTINEL_AUTHORITY_ARTIFACTS_DIR"))
        self.actor = str(env.get(
            "SENTINEL_DEPLOY_ACTOR", "sentinel-autonomous-deploy")).strip()
        self.reviewer = str(env.get(
            "SENTINEL_DEPLOY_REVIEWER", self.actor)).strip()
        self.ticket_prefix = str(env.get(
            "SENTINEL_DEPLOY_TICKET_PREFIX", "autonomous-deploy")).strip()
        self.max_exposure = str(env.get(
            "SENTINEL_DEPLOY_MAXIMUM_EXPOSURE", "1")).strip()
        self.not_before_margin = _int(
            env.get("SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS", "120"),
            name="SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS",
            minimum=0, maximum=1800)
        self.health_timeout = _int(
            env.get("SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS", "300"),
            name="SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS",
            minimum=30, maximum=1800)
        self.allow_empty_bind = _as_bool(
            env.get("SENTINEL_DEPLOY_ALLOW_EMPTY_BIND", "0"),
            name="SENTINEL_DEPLOY_ALLOW_EMPTY_BIND")
        self.heartbeat_seconds = _int(
            env.get("SENTINEL_AUTOMATION_HEARTBEAT_SECONDS", "10"),
            name="SENTINEL_AUTOMATION_HEARTBEAT_SECONDS",
            minimum=1, maximum=300)

        if str(env.get("ALPACA_BASE_URL", PAPER_URL)).rstrip("/") != PAPER_URL:
            raise DeployRefused(
                "ALPACA_BASE_URL must be exactly %s for autonomous deployment" % PAPER_URL)
        for name in (
                "SENTINEL_POSTGRES_PASSWORD", "SENTINEL_BACKUP_DIR",
                "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "SHARADAR_API_KEY"):
            _require(env, name)
        if "@" in self.runtime_repository or "@" in self.test_repository:
            raise DeployRefused("image repositories must be mutable repository names, not digests")
        if not self.actor or not self.reviewer or not self.ticket_prefix:
            raise DeployRefused("deploy actor, reviewer, and ticket prefix must be non-empty")
        try:
            exposure = Decimal(self.max_exposure)
        except InvalidOperation as exc:
            raise DeployRefused("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE is not a decimal") from exc
        if not exposure.is_finite() or exposure < 0 or exposure > 1:
            raise DeployRefused("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE must be finite in [0,1]")
        if not self.signing_key.is_file():
            raise DeployRefused("signing key is not a readable file: %s" % self.signing_key)
        if _under(self.signing_key, ROOT):
            raise DeployRefused("private signing key must live outside the Git checkout")
        self.authority_dir.mkdir(parents=True, exist_ok=True)


class Runner:
    def __init__(self, env: Mapping[str, str], log_path: Path) -> None:
        self.env = dict(env)
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

    def run(self, argv: Sequence[str], *, check: bool = True,
            capture: bool = False, cwd: Path = ROOT) -> subprocess.CompletedProcess:
        argv = [str(item) for item in argv]
        stamp = _utc_text(_utcnow())
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write("\n[%s] $ %s\n" % (stamp, " ".join(shlex.quote(x) for x in argv)))
            log.flush()
        try:
            completed = subprocess.run(
                argv, cwd=str(cwd), env=self.env,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
                text=True, check=False)
        except OSError as exc:
            raise DeployRefused("could not execute %s: %s" % (argv[0], exc)) from exc
        if capture:
            with self.log_path.open("a", encoding="utf-8") as log:
                if completed.stdout:
                    log.write(completed.stdout)
                if completed.stderr:
                    log.write(completed.stderr)
        if check and completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            tail = " | ".join(detail[-4:])[:1200]
            raise DeployRefused(
                "command failed (%d): %s%s" % (
                    completed.returncode, " ".join(argv),
                    (" — " + tail) if tail else ""))
        return completed


class DeploymentLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise DeployRefused("another autonomous deployment holds %s" % self.path) from exc
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write("pid=%d started=%s\n" % (os.getpid(), _utc_text(_utcnow())))
        self.handle.flush()
        return self

    def __exit__(self, *_args):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _json_output(completed: subprocess.CompletedProcess, *, label: str) -> Mapping:
    try:
        value = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise DeployRefused("%s did not return JSON" % label) from exc
    if not isinstance(value, dict):
        raise DeployRefused("%s did not return a JSON object" % label)
    return value


def _repo_digest(value: str, expected_repository: str) -> Tuple[str, str]:
    value = value.strip()
    prefix = expected_repository + "@"
    if not value.startswith(prefix):
        raise DeployRefused("promotion returned a different repository: %s" % value)
    digest = value[len(prefix):]
    if _DIGEST.fullmatch(digest) is None:
        raise DeployRefused("promotion did not return an immutable SHA-256 digest")
    return value, digest


def validate_owned_status(status: Mapping, cfg: Config) -> str:
    state = status.get("ownership")
    if state == "UNKNOWN":
        raise DeployRefused("canonical account ownership is UNKNOWN")
    if state == "OWNED":
        if (status.get("broker") != "alpaca"
                or status.get("broker_account_id") != cfg.account_id
                or status.get("deployment_id") != cfg.deployment_id
                or not isinstance(status.get("takeover_epoch"), int)
                or int(status["takeover_epoch"]) < 1):
            raise DeployRefused(
                "durable OWNED binding does not match configured deployment/account")
        return "OWNED"
    if state == "NOT_OWNED":
        if not cfg.allow_empty_bind:
            raise DeployRefused(
                "account is NOT_OWNED; set SENTINEL_DEPLOY_ALLOW_EMPTY_BIND=1 only for a known empty new paper account")
        return "NOT_OWNED"
    raise DeployRefused("canonical ownership state is malformed: %r" % (state,))


def health_heartbeat_proof(first: Mapping, second: Mapping, *, cfg: Config,
                           certificate_sha256: str) -> None:
    for label, health in (("first", first), ("second", second)):
        if health.get("operational_ready") is not True:
            raise DeployRefused("%s health sample is not operationally ready" % label)
        if health.get("policy_state") != "LEADER_ACTIVE":
            raise DeployRefused("%s health sample has no active leader" % label)
        if (health.get("deployment_id") != cfg.deployment_id
                or health.get("broker_account_id") != cfg.account_id
                or health.get("certificate_sha256") != certificate_sha256
                or health.get("authority_verdict") != "PASS"
                or health.get("authority_lifecycle_current") is not True):
            raise DeployRefused("%s health sample authority identity is not exact" % label)
        if int(health.get("dead_letter_alerts") or 0) != 0:
            raise DeployRefused("%s health sample has dead-letter alerts" % label)
        if health.get("latest_cycle_state") == "BLOCKED" or health.get("latest_failure_code"):
            raise DeployRefused("%s health sample contains a latched automation failure" % label)
    for field in ("control_generation", "leader_holder", "fencing_token"):
        if not first.get(field) or first.get(field) != second.get(field):
            raise DeployRefused("leader proof changed %s between heartbeat samples" % field)
    before = first.get("leader_heartbeat_at")
    after = second.get("leader_heartbeat_at")
    if not before or not after or str(after) <= str(before):
        raise DeployRefused("leader heartbeat did not advance between health samples")


class AutonomousDeploy:
    def __init__(self, cfg: Config, runner: Runner, attempt_dir: Path) -> None:
        self.cfg = cfg
        self.runner = runner
        self.attempt_dir = attempt_dir
        self.env = runner.env
        self.commit = ""
        self.base_compose: List[str] = []
        self.automation_overlay = "docker-compose.sentinel-automation.yml"
        self.runtime_repo_digest = ""
        self.test_repo_digest = ""
        self.runtime_digest = ""
        self.test_digest = ""
        self.transition_started = False
        self.active_certificate = ""
        self.new_certificate = ""
        self.account_equity = Decimal(0)

    def phase(self, text: str) -> None:
        print("\n== %s" % text, flush=True)

    def git_preflight(self) -> None:
        self.phase("preflight: exact clean Git checkout")
        dirty = self.runner.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            capture=True).stdout.strip()
        if dirty:
            raise DeployRefused("working tree became dirty after fast-forward")
        branch = self.runner.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture=True).stdout.strip()
        target = self.env.get("SENTINEL_DEPLOY_GIT_BRANCH", "main")
        if branch != target:
            raise DeployRefused("checkout branch %s is not deployment branch %s" % (branch, target))
        self.commit = self.runner.run(
            ["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
        if _HEX40.fullmatch(self.commit) is None:
            raise DeployRefused("Git HEAD is not an exact 40-hex commit")

    def read_paper_account(self) -> None:
        self.phase("preflight: read-only Alpaca paper account identity")
        request = urllib.request.Request(
            PAPER_URL + "/v2/account",
            headers={
                "APCA-API-KEY-ID": _require(self.env, "ALPACA_API_KEY"),
                "APCA-API-SECRET-KEY": _require(self.env, "ALPACA_SECRET_KEY"),
                "Accept": "application/json",
            }, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise DeployRefused("Alpaca paper account read returned HTTP %d" % exc.code) from exc
        except (OSError, ValueError) as exc:
            raise DeployRefused("Alpaca paper account read failed: %s" % type(exc).__name__) from exc
        if not isinstance(payload, dict):
            raise DeployRefused("Alpaca account response is not an object")
        identities = {str(payload.get("id") or ""), str(payload.get("account_number") or "")}
        if self.cfg.account_id not in identities:
            raise DeployRefused("Alpaca credentials resolve to a different paper account")
        if str(payload.get("status") or "").upper() != "ACTIVE":
            raise DeployRefused("Alpaca paper account is not ACTIVE")
        for flag in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
            if payload.get(flag) is not False:
                raise DeployRefused("Alpaca paper account flag %s is not false" % flag)
        try:
            multiplier = Decimal(str(payload["multiplier"]))
            equity = Decimal(str(payload["equity"]))
            cash = Decimal(str(payload["cash"]))
            buying_power = Decimal(str(payload["buying_power"]))
        except (KeyError, InvalidOperation) as exc:
            raise DeployRefused("Alpaca paper account monetary fields are malformed") from exc
        if not all(x.is_finite() for x in (multiplier, equity, cash, buying_power)):
            raise DeployRefused("Alpaca paper account contains non-finite monetary fields")
        if multiplier != 1 or equity <= 0 or cash < 0 or buying_power < 0:
            raise DeployRefused("Alpaca paper account is not a positive cash-only account")
        if abs(buying_power - cash) > Decimal("1.00"):
            raise DeployRefused("Alpaca paper buying power differs from cash by more than $1")
        self.account_equity = equity

    def resolve_compose(self) -> None:
        explained = self.runner.run(
            ["bash", "scripts/sentinel-compose.sh", "--explain"], capture=True)
        args = shlex.split(explained.stdout.strip())
        if not args or "-f" not in args:
            raise DeployRefused("Sentinel Compose resolver returned no graph")
        self.base_compose = ["docker", "compose"] + args
        if any("nocpu" in part for part in args):
            generated = self.attempt_dir / "docker-compose.sentinel-automation.nocpu.yml"
            self.runner.run([
                self.env.get("SENTINEL_HOST_PYTHON", sys.executable),
                "scripts/sentinel_strip_cpu_limits.py",
                "docker-compose.sentinel-automation.yml", str(generated)])
            self.automation_overlay = str(generated)

    def build_promote(self) -> None:
        self.phase("build: exact Sentinel runtime, authorized runtime, and test lens")
        self.resolve_compose()
        self.runner.run(self.base_compose + [
            "build", "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
            "sentinel", "sentinel-panel"])
        self.runner.run([
            "docker", "build", "--network", "host",
            "--build-arg", "SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest",
            "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
            "-t", "sentinel-authorized:latest", "-f",
            "Dockerfile.sentinel-authorized", "."])
        self.runner.run([
            "docker", "build", "--network", "host",
            "--build-arg", "SENTINEL_IMAGE=sentinel-authorized:latest",
            "--build-arg", "SOURCE_GIT_SHA=" + self.commit,
            "-t", "sentinel-test:latest", "-f", "Dockerfile.sentinel-test", "."])

        build_record = self.attempt_dir / "image-build.json"
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "capture-build",
            "--git-commit", self.commit,
            "--runtime-ref", "sentinel-authorized:latest",
            "--test-ref", "sentinel-test:latest", "--output", str(build_record)])

        self.phase("test: complete Sentinel suite in the exact new test image")
        suite = self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "sentinel-test:latest", "tests/sentinel", "-q", "-ra"], capture=True)
        combined = (suite.stdout or "") + "\n" + (suite.stderr or "")
        summary = "\n".join(combined.strip().splitlines()[-4:])
        print(summary, flush=True)
        if re.search(r"(^|, )\d+ skipped(,| in |$)", combined, re.M):
            raise DeployRefused("complete Sentinel deployment suite skipped tests")

        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--entrypoint", "python", "sentinel-authorized:latest",
            "-m", "sentinel", "identity", "--require-certified"])
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "verify-build",
            "--record", str(build_record)])

        self.phase("promote: push exact image IDs and freeze immutable RepoDigests")
        runtime_tag = self.cfg.runtime_repository + ":" + self.commit
        test_tag = self.cfg.test_repository + ":" + self.commit
        self.runner.run(["docker", "tag", "sentinel-authorized:latest", runtime_tag])
        self.runner.run(["docker", "tag", "sentinel-test:latest", test_tag])
        self.runner.run(["docker", "push", runtime_tag])
        self.runner.run(["docker", "push", test_tag])
        promotion = self.attempt_dir / "image-promotion.json"
        self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "capture-promotion",
            "--build-record", str(build_record), "--runtime-tag", runtime_tag,
            "--test-tag", test_tag, "--output", str(promotion)])
        runtime = self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "resolve-promotion",
            "--record", str(promotion), "--git-commit", self.commit,
            "--kind", "runtime"], capture=True).stdout.strip()
        test = self.runner.run([
            sys.executable, "scripts/sentinel_certification_state.py", "resolve-promotion",
            "--record", str(promotion), "--git-commit", self.commit,
            "--kind", "test"], capture=True).stdout.strip()
        self.runtime_repo_digest, self.runtime_digest = _repo_digest(
            runtime, self.cfg.runtime_repository)
        self.test_repo_digest, self.test_digest = _repo_digest(
            test, self.cfg.test_repository)
        self.env.update({
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
            "SENTINEL_AUTHORITY_ARTIFACTS_DIR": str(self.cfg.authority_dir),
        })
        self.runner.env.update(self.env)
        self._verify_signing_key_is_trusted()

    def _verify_signing_key_is_trusted(self) -> None:
        code = (
            "import sys; from sentinel.authority import load_trust_roots; "
            "r=load_trust_roots().get(sys.argv[1]); "
            "assert r is not None and r.status == 'ACTIVE', "
            "'configured signing key is not an ACTIVE trust root'; print(r.key_id)")
        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--entrypoint", "python", "sentinel-test:latest",
            "-c", code, self.cfg.signing_key_id])

    def _running_automation_containers(self) -> List[str]:
        out = self.runner.run([
            "docker", "ps", "-q",
            "--filter", "label=com.docker.compose.project=sentinel",
            "--filter", "label=com.docker.compose.service=sentinel-automation"],
            capture=True).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _direct_stop_automation(self) -> None:
        ids = self._running_automation_containers()
        if ids:
            self.runner.run(["docker", "stop"] + ids)

    def _try_emergency_kill(self) -> bool:
        result = self.runner.run([
            "bash", "scripts/sentinel-emergency-kill.sh",
            "--actor", self.cfg.actor,
            "--reason", "autonomous deploy fail-closed fence"],
            capture=True, check=False)
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        return result.returncode == 0 or "already engaged" in text.lower()

    def fail_close(self) -> None:
        print("\n!! deployment failed after transition boundary; fencing automation", file=sys.stderr)
        try:
            if not self._try_emergency_kill():
                print("!! durable emergency fence could not be confirmed", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - best-effort emergency path
            print("!! emergency fence error: %s" % exc, file=sys.stderr)
        try:
            self._direct_stop_automation()
        except Exception as exc:  # noqa: BLE001
            print("!! automation stop error: %s" % exc, file=sys.stderr)

    @contextlib.contextmanager
    def transition(self):
        self.transition_started = True
        try:
            yield
        except BaseException:
            self.fail_close()
            raise

    def _base_cli(self, args: Sequence[str], *, capture: bool = False,
                  check: bool = True) -> subprocess.CompletedProcess:
        return self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T", "sentinel"]
            + list(args), capture=capture, check=check)

    def _authorized_compose(self) -> List[str]:
        return self.base_compose + ["-f", self.automation_overlay]

    def _authorized_cli(self, args: Sequence[str], *, capture: bool = False,
                        check: bool = True) -> subprocess.CompletedProcess:
        return self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "sentinel-authorized-cli"] + list(args), capture=capture, check=check)

    def _status(self) -> Mapping:
        return _json_output(self._base_cli(["status"], capture=True), label="status")

    def _automation_status(self) -> Mapping:
        return _json_output(
            self._base_cli(["automation-status"], capture=True),
            label="automation-status")

    def quiesce_backup_and_migrate(self) -> None:
        self.phase("transition: fence and stop old automation")
        first_kill = self._try_emergency_kill()
        self._direct_stop_automation()
        self.phase("transition: start only behavioral PostgreSQL on preserved volume")
        self.runner.run(self.base_compose + ["up", "-d", "sentinel-postgres"])

        self.phase("durability: fresh pre-migration base backup and restore drill")
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        self.runner.run(["bash", "scripts/sentinel-restore-drill.sh"])

        self.phase("schema: explicit migration while automation is stopped")
        code = (
            "import os; from sentinel import schema; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "schema.ensure_schema(c); c.close(); print('schema migration PASS')")
        self.runner.run(self.base_compose + [
            "--profile", "cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel", "-c", code])
        if not self._try_emergency_kill():
            raise DeployRefused(
                "durable automation kill could not be confirmed after schema migration")
        if not first_kill:
            print("  initial kill was unavailable; automation was stopped and durable kill is now confirmed")
        status = self._automation_status()
        if status.get("enabled"):
            self._base_cli([
                "deactivate-paper-automation", "--actor", self.cfg.actor,
                "--reason", "autonomous deployment configuration transition"])
            status = self._automation_status()
        if status.get("enabled") is not False or status.get("kill_switch_engaged") is not True:
            raise DeployRefused("automation did not reach disabled+killed deployment state")

    def refresh_data(self) -> None:
        self.phase("data: current daily ingest and full readiness contract")
        self._base_cli(["feed-daily"])
        self._base_cli(["check-data"])
        self.runner.run(self.base_compose + ["up", "-d", "sentinel-panel"])

    def _artifact_rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.cfg.authority_dir).as_posix()
        except ValueError as exc:
            raise DeployRefused("authority artifact escaped configured directory") from exc

    def _authorized_artifact(self, path: Path) -> str:
        return "/var/lib/sentinel-authority/" + self._artifact_rel(path)

    def _sign(self, *, tool: str, candidate: Path, output: Path,
              confirmation: str) -> str:
        key_mount = "type=bind,src=%s,dst=/signing-key,readonly" % self.cfg.signing_key
        auth_mount = "type=bind,src=%s,dst=/authority" % self.cfg.authority_dir
        candidate_in = "/authority/" + self._artifact_rel(candidate)
        output_in = "/authority/" + self._artifact_rel(output)
        self.runner.run([
            "docker", "run", "--rm", "--network", "none",
            "--mount", key_mount, "--mount", auth_mount,
            "--entrypoint", "python", "sentinel-test:latest",
            "-m", tool, "issue", "--candidate", candidate_in,
            "--private-key-file", "/signing-key", "--key-id",
            self.cfg.signing_key_id, "--output", output_in, confirmation])
        if not output.is_file():
            raise DeployRefused("offline signer did not create %s" % output)
        return hashlib.sha256(output.read_bytes()).hexdigest()

    def _wait_for(self, instant: str) -> None:
        boundary = datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        seconds = (boundary - datetime.now(timezone.utc)).total_seconds()
        if seconds > 0:
            print("  waiting %.0fs for signed not_before boundary" % seconds, flush=True)
            time.sleep(seconds + 1)

    def ensure_ownership(self) -> None:
        self.phase("ownership: verify canonical PostgreSQL account binding")
        status = self._status()
        state = validate_owned_status(status, self.cfg)
        if state == "OWNED":
            return
        self.phase("ownership: one-time strict empty-account enrollment")
        admin = status.get("administrative_authority") or {}
        highest = int(admin.get("highest_issuer_generation") or 0)
        generation = highest + 1
        now = _utcnow()
        not_before = now + timedelta(seconds=self.cfg.not_before_margin)
        candidate = self.attempt_dir / "empty-binding-candidate.json"
        cert = self.attempt_dir / "empty-binding-certificate.json"
        candidate_id = "empty-bind-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-empty-paper-binding-candidate",
            "--certificate-id", candidate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before", _utc_text(not_before),
            "--reviewer", self.cfg.reviewer,
            "--ticket", "%s-empty-%d" % (self.cfg.ticket_prefix, generation)],
            capture=True)
        candidate.write_text(result.stdout, encoding="utf-8")
        document = json.loads(result.stdout)
        actual_not_before = document["claims"]["not_before"]
        digest = self._sign(
            tool="tools.sentinel_empty_account_authority",
            candidate=candidate, output=cert,
            confirmation="--confirm-issue-empty-paper-binding")
        self._authorized_cli([
            "install-administrative-certificate", "--certificate",
            self._authorized_artifact(cert), "--confirm-certificate-sha256", digest,
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id, "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-install-administrative-certificate"])
        self._wait_for(actual_not_before)
        self._authorized_cli([
            "activate-administrative-certificate", "--certificate-sha256", digest,
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id, "--takeover-epoch", "1",
            "--reason", "autonomous strict-empty enrollment",
            "--confirm-activate-administrative-certificate"])
        inspected = _json_output(self._authorized_cli([
            "inspect-empty-paper-account", "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id], capture=True),
            label="empty account inspection")
        if (inspected.get("approval_ready") is not True
                or inspected.get("positions") != []
                or inspected.get("working_open_orders") != []):
            raise DeployRefused(
                "unbound account is not provably empty/stable; inherited books are never auto-migrated")
        self._authorized_cli([
            "bind-empty-paper-account", "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--notes", "autonomous strict-empty enrollment"])
        validate_owned_status(self._status(), self.cfg)

    def _execution_authority_state(self) -> Mapping:
        code = (
            "import json,os; from sentinel.feed import store; "
            "c=store.connect(os.environ['SENTINEL_DATABASE_URL']); "
            "cur=c.cursor(); cur.execute(\"SELECT COALESCE((SELECT highest_issuer_generation FROM sentinel_execution_authority_state WHERE id=1),0), (SELECT active_certificate_sha256 FROM sentinel_execution_authority_state WHERE id=1)\"); "
            "r=cur.fetchone(); print(json.dumps({'highest_issuer_generation':int(r[0]),'active_certificate_sha256':r[1]})); c.rollback(); c.close()")
        result = self.runner.run(self._authorized_compose() + [
            "--profile", "authorized-cli", "run", "--rm", "-T",
            "--entrypoint", "python", "sentinel-authorized-cli", "-c", code],
            capture=True)
        return _json_output(result, label="execution authority state")

    def rotate_observation_authority(self) -> Tuple[str, str]:
        self.phase("authority: build and offline-sign renewable paper observation lease")
        state = self._execution_authority_state()
        generation = int(state.get("highest_issuer_generation") or 0) + 1
        predecessor = state.get("active_certificate_sha256")
        if predecessor is not None and re.fullmatch(r"[0-9a-f]{64}", str(predecessor)) is None:
            raise DeployRefused("active execution certificate identity is malformed")
        now = _utcnow()
        not_before = now + timedelta(seconds=self.cfg.not_before_margin)
        candidate = self.attempt_dir / "paper-observation-candidate.json"
        cert = self.attempt_dir / "paper-observation-certificate.json"
        certificate_id = "paper-observation-%s-g%d" % (self.commit[:12], generation)
        result = self._authorized_cli([
            "create-paper-observation-candidate",
            "--certificate-id", certificate_id,
            "--issuer-generation", str(generation),
            "--deployment-id", self.cfg.deployment_id,
            "--expect-account", self.cfg.account_id,
            "--not-before", _utc_text(not_before),
            "--maximum-exposure", self.cfg.max_exposure,
            "--cash", str(self.account_equity),
            "--reviewer", self.cfg.reviewer,
            "--ticket", "%s-observation-%d" % (self.cfg.ticket_prefix, generation)],
            capture=True)
        candidate.write_text(result.stdout, encoding="utf-8")
        document = json.loads(result.stdout)
        claims = document["claims"]
        evidence = document["retained_evidence"]
        decision_session = evidence["warmup"]["decision_session"]
        actual_not_before = claims["not_before"]
        if claims.get("supersedes_certificate_sha256") != predecessor:
            raise DeployRefused("candidate predecessor differs from durable authority")
        digest = self._sign(
            tool="tools.sentinel_observation_authority",
            candidate=candidate, output=cert,
            confirmation="--confirm-issue-paper-observation-only")
        self._authorized_cli([
            "install-system-certificate", "--certificate",
            self._authorized_artifact(cert), "--confirm-certificate-sha256", digest,
            "--reason", "autonomous renewable paper observation deploy",
            "--confirm-install-alpaca-paper-execution-certificate"])
        self._wait_for(actual_not_before)
        if predecessor:
            self._authorized_cli([
                "rotate-system-certificate", "--certificate-sha256", digest,
                "--confirm-supersedes-certificate-sha256", str(predecessor),
                "--confirm-paper-account", self.cfg.account_id,
                "--confirm-deployment-id", self.cfg.deployment_id,
                "--reason", "autonomous renewable paper observation deploy",
                "--confirm-rotate-alpaca-paper-execution-certificate",
                "--confirm-controller-rollout"])
        else:
            self._authorized_cli([
                "activate-system-certificate", "--certificate-sha256", digest,
                "--confirm-paper-account", self.cfg.account_id,
                "--confirm-deployment-id", self.cfg.deployment_id,
                "--reason", "autonomous first paper observation deploy",
                "--confirm-activate-alpaca-paper-execution-certificate",
                "--confirm-controller-rollout"])
        self.active_certificate = str(predecessor or "")
        self.new_certificate = digest
        return digest, decision_session

    def prepare_activate_start(self, certificate_sha256: str,
                               decision_session: str) -> Mapping:
        self.phase("plan: prepare one current durable paper plan")
        prepared = _json_output(self._authorized_cli([
            "prepare-paper-plan", "--through", decision_session,
            "--warmup-sessions", "252", "--expect-account", self.cfg.account_id],
            capture=True), label="prepared paper plan")
        current = _json_output(self._base_cli(
            ["current-paper-plan"], capture=True), label="current paper plan")
        plan = prepared.get("plan") or {}
        if plan.get("decision_session") != decision_session:
            raise DeployRefused("prepared plan decision session differs from signed warmup")
        if current.get("database_authorities_match") is False:
            raise DeployRefused("current plan database authorities do not match")

        self.phase("automation: activate behind kill, start pinned service, then release")
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
            raise DeployRefused("automation did not start behind the expected kill fence")
        self._authorized_cli([
            "release-paper-automation-kill-switch",
            "--confirm-paper-account", self.cfg.account_id,
            "--confirm-deployment-id", self.cfg.deployment_id,
            "--confirm-certificate-sha256", certificate_sha256,
            "--actor", self.cfg.actor, "--reason", "autonomous deployment verified",
            "--confirm-release-unattended-paper-kill-switch"])
        return current

    def _wait_operational(self) -> Mapping:
        deadline = time.monotonic() + self.cfg.health_timeout
        last = None
        while time.monotonic() < deadline:
            last = self._automation_status()
            if (last.get("operational_ready") is True
                    and last.get("policy_state") == "LEADER_ACTIVE"):
                return last
            if last.get("latest_cycle_state") == "BLOCKED" or last.get("latest_failure_code"):
                raise DeployRefused("automation latched a failure while becoming operational")
            time.sleep(3)
        raise DeployRefused(
            "automation did not become operational before timeout; last policy=%r" %
            ((last or {}).get("policy_state"),))

    def verify_operational(self, certificate_sha256: str) -> Mapping:
        self.phase("prove: active leader, exact authority, and advancing heartbeat")
        first = self._wait_operational()
        time.sleep(self.cfg.heartbeat_seconds + 2)
        second = self._automation_status()
        health_heartbeat_proof(
            first, second, cfg=self.cfg,
            certificate_sha256=certificate_sha256)
        status = self._status()
        validate_owned_status(status, self.cfg)
        authority = status.get("paper_execution_authority") or {}
        if (authority.get("authority_mode") != "PAPER_OBSERVATION_ONLY"
                or authority.get("lifecycle_current") is not True):
            raise DeployRefused("final status does not show current PAPER_OBSERVATION_ONLY authority")
        return second

    def persist_success(self, health: Mapping) -> None:
        self.phase("finalize: persist immutable deploy facts and post-deploy backup")
        update_dotenv(ENV_PATH, {
            "SENTINEL_GIT_COMMIT": self.commit,
            "SENTINEL_RUNTIME_IMAGE_REPOSITORY": self.cfg.runtime_repository,
            "SENTINEL_RUNTIME_IMAGE_DIGEST": self.runtime_digest,
            "SENTINEL_TEST_IMAGE_REPOSITORY": self.cfg.test_repository,
            "SENTINEL_TEST_IMAGE_DIGEST": self.test_digest,
        })
        self.runner.run(["bash", "scripts/sentinel-base-backup.sh"])
        self.runner.run(["bash", "scripts/sentinel-backup-status.sh"])
        receipt = {
            "schema": DEPLOY_SCHEMA,
            "completed_at": _utc_text(_utcnow()),
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
        }
        path = self.attempt_dir / "deployment-receipt.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        print("\nDEPLOYMENT PASS: autonomous Alpaca PAPER trading is authorized and operational")
        print("receipt: %s" % path)

    def run(self) -> None:
        self.git_preflight()
        self.read_paper_account()
        self.build_promote()
        with self.transition():
            self.quiesce_backup_and_migrate()
            self.refresh_data()
            self.ensure_ownership()
            certificate, session = self.rotate_observation_authority()
            self.prepare_activate_start(certificate, session)
            health = self.verify_operational(certificate)
            self.persist_success(health)


def update_dotenv(path: Path, updates: Mapping[str, str]) -> None:
    """Atomically update only named non-secret deploy facts, preserving .env."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict((str(k), str(v)) for k, v in updates.items())
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        if "=" in candidate:
            key = candidate.split("=", 1)[0].strip()
            if key in remaining:
                out.append("%s=%s" % (key, remaining.pop(key)))
                continue
        out.append(line)
    if remaining:
        if out and out[-1] != "":
            out.append("")
        out.append("# Managed by scripts/sentinel-autonomous-deploy.sh after PASS.")
        for key in sorted(remaining):
            out.append("%s=%s" % (key, remaining[key]))
    temporary = path.with_name(path.name + ".deploy.tmp")
    temporary.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def _attempt_dir(cfg: Config, commit_hint: str = "pending") -> Path:
    stamp = _utcnow().strftime("%Y%m%dT%H%M%SZ")
    base = cfg.authority_dir / "deployments"
    base.mkdir(parents=True, exist_ok=True)
    path = base / (stamp + "-" + commit_hint[:12])
    counter = 0
    while path.exists():
        counter += 1
        path = base / (stamp + "-" + commit_hint[:12] + "-%d" % counter)
    path.mkdir(mode=0o700)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fully autonomous fail-closed Sentinel ALPACA PAPER deployment")
    parser.add_argument(
        "--explain", action="store_true",
        help="print the enforced deployment phases and exit without deployment")
    args = parser.parse_args(argv)
    if args.explain:
        print("git ff-only -> account read -> build/test/push -> kill/stop -> "
              "backup/restore -> schema -> daily/readiness -> ownership -> "
              "signed certificate rotate -> prepare -> activate killed -> start -> "
              "release -> heartbeat proof -> post-deploy backup")
        return 0
    try:
        env = merged_environment()
        cfg = Config(env)
        if not (ROOT / ".git").exists():
            raise DeployRefused("autonomous deploy must run from a Git checkout")
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False).stdout.strip()
        attempt = _attempt_dir(cfg, head if _HEX40.fullmatch(head) else "pending")
        runner = Runner(env, attempt / "commands.log")
        with DeploymentLock(cfg.authority_dir / "autonomous-deploy.lock"):
            AutonomousDeploy(cfg, runner, attempt).run()
        return 0
    except DeployRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("REFUSED: deployment interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
