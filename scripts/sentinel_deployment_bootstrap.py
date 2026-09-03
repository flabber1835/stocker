#!/usr/bin/env python3
"""Provision first-install Sentinel publication-receipt authority.

The supported GO and autonomous-deployment launchers call this helper before any
Compose-dependent phase. Automatic generation is allowed only while the
canonical PostgreSQL publication authority is locked and the database proves
that no authenticated receipt ancestry exists.

A database containing publications but no receipt-policy relations is ambiguous:
it may be a genuine pre-receipt deployment, or a receipt-era deployment that
lost authority tables. Automatic generation therefore refuses that shape. An
operator who has independently verified that the database predates authenticated
publication receipts can use ``--provision-verified-pre-receipt``. That explicit
attestation is accepted only for the exact legacy publication-only schema shape;
it does not bypass partial-schema or authenticated-receipt fences.

The generated key is written atomically to the existing .env at mode 0600,
never printed, and never passed on a command line. PostgreSQL is never started
for this proof until the durable-backup-target guard has passed.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import subprocess
import sys
import time
from typing import Callable, Dict, Iterator, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
RECEIPT_KEY = "SENTINEL_PUBLICATION_RECEIPT_KEY"
MIN_KEY_BYTES = 32
DEFAULT_POSTGRES_TIMEOUT_SECONDS = 120

# Must stay identical to sentinel.feed._publication_impl.CORPUS_LOCK_KEY.
# The bootstrap holds this exact exclusive advisory lock across the complete
# ancestry-check -> fsync(.env) transition, so canonical publication cannot
# create the first authenticated receipt under a different in-memory key.
CORPUS_LOCK_KEY = 0x5E27_C0B5

SAFE_FRESH_DATABASE = "SAFE_FRESH_DATABASE"
SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS = "SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS"
SAFE_VERIFIED_PRE_RECEIPT_DATABASE = "SAFE_VERIFIED_PRE_RECEIPT_DATABASE"
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


def _require_probe_prerequisites(env: Mapping[str, str]) -> None:
    password = str(env.get("SENTINEL_POSTGRES_PASSWORD") or "").strip()
    if not password or _PLACEHOLDER.fullmatch(password):
        raise BootstrapRefused(
            "SENTINEL_POSTGRES_PASSWORD is absent or still a placeholder; "
            "refusing to initialize PostgreSQL with a known credential")
    backup_dir = str(env.get("SENTINEL_BACKUP_DIR") or "").strip()
    if not backup_dir:
        raise BootstrapRefused(
            "SENTINEL_BACKUP_DIR is required before first-install secret bootstrap")


def _require_backup_target(env: Mapping[str, str]) -> None:
    completed = _run([
        "bash", "-c",
        ". scripts/sentinel-backup-lib.sh; sentinel_backup_root >/dev/null",
    ], env=env)
    if completed.returncode != 0:
        raise BootstrapRefused(
            "independently durable Sentinel backup target is not ready")


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
    raw = str(
        env.get("SENTINEL_DEPLOY_BOOTSTRAP_POSTGRES_TIMEOUT_SECONDS") or "").strip()
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


def _close_lock_process(process: subprocess.Popen, acquired: bool) -> None:
    if process.stdin is not None:
        if acquired and process.poll() is None:
            try:
                process.stdin.write(
                    "SELECT pg_advisory_unlock(%d);\n\\q\n" % CORPUS_LOCK_KEY)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        try:
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def _publication_authority_lock(
        env: Mapping[str, str],
        compose_args: Sequence[str]) -> Iterator[None]:
    """Hold the canonical corpus exclusive lock until the host key is durable.

    psql remains alive with stdin connected to this parent. If the parent dies,
    EOF closes the psql session and PostgreSQL releases the advisory lock.
    """
    token = secrets.token_hex(16)
    argv = [
        "docker", "compose", *[str(item) for item in compose_args],
        "exec", "-T", "sentinel-postgres",
        "psql", "-qAtX", "-U", "sentinel", "-d", "sentinel",
        "-v", "ON_ERROR_STOP=1",
    ]
    try:
        process = subprocess.Popen(
            argv, cwd=str(ROOT), env=dict(env),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
    except OSError as exc:
        raise BootstrapRefused(
            "Sentinel PostgreSQL publication-authority lock session could not start") from exc

    acquired = False
    try:
        if process.stdin is None or process.stdout is None:
            raise BootstrapRefused(
                "Sentinel PostgreSQL publication-authority lock pipes are unavailable")
        process.stdin.write(
            "SELECT CASE WHEN pg_try_advisory_lock(%d) "
            "THEN 'LOCKED:%s' ELSE 'BUSY:%s' END;\n"
            % (CORPUS_LOCK_KEY, token, token))
        process.stdin.flush()
        marker = process.stdout.readline().strip()
        if marker == "BUSY:" + token:
            raise BootstrapRefused(
                "corpus publication authority is busy; retry secret bootstrap "
                "after the active reader/publisher releases the corpus lock")
        if marker != "LOCKED:" + token:
            raise BootstrapRefused(
                "Sentinel PostgreSQL publication-authority lock was not proven")
        acquired = True
        yield
    finally:
        _close_lock_process(process, acquired)


def _receipt_ancestry_ready(
        env: Mapping[str, str], compose_args: Sequence[str], *,
        allow_verified_pre_receipt: bool = False) -> str:
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
        if allow_verified_pre_receipt:
            return SAFE_VERIFIED_PRE_RECEIPT_DATABASE
        raise BootstrapRefused(
            "publication history exists without receipt-policy authority; "
            "PostgreSQL alone cannot distinguish a verified pre-receipt database "
            "from receipt-era authority loss. Restore the missing receipt authority, "
            "or rerun this bootstrap with --provision-verified-pre-receipt only after "
            "independently verifying that the database predates authenticated receipts")
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


@contextmanager
def _receipt_ancestry_guard(
        env: Mapping[str, str], *,
        allow_verified_pre_receipt: bool = False) -> Iterator[str]:
    _require_probe_prerequisites(env)
    _require_backup_target(env)
    compose_args = _compose_args(env)
    _ensure_postgres_ready(env, compose_args)
    with _publication_authority_lock(env, compose_args):
        yield _receipt_ancestry_ready(
            env, compose_args,
            allow_verified_pre_receipt=allow_verified_pre_receipt)


def _receipt_ancestry(
        env: Mapping[str, str], *,
        allow_verified_pre_receipt: bool = False) -> str:
    """Diagnostic wrapper; generation uses _receipt_ancestry_guard directly."""
    with _receipt_ancestry_guard(
            env,
            allow_verified_pre_receipt=allow_verified_pre_receipt) as state:
        return state


def _current_file_key(path: Path) -> Optional[str]:
    values = _parse_env(path)
    value = str(values.get(RECEIPT_KEY) or "").strip()
    if not value or _PLACEHOLDER.fullmatch(value):
        return None
    if not _usable_key(value):
        raise BootstrapRefused(
            "%s changed during bootstrap to an invalid value" % RECEIPT_KEY)
    return value


def _atomic_set_key(path: Path, generated: str) -> str:
    """Persist generated, or adopt a valid key established after the first read."""
    try:
        entry = path.lstat()
    except FileNotFoundError as exc:
        raise BootstrapRefused(".env disappeared during deployment bootstrap") from exc
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
        raise BootstrapRefused(".env changed to an unsafe file type")
    try:
        original_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise BootstrapRefused(".env became unreadable during deployment bootstrap") from exc

    concurrent = _current_file_key(path)
    if concurrent is not None:
        try:
            os.chmod(str(path), 0o600)
        except OSError as exc:
            raise BootstrapRefused(
                ".env permissions could not be tightened during key adoption") from exc
        return concurrent

    lines = original_text.splitlines()
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
        out.append(
            "# Generated by the supported Sentinel deployment bootstrap; preserve after first use.")
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

        current_entry = path.lstat()
        if stat.S_ISLNK(current_entry.st_mode) or not stat.S_ISREG(current_entry.st_mode):
            raise BootstrapRefused(".env changed to an unsafe file type")
        try:
            current_text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BootstrapRefused(
                ".env became unreadable immediately before key commit") from exc
        if current_text != original_text:
            concurrent = _current_file_key(path)
            if concurrent is not None:
                try:
                    os.chmod(str(path), 0o600)
                except OSError as exc:
                    raise BootstrapRefused(
                        ".env permissions could not be tightened during key adoption") from exc
                return concurrent
            raise BootstrapRefused(
                ".env changed during publication-authority bootstrap; retry from "
                "the new host configuration")

        os.replace(str(temporary), str(path))
        directory_fd = os.open(
            str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        persisted = _current_file_key(path)
        if persisted != generated:
            raise BootstrapRefused(
                "publication receipt authority was not durably persisted as generated")
        return generated
    finally:
        if fd is not None:
            os.close(fd)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _persist_for_state(path: Path, generated: str, state: str) -> str:
    if state == AUTHENTICATED_RECEIPTS_EXIST:
        raise BootstrapRefused(
            "%s is missing but authenticated publication receipts already exist; "
            "restore the original key from deployment secrets/backups"
            % RECEIPT_KEY)
    if state not in {
            SAFE_FRESH_DATABASE,
            SAFE_RECEIPT_POLICY_WITHOUT_RECEIPTS,
            SAFE_VERIFIED_PRE_RECEIPT_DATABASE}:
        raise BootstrapRefused("publication receipt ancestry returned an unknown state")
    persisted = _atomic_set_key(path, generated)
    if persisted != generated:
        return "PRESENT_FILE_CONCURRENT"
    return "GENERATED_" + state


def ensure_publication_receipt_key(
        path: Path = ENV_PATH,
        *, receipt_state_probe: Optional[
            Callable[[Mapping[str, str]], str]] = None,
        allow_verified_pre_receipt: bool = False) -> str:
    values = _parse_env(path)
    configured = _configured_key(values)
    if configured is not None:
        return "PRESENT_EXTERNAL" if RECEIPT_KEY in os.environ else "PRESENT_FILE"

    generated = secrets.token_hex(MIN_KEY_BYTES)
    probe_env = dict(values)
    probe_env.update(os.environ)
    # Candidate exists only so Compose can resolve the graph. sentinel-postgres
    # does not consume publication-receipt authority.
    probe_env[RECEIPT_KEY] = generated

    # Injection is retained for hermetic unit tests. The production path always
    # uses the guarded context so the canonical corpus lock remains held through
    # _atomic_set_key() and its directory fsync.
    if receipt_state_probe is not None:
        state = receipt_state_probe(probe_env)
        return _persist_for_state(path, generated, state)

    with _receipt_ancestry_guard(
            probe_env,
            allow_verified_pre_receipt=allow_verified_pre_receipt) as state:
        return _persist_for_state(path, generated, state)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Provision first-install Sentinel deployment secrets")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument(
        "--provision-verified-pre-receipt",
        action="store_true",
        help=(
            "Operator attestation that existing publication history predates "
            "authenticated publication receipts. Accepted only for the exact "
            "legacy publication-only schema shape; never bypasses receipt-era "
            "or partial-schema authority fences."))
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = ensure_publication_receipt_key(
            args.env_file,
            allow_verified_pre_receipt=args.provision_verified_pre_receipt)
    except BootstrapRefused as exc:
        print("REFUSED: deployment bootstrap: %s" % exc, file=sys.stderr)
        return 2
    if result == "GENERATED_" + SAFE_VERIFIED_PRE_RECEIPT_DATABASE:
        print(
            "deployment bootstrap: generated and securely persisted publication "
            "receipt authority for operator-verified pre-receipt database",
            flush=True)
    elif result.startswith("GENERATED_"):
        print(
            "deployment bootstrap: generated and securely persisted publication receipt authority",
            flush=True)
    else:
        print("deployment bootstrap: publication receipt authority present", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())