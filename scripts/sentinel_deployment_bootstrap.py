#!/usr/bin/env python3
"""Provision first-install Sentinel secrets before Compose is allowed to resolve.

The supported GO and autonomous-deployment launchers call this helper before any
Compose-dependent phase.  Its only managed value is the independent publication
receipt HMAC authority introduced by the receipt-chain hardening.

A missing key may be generated automatically only after PostgreSQL proves that
no authenticated receipt row already exists.  A legacy/pre-receipt corpus is
safe: the schema migration records its current publication frontier as the
legacy prefix and only later publications require authenticated receipts.  If
any authenticated receipt exists, losing the key is recovery of an existing
secret, never permission to rotate it.

The key is generated with ``secrets``, written atomically to the existing .env
at mode 0600, never printed, and never passed on a command line.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import sys
import time
from typing import Callable, Dict, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
RECEIPT_KEY = "SENTINEL_PUBLICATION_RECEIPT_KEY"
MIN_KEY_BYTES = 32
DEFAULT_POSTGRES_TIMEOUT_SECONDS = 120

SAFE_FRESH_DATABASE = "SAFE_FRESH_DATABASE"
SAFE_LEGACY_DATABASE = "SAFE_LEGACY_DATABASE"
SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS = "SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS"
AUTHENTICATED_RECEIPTS_EXIST = "AUTHENTICATED_RECEIPTS_EXIST"

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PLACEHOLDER = re.compile(
    r"^(replace-with-.*|your_.*_here|changeme|xxx+|todo|<.*>|\.\.\.)$", re.I)


class BootstrapRefused(RuntimeError):
    pass


def _decode_value(raw: str) -> str:
    value = str(raw).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        value = value[1:-1]
        if quote == '"':
            value = value.replace('\\"', '"').replace("\\\\", "\\")
        return value
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def _parse_env(path: Path) -> Dict[str, str]:
    try:
        entry = path.lstat()
    except FileNotFoundError as exc:
        raise BootstrapRefused(
            ".env is missing; create the normal Sentinel environment first") from exc
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise BootstrapRefused(".env must be a regular non-symlink file")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BootstrapRefused(".env is unreadable") from exc

    values: Dict[str, str] = {}
    seen_receipt = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if _ENV_KEY.fullmatch(key) is None:
            continue
        if key == RECEIPT_KEY:
            seen_receipt += 1
        values[key] = _decode_value(value)
    if seen_receipt > 1:
        raise BootstrapRefused(
            "%s appears more than once in .env" % RECEIPT_KEY)
    return values


def _usable_key(value: object) -> bool:
    text = str(value or "").strip()
    return (
        bool(text)
        and _PLACEHOLDER.fullmatch(text) is None
        and len(text.encode("utf-8")) >= MIN_KEY_BYTES
    )


def _configured_key(values: Mapping[str, str]) -> Optional[str]:
    if RECEIPT_KEY in os.environ:
        external = str(os.environ.get(RECEIPT_KEY) or "").strip()
        if not _usable_key(external):
            raise BootstrapRefused(
                "%s is explicitly set in the process environment but is empty, "
                "a placeholder, or shorter than %d bytes; unset or restore it"
                % (RECEIPT_KEY, MIN_KEY_BYTES))
        return external

    file_value = str(values.get(RECEIPT_KEY) or "").strip()
    if not file_value or _PLACEHOLDER.fullmatch(file_value):
        return None
    if not _usable_key(file_value):
        raise BootstrapRefused(
            "%s in .env is shorter than %d bytes; refusing automatic rotation"
            % (RECEIPT_KEY, MIN_KEY_BYTES))
    return file_value


def _run(argv: Sequence[str], *, env: Mapping[str, str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [str(item) for item in argv], cwd=str(ROOT), env=dict(env),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            check=False)
    except OSError:
        return subprocess.CompletedProcess(
            [str(item) for item in argv], 127, stdout="", stderr="")


def _compose_args(env: Mapping[str, str]) -> Sequence[str]:
    completed = _run(
        ["bash", "scripts/sentinel-compose.sh", "--explain"], env=env)
    if completed.returncode != 0:
        raise BootstrapRefused(
            "Sentinel Compose graph could not be resolved while checking "
            "publication-receipt ancestry")
    try:
        args = shlex.split((completed.stdout or "").strip())
    except ValueError as exc:
        raise BootstrapRefused("Sentinel Compose graph output is malformed") from exc
    if not args or "-f" not in args:
        raise BootstrapRefused("Sentinel Compose graph is incomplete")
    return args


def _postgres_timeout(env: Mapping[str, str]) -> int:
    raw = str(env.get("SENTINEL_DEPLOY_BOOTSTRAP_POSTGRES_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_POSTGRES_TIMEOUT_SECONDS
    try:
        value = int(raw)
    except ValueError as exc:
        raise BootstrapRefused("deployment bootstrap PostgreSQL timeout is invalid") from exc
    if value < 1:
        raise BootstrapRefused("deployment bootstrap PostgreSQL timeout is invalid")
    return value


def _ensure_postgres_ready(env: Mapping[str, str], compose_args: Sequence[str]) -> None:
    prefix = ["docker", "compose", *[str(item) for item in compose_args]]
    started = _run(prefix + ["up", "-d", "sentinel-postgres"], env=env)
    if started.returncode != 0:
        raise BootstrapRefused(
            "Sentinel PostgreSQL could not be started for receipt-ancestry proof")

    selected = _run(prefix + ["ps", "-q", "sentinel-postgres"], env=env)
    ids = [line.strip() for line in (selected.stdout or "").splitlines() if line.strip()]
    if selected.returncode != 0 or len(ids) != 1:
        raise BootstrapRefused(
            "Sentinel PostgreSQL container identity is unavailable")

    deadline = time.monotonic() + float(_postgres_timeout(env))
    last_status = "unknown"
    while time.monotonic() < deadline:
        inspected = _run([
            "docker", "inspect", "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
            ids[0],
        ], env=env)
        if inspected.returncode != 0:
            raise BootstrapRefused("Sentinel PostgreSQL health is unavailable")
        last_status = (inspected.stdout or "").strip().lower() or "unknown"
        if last_status == "healthy":
            return
        if last_status in {"dead", "exited", "removing"}:
            raise BootstrapRefused(
                "Sentinel PostgreSQL exited before becoming healthy")
        time.sleep(1.0)
    raise BootstrapRefused(
        "Sentinel PostgreSQL did not become healthy within the bootstrap deadline "
        "(last status %s)" % last_status)


def _psql(env: Mapping[str, str], compose_args: Sequence[str], sql: str) -> str:
    completed = _run([
        "docker", "compose", *[str(item) for item in compose_args],
        "exec", "-T", "sentinel-postgres",
        "psql", "-U", "sentinel", "-d", "sentinel", "-AtX",
        "-v", "ON_ERROR_STOP=1", "-c", sql,
    ], env=env)
    if completed.returncode != 0:
        raise BootstrapRefused(
            "Sentinel PostgreSQL receipt-ancestry query did not complete")
    return (completed.stdout or "").strip()


def _receipt_ancestry(env: Mapping[str, str]) -> str:
    compose_args = _compose_args(env)
    _ensure_postgres_ready(env, compose_args)
    shape = _psql(
        env, compose_args,
        "SELECT "
        "(to_regclass('public.sentinel_corpus_publications') IS NOT NULL)::int"
        " || ':' || "
        "(to_regclass('public.sentinel_publication_validation_policy') IS NOT NULL)::int"
        " || ':' || "
        "(to_regclass('public.sentinel_publication_validation_receipts') IS NOT NULL)::int")
    if shape == "0:0:0":
        return SAFE_FRESH_DATABASE
    if shape == "1:0:0":
        return SAFE_LEGACY_DATABASE
    if shape != "1:1:1":
        raise BootstrapRefused(
            "publication receipt schema is partially installed; refusing key generation")

    policy = _psql(
        env, compose_args,
        "SELECT COUNT(*)::text || ':' || COALESCE(MIN(required_after_version),0)::text"
        " || ':' || COALESCE(MAX(required_after_version),0)::text"
        " FROM sentinel_publication_validation_policy")
    parts = policy.split(":")
    if len(parts) != 3:
        raise BootstrapRefused("publication receipt policy is malformed")
    try:
        policy_count, policy_min, policy_max = [int(item) for item in parts]
    except ValueError as exc:
        raise BootstrapRefused("publication receipt policy is malformed") from exc
    if policy_count != 1 or policy_min != policy_max or policy_min < 0:
        raise BootstrapRefused("publication receipt policy is missing or ambiguous")

    try:
        max_publication = int(_psql(
            env, compose_args,
            "SELECT COALESCE(MAX(version),0) FROM sentinel_corpus_publications"))
        receipt_rows = int(_psql(
            env, compose_args,
            "SELECT COUNT(*) FROM sentinel_publication_validation_receipts"))
    except ValueError as exc:
        raise BootstrapRefused("publication receipt ancestry is malformed") from exc
    if receipt_rows > 0:
        return AUTHENTICATED_RECEIPTS_EXIST
    if max_publication > policy_min:
        raise BootstrapRefused(
            "publication versions exist beyond the receipt policy boundary without "
            "authenticated receipt rows")
    return SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS


def _atomic_set_key(path: Path, generated: str) -> None:
    try:
        entry = path.lstat()
    except FileNotFoundError as exc:
        raise BootstrapRefused(".env disappeared during deployment bootstrap") from exc
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise BootstrapRefused(".env changed to an unsafe file type")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BootstrapRefused(".env became unreadable during deployment bootstrap") from exc

    out = []
    replaced = False
    for raw in lines:
        stripped = raw.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        name = candidate.split("=", 1)[0].strip() if "=" in candidate else None
        if name == RECEIPT_KEY:
            if replaced:
                raise BootstrapRefused(
                    "%s appeared more than once during bootstrap" % RECEIPT_KEY)
            out.append("%s=%s" % (RECEIPT_KEY, generated))
            replaced = True
        else:
            out.append(raw)
    if not replaced:
        if out and out[-1] != "":
            out.append("")
        out.append("# Generated by the supported Sentinel deployment bootstrap; preserve after first use.")
        out.append("%s=%s" % (RECEIPT_KEY, generated))

    temporary = path.with_name(".%s.bootstrap.%d" % (path.name, os.getpid()))
    fd = None
    try:
        fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write("\n".join(out) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        current = path.lstat()
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise BootstrapRefused(".env changed to an unsafe file type")
        os.replace(str(temporary), str(path))
        directory_fd = os.open(
            str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ensure_publication_receipt_key(
        path: Path = ENV_PATH,
        *, receipt_state_probe: Callable[[Mapping[str, str]], str] = _receipt_ancestry) -> str:
    values = _parse_env(path)
    configured = _configured_key(values)
    if configured is not None:
        return "PRESENT_EXTERNAL" if RECEIPT_KEY in os.environ else "PRESENT_FILE"

    generated = secrets.token_hex(32)
    probe_env = dict(values)
    probe_env.update(os.environ)
    # This temporary in-memory value exists only so Compose can resolve the
    # graph needed to inspect PostgreSQL. The postgres service itself does not
    # receive or consume publication-receipt authority.
    probe_env[RECEIPT_KEY] = generated
    state = receipt_state_probe(probe_env)
    if state == AUTHENTICATED_RECEIPTS_EXIST:
        raise BootstrapRefused(
            "%s is missing but authenticated publication receipts already exist; "
            "restore the original key from deployment secrets/backups"
            % RECEIPT_KEY)
    if state not in {
            SAFE_FRESH_DATABASE, SAFE_LEGACY_DATABASE,
            SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS}:
        raise BootstrapRefused("publication receipt ancestry returned an unknown state")
    _atomic_set_key(path, generated)
    return "GENERATED_" + state


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision first-install Sentinel deployment secrets")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = ensure_publication_receipt_key(args.env_file)
    except BootstrapRefused as exc:
        print("REFUSED: deployment bootstrap: %s" % exc, file=sys.stderr)
        return 2
    if result.startswith("GENERATED_"):
        print(
            "deployment bootstrap: generated and securely persisted publication receipt authority",
            flush=True)
    else:
        print("deployment bootstrap: publication receipt authority present", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
