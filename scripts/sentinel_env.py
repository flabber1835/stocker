#!/usr/bin/env python3
"""Bounded, literal host env ingestion and side-effect-free preflight (Python 3.8+)."""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import stat
import sys
import unicodedata
from typing import Dict, Mapping, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
COMPLETE = b"SENTINEL_ENV_COMPLETE_V1\0"
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
PLACEHOLDER = re.compile(
    r"(?:replace-with-.*|your_.*_here|changeme|xxx+|todo|<.*>|\.\.\.)\Z", re.I)
PAPER_URL = "https://paper-api.alpaca.markets"
RECEIPT_KEY = "SENTINEL_PUBLICATION_RECEIPT_KEY"
TARGETS = ("SHADOW", "DUAL_RUN_OBSERVATION", "HISTORICAL_PAPER_EXECUTION")
UNSAFE_KEYS = frozenset({
    "BASH_ENV", "ENV", "IFS", "SHELLOPTS", "BASHOPTS", "CDPATH", "PATH",
    "PYTHON", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
    "SENTINEL_HOST_PYTHON", "SENTINEL_PYTHON", "SENTINEL_REPO_ROOT",
    "SENTINEL_DEPLOY_LOCK_FD", "SENTINEL_GO_LOCK_HELD", "SENTINEL_GO_LOCK_FD",
    "SENTINEL_GO_RUN_TOKEN", "SENTINEL_BASE_BACKUP_LOCK_HELD",
    "SENTINEL_BASE_BACKUP_LOCK_FD", "SENTINEL_BASE_BACKUP_LOCK_ROOT",
    "SENTINEL_FEED_AUTHORIZED", "SENTINEL_FEED_SERVICE_MODE",
    "SENTINEL_FEED_GIT_COMMIT", "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST",
    "SENTINEL_AUTHORIZED_RUNTIME", "SENTINEL_RUNTIME_BACKUP_AUTHORITY",
    "SENTINEL_RECOVERED_ORDER_AUTHORITY",
})
FILE_PREFIXES = ("SENTINEL_", "SHARADAR_", "ALPACA_", "NDL_")
FILE_EXTRA_KEYS = frozenset({
    "GITHUB_TOKEN", "GH_TOKEN", "COMPOSE_DISABLE_ENV_FILE", "COMPOSE_ENV_FILES",
})
HEX64_OR_EMPTY = re.compile(r"(?:|[0-9a-f]{64})\Z")
OBSERVATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,63}\Z")
PUBLICATION_POLICY = (
    "SHARADAR_SEP_SFP_SECOND_UPDATE_PLUS_15M_2345_AMERICA_NEW_YORK_V1")
