"""Publish the test result produced by ``sentinel-certify.sh``.

This is a narrow evidence producer, not a general pytest-log summarizer. It
binds the bytes emitted by the actual harness command to the pre-suite frozen
manifest and immutable image digests, and publishes only a complete pass.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Sequence


SCHEMA = "sentinel.certification-test-run/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_SUMMARY_ITEM = re.compile(
    r"(?P<count>[0-9]+) (?P<status>passed|failed|skipped|xfailed|xpassed|"
    r"errors?|warnings?)\b"
)
_SUMMARY_LINE = re.compile(
    r"^(?:[0-9]+ (?:passed|failed|skipped|xfailed|xpassed|errors?|warnings?), )*"
    r"[0-9]+ (?:passed|failed|skipped|xfailed|xpassed|errors?|warnings?) in "
    r"[0-9]+(?:\.[0-9]+)?s\r?$",
    re.MULTILINE,
)
# Both evidence summaries must occupy a complete physical line. Parameter ids
# may contain summary-shaped text, including a literal escaped newline.
_COLLECTED = re.compile(
    r"^(?P<count>[0-9]+) tests? collected in "
    r"[0-9]+(?:\.[0-9]+)?s\r?$",
    re.MULTILINE,
)
# Parameter ids are allowed to contain spaces (and this suite has several).
# The path itself is constrained to the Sentinel suite and the separator must
# name a concrete collected item rather than a module-only collection line.
_NODEID = re.compile(r"^tests/sentinel/[^\s:]+\.py::.+$")


class TestRunRefused(ValueError):
    """The supplied bytes do not prove a complete passing certified run."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base64(data: bytes) -> str:
    """Return the one padded RFC 4648 encoding accepted by the consumer."""
    return base64.b64encode(data).decode("ascii")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json_object(raw: bytes, *, what: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise TestRunRefused(f"{what} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TestRunRefused(f"{what} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise TestRunRefused(f"{what} is not a JSON object")
    return value


def _require_sha(value: object, *, field: str, git: bool = False) -> str:
    pattern = _GIT_SHA if git else _SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise TestRunRefused(f"{field} is not a canonical digest")
    return value


def _without_sha256_prefix(value: str) -> str:
    """Return the digest payload without requiring Python 3.9."""
    prefix = "sha256:"
    return value[len(prefix):] if value.startswith(prefix) else value


def _unique_repo_identity(image: object, *, field: str) -> tuple[str, str]:
    if not isinstance(image, dict):
        raise TestRunRefused(f"{field} is not an image identity object")
    refs = image.get("repo_digests")
    if not isinstance(refs, list) or not refs:
        raise TestRunRefused(
            f"{field}.repo_digests has no immutable registry digest"
        )
    digests: set[str] = set()
    for ref in refs:
        if not isinstance(ref, str) or "@" not in ref:
            raise TestRunRefused(f"{field}.repo_digests contains a malformed ref")
        digest = ref.rsplit("@", 1)[1]
        if not digest.startswith("sha256:"):
            raise TestRunRefused(f"{field}.repo_digests is not SHA-256")
        _require_sha(_without_sha256_prefix(digest), field=field)
        digests.add(digest)
    if len(digests) != 1:
        raise TestRunRefused(
            f"{field}.repo_digests resolves to {len(digests)} content digests"
        )
    return next(iter(digests)), sorted(refs)[0]


def manifest_binding(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    manifest = _json_object(raw, what="base manifest")
    if manifest.get("schema") != "sentinel.certification_manifest/2":
        raise TestRunRefused("base manifest schema is not certification_manifest/2")
    if manifest.get("lifecycle") != "FROZEN":
        raise TestRunRefused("pre-suite base manifest lifecycle is not FROZEN")
    input_hashes = manifest.get("image_source_hashes")
    if not isinstance(input_hashes, dict):
        raise TestRunRefused("base manifest has no image_source_hashes")
    binding = {
        "path": path.as_posix(),
        "sha256": _sha256(raw),
        "lifecycle": "FROZEN",
        "identity_hash": _require_sha(
            manifest.get("identity_hash"), field="identity_hash"
        ),
        "git_commit": _require_sha(
            manifest.get("git_commit"), field="git_commit", git=True
        ),
        "certification_input_sha256": _require_sha(
            input_hashes.get("certification_inputs"),
            field="image_source_hashes.certification_inputs",
        ),
        "runtime_image_digest": _unique_repo_identity(
            manifest.get("sentinel_runtime_image"),
            field="sentinel_runtime_image",
        )[0],
        "test_image_digest": _unique_repo_identity(
            manifest.get("sentinel_test_image"), field="sentinel_test_image"
        )[0],
    }
    if binding["runtime_image_digest"] == binding["test_image_digest"]:
        raise TestRunRefused("runtime and test images have the same digest")
    return binding, raw


def test_image_ref(path: Path) -> str:
    """Return a deterministic digest-qualified ref after full validation."""
    _, raw = manifest_binding(path)
    manifest = _json_object(raw, what="base manifest")
    return _unique_repo_identity(
        manifest.get("sentinel_test_image"), field="sentinel_test_image"
    )[1]


def inventory_from_log(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TestRunRefused("collection log is not UTF-8") from exc
    nodeids = sorted({
        line.strip() for line in text.splitlines()
        if _NODEID.fullmatch(line.strip()) is not None
    })
    if not nodeids:
        raise TestRunRefused("collection log contains no Sentinel nodeids")
    declared = [int(match.group("count")) for match in _COLLECTED.finditer(text)]
    if len(declared) != 1 or declared[0] != len(nodeids):
        raise TestRunRefused(
            "collection summary does not match the sorted unique nodeid inventory"
        )
    canonical_nodeids = _canonical(nodeids)
    return {
        "nodeids": nodeids,
        "sha256": _sha256(canonical_nodeids),
        "count": len(nodeids),
    }


def counts_from_log(raw: bytes, *, exit_code: int) -> dict[str, int]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TestRunRefused("pytest log is not UTF-8") from exc
    summary_lines = [match.group(0) for match in _SUMMARY_LINE.finditer(text)]
    if len(summary_lines) != 1:
        raise TestRunRefused("pytest log does not contain one terminal summary")
    counts = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "errors": 0,
    }
    seen: set[str] = set()
    for match in _SUMMARY_ITEM.finditer(summary_lines[0]):
        status = match.group("status")
        if status.startswith("error"):
            status = "errors"
        if status == "warnings":
            continue
        if status in seen:
            raise TestRunRefused(f"pytest summary repeats {status}")
        seen.add(status)
        counts[status] = int(match.group("count"))
    if counts["passed"] <= 0:
        raise TestRunRefused("pytest summary contains no passing test")
    if exit_code != 0:
        raise TestRunRefused(f"pytest exited {exit_code}, not zero")
    bad = {
        key: counts[key]
        for key in ("failed", "skipped", "xpassed", "errors")
        if counts[key]
    }
    if bad:
        raise TestRunRefused(f"pytest result is not certifiable: {bad}")
    return counts


def validate_canonical_command(
    command: object, *, expected_test_image_digest: str
) -> list[str]:
    """Return the one formal Sentinel-suite argv accepted as evidence.

    This validation is intentionally shared by the producer, bundle builder,
    and offline issuer.  Re-hashing an operator-selected pytest subset must
    never turn that subset into a formal certification run.
    """
    if not isinstance(command, list) or any(
        not isinstance(arg, str) or not arg for arg in command
    ):
        raise TestRunRefused("test command argv is empty or malformed")
    expected_tail = ["tests/sentinel", "-q", "-rs"]
    if (
        len(command) != 9
        or command[:5] != ["docker", "run", "--rm", "--network", "none"]
        or command[6:] != expected_tail
    ):
        raise TestRunRefused("test command is not the canonical suite command")
    if (
        not isinstance(expected_test_image_digest, str)
        or not expected_test_image_digest.startswith("sha256:")
        or _SHA256.fullmatch(
            _without_sha256_prefix(expected_test_image_digest)
        ) is None
    ):
        raise TestRunRefused("manifest-bound test image digest is malformed")
    if (
        "@" not in command[5]
        or command[5].rsplit("@", 1)[1] != expected_test_image_digest
    ):
        raise TestRunRefused(
            "test command does not run the manifest-bound immutable test image"
        )
    return list(command)


def build_record(
    *, manifest_path: Path, inventory_path: Path, log_path: Path,
    exit_code: int, command: Sequence[str],
) -> dict[str, Any]:
    if not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise TestRunRefused("test command argv is empty or malformed")
    binding, _ = manifest_binding(manifest_path)
    inventory_log = inventory_path.read_bytes()
    inventory = inventory_from_log(inventory_log)
    log = log_path.read_bytes()
    counts = counts_from_log(log, exit_code=exit_code)
    argv = validate_canonical_command(
        list(command),
        expected_test_image_digest=binding["test_image_digest"],
    )
    if counts["passed"] + counts["xfailed"] != inventory["count"]:
        raise TestRunRefused(
            "pytest outcomes do not account for every collected nodeid"
        )
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS",
        "producer_sha256": _sha256(Path(__file__).resolve().read_bytes()),
        "base_manifest": binding,
        "command": {"argv": argv, "sha256": _sha256(_canonical(argv))},
        "inventory": inventory,
        "inventory_log_base64": _base64(inventory_log),
        "pytest_log_base64": _base64(log),
        "pytest_log_sha256": _sha256(log),
        "exit_code": exit_code,
    }
    record.update(counts)
    return record


def _fsync_directory(path: Path) -> None:
    # Windows cannot open a directory as a regular file descriptor. The same
    # volume still gets the file fsync + atomic hard-link/no-clobber boundary;
    # POSIX additionally persists both directory-entry transitions.
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _unlink_retry(path: Path) -> None:
    last: OSError | None = None
    for _ in range(4):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last = exc
    assert last is not None
    raise last


def _rollback_published(path: Path, original: BaseException) -> None:
    try:
        _unlink_retry(path)
    except OSError as cleanup:
        quarantine = path.with_name(f".{path.name}.rollback.{os.getpid()}")
        try:
            os.replace(path, quarantine)
            try:
                _unlink_retry(quarantine)
            except OSError as residual:
                if hasattr(original, "add_note"):
                    original.add_note(
                        f"rollback quarantine remains at {quarantine}: {residual!r}"
                    )
        except OSError as rename_error:
            if hasattr(original, "add_note"):
                original.add_note(
                    f"could not remove published path: {cleanup!r}; "
                    f"rename fallback failed: {rename_error!r}"
                )
    try:
        _fsync_directory(path.parent)
    except BaseException as cleanup_fsync:
        if hasattr(original, "add_note"):
            original.add_note(
                f"rollback parent fsync also failed: {cleanup_fsync!r}"
            )


def _write_no_clobber(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    published = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        published = True
        _fsync_directory(path.parent)
        _unlink_retry(temporary)
        _fsync_directory(path.parent)
    except BaseException as exc:
        if published:
            _rollback_published(path, exc)
        raise
    finally:
        try:
            _unlink_retry(temporary)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    validate = sub.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--print-test-ref", action="store_true")
    retain = sub.add_parser("retain-manifest")
    retain.add_argument("--manifest", type=Path, required=True)
    retain.add_argument("--output", type=Path, required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--inventory-log", type=Path, required=True)
    publish.add_argument("--pytest-log", type=Path, required=True)
    publish.add_argument("--exit-code", type=int, required=True)
    publish.add_argument("--output", type=Path, required=True)
    publish.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "validate-manifest":
            if args.print_test_ref:
                print(test_image_ref(args.manifest))
            else:
                manifest_binding(args.manifest)
            return 0
        if args.operation == "retain-manifest":
            _, raw = manifest_binding(args.manifest)
            _write_no_clobber(args.output, raw)
            return 0
        command = list(args.command)
        if command[:1] == ["--"]:
            command = command[1:]
        record = build_record(
            manifest_path=args.manifest,
            inventory_path=args.inventory_log,
            log_path=args.pytest_log,
            exit_code=args.exit_code,
            command=command,
        )
        _write_no_clobber(args.output, _canonical(record))
    except (OSError, TestRunRefused) as exc:
        print(f"TEST RUN EVIDENCE REFUSED: {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
