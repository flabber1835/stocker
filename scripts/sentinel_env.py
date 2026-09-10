#!/usr/bin/env python3
"""Bounded, literal host env ingestion and side-effect-free preflight (Python 3.8+)."""
from __future__ import annotations

import argparse
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
})
FILE_PREFIXES = ("SENTINEL_", "SHARADAR_", "ALPACA_", "NDL_")
FILE_EXTRA_KEYS = frozenset({
    "GITHUB_TOKEN", "GH_TOKEN", "COMPOSE_DISABLE_ENV_FILE", "COMPOSE_ENV_FILES",
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
    # Keep leading whitespace until comment recognition: '= # comment' is empty.
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
    # Parsed legacy data is broader than executable command configuration.
    # Validate every file key before merging, even if the process overrides it.
    for key in values:
        if (key in UNSAFE_KEYS or KEY.fullmatch(key) is None
                or not (key.startswith(FILE_PREFIXES) or key in FILE_EXTRA_KEYS)):
            _fail("FILE_COMMAND_KEY_REFUSED", key=key)
    result = dict(values)
    result.update(process)
    # Compose receives the literal values already resolved here. A second parser
    # must not reinterpret '$', override the chosen file, or observe later bytes.
    if result.get("COMPOSE_ENV_FILES", "").strip() not in {"", "/dev/null"}:
        _fail("ALTERNATE_COMPOSE_ENV_FILES_REFUSED", key="COMPOSE_ENV_FILES")
    result["COMPOSE_DISABLE_ENV_FILE"] = "1"
    result["COMPOSE_ENV_FILES"] = "/dev/null"
    return result


def usable(value: str) -> bool:
    return bool(value.strip()) and PLACEHOLDER.fullmatch(value.strip()) is None


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
    if profile in {"install", "bringup"} or (profile == "go" and target != "SHADOW"):
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
    if "ALPACA_API_KEY" in required and env.get("ALPACA_BASE_URL", PAPER_URL).rstrip("/") != PAPER_URL:
        _fail("PAPER_ENDPOINT_REQUIRED", key="ALPACA_BASE_URL")
    receipt = env.get(RECEIPT_KEY, "")
    if profile != "bootstrap" and receipt and (not usable(receipt) or len(receipt.strip().encode("utf-8")) < 32):
        _fail("INVALID_RECEIPT_KEY", key=RECEIPT_KEY)
    for key in ("SENTINEL_FORCE_CPU_LIMITS", "SENTINEL_FORCE_NO_CPU_LIMITS",
                "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED"):
        if key in env and env[key] not in {"0", "1"}:
            _fail("EXPECTED_0_OR_1", key=key)
    if env.get("SENTINEL_FORCE_CPU_LIMITS") == env.get("SENTINEL_FORCE_NO_CPU_LIMITS") == "1":
        _fail("CONFLICTING_CPU_MODES; force modes are mutually exclusive")
    if profile == "install":
        bounds = {
            "SENTINEL_DEPLOY_NOT_BEFORE_MARGIN_SECONDS": (0, 1800),
            "SENTINEL_DEPLOY_HEALTH_TIMEOUT_SECONDS": (30, 1800),
            "SENTINEL_AUTOMATION_HEARTBEAT_SECONDS": (1, 300),
            "SENTINEL_DEPLOY_DATA_RETRY_SECONDS": (30, 3600),
            "SENTINEL_DEPLOY_DATA_WAIT_TIMEOUT_SECONDS": (300, 86400),
        }
        for key, (lower, upper) in bounds.items():
            if key not in env:
                continue
            value = env[key].strip()
            if not re.fullmatch(r"[0-9]{1,8}", value) or not lower <= int(value) <= upper:
                _fail("INTEGER_OUT_OF_RANGE", key=key)
        for key in ("SENTINEL_DEPLOY_ALLOW_EMPTY_BIND", "SENTINEL_DEPLOY_REVOKE_PREVIOUS_SIGNING_KEY"):
            if key in env and env[key].strip().lower() not in {"", "0", "1", "false", "true", "no", "yes", "off", "on"}:
                _fail("INVALID_BOOLEAN", key=key)
        if re.fullmatch(r"(?:0|1|0\.[0-9]{0,17}[1-9])", env.get("SENTINEL_DEPLOY_MAXIMUM_EXPOSURE", "1")) is None:
            _fail("INVALID_EXPOSURE", key="SENTINEL_DEPLOY_MAXIMUM_EXPOSURE")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--profile", choices=("compose", "bootstrap", "install", "go", "bringup", "maintenance"), required=True)
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
        if RECEIPT_KEY in os.environ and (not usable(os.environ[RECEIPT_KEY])
                                         or len(os.environ[RECEIPT_KEY].strip().encode("utf-8")) < 32):
            _fail("INVALID_EXTERNAL_RECEIPT_KEY", key=RECEIPT_KEY)
        validate(resolved, profile=args.profile, target=args.target)
        if args.records:
            # Private shell-loader protocol: no bytes are published until every
            # check passes, and an incomplete pipe cannot be accepted as success.
            names = set(values) | {"COMPOSE_DISABLE_ENV_FILE", "COMPOSE_ENV_FILES"}
            # A fresh blank file slot remains unprovisioned. Exporting it would
            # turn it into an explicit invalid process override at bootstrap.
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