INTEGER_BOUNDS = {
    "SENTINEL_MAX_CYCLES": (1, 1000000),
    "SENTINEL_SHADOW_POLL_SECONDS": (1, 86400),
    "SENTINEL_SHADOW_ADVANCE_DEADLINE_SECONDS": (1, 86400),
    "SENTINEL_DEPLOY_BOOTSTRAP_POSTGRES_TIMEOUT_SECONDS": (1, 1800),
    "SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS": (0, 1800),
    "SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS": (30, 1800),
    "SENTINEL_DEPLOY_DATA_RETRY_SECONDS": (30, 3600),
    "SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS": (300, 86400),
    "SENTINEL_AUTOMATION_PUBLICATION_DELAY_SECONDS": (0, 86400),
    "SENTINEL_AUTOMATION_EXECUTION_DELAY_SECONDS": (0, 3600),
    "SENTINEL_AUTOMATION_LEASE_SECONDS": (1, 3600),
    "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": (1, 300),
    "SENTINEL_AUTOMATION_CONTROL_POLL_SECONDS": (1, 300),
    "SENTINEL_AUTOMATION_RETRY_BASE_SECONDS": (1, 3600),
    "SENTINEL_AUTOMATION_RETRY_MAX_SECONDS": (1, 86400),
    "SENTINEL_AUTOMATION_CALLBACK_DEADLINE_SECONDS": (1, 86400),
    "SENTINEL_AUTOMATION_REFRESH_MAX_ATTEMPTS": (1, 1000),
    "SENTINEL_AUTOMATION_PREFLIGHT_RECOVER_MAX_ATTEMPTS": (1, 1000),
    "SENTINEL_AUTOMATION_PREPARE_MAX_ATTEMPTS": (1, 1000),
    "SENTINEL_AUTOMATION_EXECUTE_MAX_ATTEMPTS": (1, 1000),
    "SENTINEL_AUTOMATION_RECOVER_MAX_ATTEMPTS": (1, 1000),
    "SENTINEL_AUTOMATION_ALERT_CLAIM_SECONDS": (1, 3600),
    "SENTINEL_AUTOMATION_ALERT_MAX_ATTEMPTS": (1, 10000000),
    "SENTINEL_AUTOMATION_SUPERVISOR_POLL_SECONDS": (1, 300),
    "SENTINEL_AUTOMATION_SUPERVISOR_STARTUP_GRACE_SECONDS": (0, 3600),
    "SENTINEL_AUTOMATION_ALERT_WEBHOOK_TIMEOUT_SECONDS": (1, 300),
    "SENTINEL_AUTOMATION_ALERT_POLL_SECONDS": (1, 300),
    "SENTINEL_AUTOMATION_ALERT_PROBE_SECONDS": (1, 86400),
    "SENTINEL_AUTOMATION_ALERT_MAX_CONSECUTIVE_FAILURES": (1, 1000),
    "SENTINEL_AUTOMATION_ALERT_HEALTH_MAX_AGE_SECONDS": (1, 3600),
    "SENTINEL_AUTOMATION_ALERT_STARTUP_GRACE_SECONDS": (0, 3600),
}
DECIMAL_BOUNDS = {
    "SENTINEL_POLL_SECONDS": (Decimal("0.001"), Decimal("3600")),
    "SENTINEL_BACKUP_MAX_AGE_HOURS": (Decimal("0.001"), Decimal("8760")),
    "SENTINEL_SHADOW_STARTING_CASH": (Decimal("0.01"), Decimal("1000000000000000")),
}
EXACT_BOOLEAN_KEYS = frozenset({
    "SENTINEL_FORCE_CPU_LIMITS",
    "SENTINEL_FORCE_NO_CPU_LIMITS",
    "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED",
    "SENTINEL_SHADOW_OBSERVATION_ENABLED",
})
FLEX_BOOLEAN_KEYS = frozenset({
    "SENTINEL_DEPLOY_ALLOW_EMPTY_BIND",
    "SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY",
})
SHA256_KEYS = frozenset({
    "SENTINEL_SHADOW_REGENESIS_APPROVAL_SHA256",
    "SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256",
    "SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256",
    "SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256",
    "SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256",
})


class EnvRefused(ValueError):
    """Only safe metadata belongs in this exception's message."""


def _fail(code: str, *, line: Optional[int] = None, key: str = "") -> None:
    suffix = " at line %d" % line if line is not None else ""
    if key and KEY.fullmatch(key):
        suffix += " (%s)" % key
    raise EnvRefused(".env %s%s" % (code, suffix))


def _identity(entry):
    return (entry.st_dev, entry.st_ino, entry.st_mode, entry.st_size,
            entry.st_mtime_ns, entry.st_ctime_ns)


def read_bytes(path: Path, *, required: bool = False) -> bytes:
    """Read one stable regular-file observation; special files cannot block."""
    fd = None
    try:
        try:
            before = path.lstat()
        except FileNotFoundError:
            if required:
                _fail("MISSING_FILE")
            return b""
        if not stat.S_ISREG(before.st_mode):
            _fail("UNSAFE_FILE_TYPE; expected regular non-symlink file")
        if not before.st_mode & 0o444:
            _fail("UNREADABLE_FILE")
        if before.st_size > MAX_BYTES:
            _fail("FILE_TOO_LARGE")
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        opened = os.fstat(fd)
        if _identity(opened) != _identity(before):
            _fail("FILE_CHANGED_DURING_READ")
        chunks = []
        size = 0
        while size <= MAX_BYTES:
            block = os.read(fd, min(65536, MAX_BYTES + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        if size > MAX_BYTES:
            _fail("FILE_TOO_LARGE")
        if (_identity(os.fstat(fd)) != _identity(before)
                or _identity(path.lstat()) != _identity(before)
                or size != before.st_size):
            _fail("FILE_CHANGED_DURING_READ")
        return b"".join(chunks)
    except OSError:
        _fail("UNREADABLE_FILE_OR_CHANGED")
    finally:
        if fd is not None:
            os.close(fd)


def _unsafe_character(char: str) -> bool:
    return (unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            or 0xFDD0 <= ord(char) <= 0xFDEF or ord(char) & 0xFFFF in {0xFFFE, 0xFFFF})


def _value(raw: str, number: int) -> str:
    if raw.lstrip(" \t")[:1] not in {"'", '"'}:
        return re.split(r"[ \t]+#", raw, maxsplit=1)[0].strip(" \t")
    raw = raw.strip(" \t")
    quote = raw[0]
    out = []
    index = 1
    while index < len(raw):
        char = raw[index]
        if char == quote:
            tail = raw[index + 1:]
            if tail and (not tail[0] in " \t" or not tail.strip(" \t").startswith("#")):
                _fail("TRAILING_QUOTED_DATA", line=number)
            return "".join(out)
        if char == "\\" and index + 1 < len(raw):
            following = raw[index + 1]
            if following == quote or (quote == '"' and following == "\\"):
                out.append(following)
                index += 2
                continue
            if quote == '"' and following in "nrt":
                _fail("ESCAPED_CONTROL_CHARACTER", line=number)
        out.append(char)
        index += 1
    _fail("UNCLOSED_QUOTE", line=number)


def parse_bytes(raw: bytes) -> Dict[str, str]:
    if len(raw) > MAX_BYTES:
        _fail("FILE_TOO_LARGE")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        _fail("INVALID_UTF8")
    text = text.replace("\r\n", "\n")
    values: Dict[str, str] = {}
    for number, physical in enumerate(text.split("\n"), 1):
        if len(physical.encode("utf-8")) > MAX_LINE_BYTES:
            _fail("LINE_TOO_LONG", line=number)
        if any(_unsafe_character(char) for char in physical if char != "\t"):
            _fail("NONPRINTING_CHARACTER", line=number)
        line = physical.strip(" \t")
        if not line or line.startswith("#"):
            continue
        if re.match(r"export[ \t]+", line):
            line = re.sub(r"^export[ \t]+", "", line, count=1)
        if "=" not in line:
            _fail("MALFORMED_ASSIGNMENT", line=number)
        name, value = line.split("=", 1)
        name = name.strip(" \t")
        if KEY.fullmatch(name) is None:
            _fail("INVALID_KEY", line=number)
        if name in UNSAFE_KEYS:
            _fail("HOST_CONTROL_KEY_REFUSED", line=number, key=name)
        if name in values:
            _fail("DUPLICATE_KEY; appears more than once", line=number, key=name)
        parsed = _value(value, number)
        if any(_unsafe_character(char) for char in parsed):
            _fail("NONPRINTING_VALUE", line=number, key=name)
        values[name] = parsed
    return values


def load(path: Path, *, required: bool = False) -> Dict[str, str]:
    return parse_bytes(read_bytes(path, required=required))


def merge(values: Mapping[str, str], process: Mapping[str, str]) -> Dict[str, str]:
    for key in values:
        if (key in UNSAFE_KEYS or KEY.fullmatch(key) is None
                or not (key.startswith(FILE_PREFIXES) or key in FILE_EXTRA_KEYS)):
            _fail("FILE_COMMAND_KEY_REFUSED", key=key)
    result = dict(values)
    result.update(process)
    if result.get("COMPOSE_ENV_FILES", "").strip() not in {"", "/dev/null"}:
        _fail("ALTERNATE_COMPOSE_ENV_FILES_REFUSED", key="COMPOSE_ENV_FILES")
    result["COMPOSE_DISABLE_ENV_FILE"] = "1"
    result["COMPOSE_ENV_FILES"] = "/dev/null"
    return result


def usable(value: str) -> bool:
    return bool(value.strip()) and PLACEHOLDER.fullmatch(value.strip()) is None


def _validate_integer(env: Mapping[str, str], key: str, lower: int, upper: int) -> None:
    if key not in env:
        return
    value = str(env[key]).strip()
    if not re.fullmatch(r"[0-9]{1,10}", value):
        _fail("INTEGER_OUT_OF_RANGE", key=key)
    number = int(value)
    if number < lower or number > upper:
        _fail("INTEGER_OUT_OF_RANGE", key=key)


def _validate_decimal(
        env: Mapping[str, str], key: str, lower: Decimal, upper: Decimal) -> None:
    if key not in env:
        return
    value = str(env[key]).strip()
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        _fail("DECIMAL_OUT_OF_RANGE", key=key)
    if not number.is_finite() or number < lower or number > upper:
        _fail("DECIMAL_OUT_OF_RANGE", key=key)


def _validate_semantics(env: Mapping[str, str]) -> None:
    for key, bounds in INTEGER_BOUNDS.items():
        _validate_integer(env, key, bounds[0], bounds[1])
    for key, bounds in DECIMAL_BOUNDS.items():
        _validate_decimal(env, key, bounds[0], bounds[1])
    for key in EXACT_BOOLEAN_KEYS:
        if key in env and str(env[key]).strip() not in {"0", "1"}:
            _fail("EXPECTED_0_OR_1", key=key)
    for key in FLEX_BOOLEAN_KEYS:
        if (key in env and str(env[key]).strip().lower()
                not in {"", "0", "1", "false", "true", "no", "yes", "off", "on"}):
            _fail("INVALID_BOOLEAN", key=key)
    for key in SHA256_KEYS:
        if key in env and HEX64_OR_EMPTY.fullmatch(str(env[key]).strip()) is None:
            _fail("INVALID_SHA256", key=key)
    if ("SENTINEL_SHADOW_OBSERVATION_ID" in env
            and OBSERVATION_ID.fullmatch(
                str(env["SENTINEL_SHADOW_OBSERVATION_ID"]).strip()) is None):
        _fail("INVALID_OBSERVATION_ID", key="SENTINEL_SHADOW_OBSERVATION_ID")
    for key in (
            "SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY",
            "SENTINEL_AUTOMATION_PUBLICATION_TIMING_POLICY"):
        if key in env and str(env[key]).strip() != PUBLICATION_POLICY:
            _fail("INVALID_PUBLICATION_TIMING_POLICY", key=key)
    exposure = str(env.get("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE", "1")).strip()
    if re.fullmatch(r"(?:0|1|0\.[0-9]{0,17}[1-9])", exposure) is None:
        _fail("INVALID_EXPOSURE", key="SENTINEL_DEPLOY_MAXIMUM_EXPOSURE")


def validate(env: Mapping[str, str], *, profile: str, target: Optional[str] = None) -> None:
    """No I/O: prove local prerequisites before any external operation."""
    if profile not in {"compose", "bootstrap", "install", "go", "bringup", "maintenance"}:
        _fail("INVALID_PROFILE")
    target = target if target is not None else env.get("SENTINEL_GO_TARGET", TARGETS[1])
    if profile != "maintenance" and target not in TARGETS:
        _fail("INVALID_TARGET", key="SENTINEL_GO_TARGET")
    required = ["SENTINEL_BACKUP_DIR"] if profile == "compose" else [
        "SENTINEL_BACKUP_DIR", "SENTINEL_POSTGRES_PASSWORD", "SHARADAR_API_KEY"]
    if profile == "maintenance":
        required = ["SENTINEL_BACKUP_DIR", "SENTINEL_POSTGRES_PASSWORD", RECEIPT_KEY]
    if profile == "bringup" or (profile in {"install", "go"} and target != "SHADOW"):
        required += ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"]
    invalid = [key for key in required if not usable(env.get(key, ""))]
    if invalid:
        raise EnvRefused(".env REQUIRED_VALUES_MISSING_OR_PLACEHOLDER: " + ", ".join(invalid))
    for key, value in env.items():
        if key.startswith(("SENTINEL_", "SHARADAR_", "ALPACA_", "NDL_")):
            if any(_unsafe_character(c) for c in value):
                _fail("NONPRINTING_VALUE", key=key)
    if not Path(env["SENTINEL_BACKUP_DIR"]).is_absolute():
        _fail("ABSOLUTE_PATH_REQUIRED", key="SENTINEL_BACKUP_DIR")
    if profile != "compose":
        password = env["SENTINEL_POSTGRES_PASSWORD"]
        if any(c in password for c in ":/@?#[]%") or any(c.isspace() for c in password):
            _fail("UNSAFE_DSN_PASSWORD", key="SENTINEL_POSTGRES_PASSWORD")
    if ("ALPACA_API_KEY" in required
            and env.get("ALPACA_BASE_URL", PAPER_URL).rstrip("/") != PAPER_URL):
        _fail("PAPER_ENDPOINT_REQUIRED", key="ALPACA_BASE_URL")
    receipt = env.get(RECEIPT_KEY, "")
    if (profile != "bootstrap" and receipt
            and (not usable(receipt) or len(receipt.strip().encode("utf-8")) < 32)):
        _fail("INVALID_RECEIPT_KEY", key=RECEIPT_KEY)
    _validate_semantics(env)
    if env.get("SENTINEL_FORCE_CPU_LIMITS") == env.get("SENTINEL_FORCE_NO_CPU_LIMITS") == "1":
        _fail("CONFLICTING_CPU_MODES; force modes are mutually exclusive")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--profile",
        choices=("compose", "bootstrap", "install", "go", "bringup", "maintenance"),
        required=True)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--records", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--go-args", nargs=argparse.REMAINDER, default=[], help=argparse.SUPPRESS)
    args, _remaining = parser.parse_known_args(argv)
    if args.go_args:
        target_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        target_parser.add_argument("--target", choices=TARGETS, default=args.target)
        target_args, _remaining = target_parser.parse_known_args(args.go_args)
        args.target = target_args.target
    try:
        values = load(args.env_file, required=args.profile not in {"compose", "maintenance"})
        resolved = merge(values, os.environ)
        if (RECEIPT_KEY in os.environ
                and (not usable(os.environ[RECEIPT_KEY])
                     or len(os.environ[RECEIPT_KEY].strip().encode("utf-8")) < 32)):
            _fail("INVALID_EXTERNAL_RECEIPT_KEY", key=RECEIPT_KEY)
        validate(resolved, profile=args.profile, target=args.target)
        if args.records:
            names = set(values) | {"COMPOSE_DISABLE_ENV_FILE", "COMPOSE_ENV_FILES"}
            if not values.get(RECEIPT_KEY) and RECEIPT_KEY not in os.environ:
                names.discard(RECEIPT_KEY)
            for key in names:
                if any(_unsafe_character(char) for char in resolved[key]):
                    _fail("NONPRINTING_VALUE", key=key)
            payload = b"".join((key + "=" + resolved[key]).encode("utf-8") + b"\0"
                               for key in sorted(names)) + COMPLETE
            sys.stdout.buffer.write(payload)
        else:
            print("environment preflight: PASS (%s)" % args.profile)
        return 0
    except EnvRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
