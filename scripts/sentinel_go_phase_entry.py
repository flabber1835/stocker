#!/usr/bin/env python3
"""Final host entry for the phased GO controller.

This narrow wrapper adds the ordinary-runtime identity to retained certification
without duplicating the phase controller.  The controller's TestSummary already
binds the authorized runtime, Sentinel test lens and backtester lenses; this
companion binding closes the remaining retry-to-promotion substitution seam for
``sentinel-go-runtime:<commit>``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sentinel_go_phase_controller as controller  # noqa: E402

ORDINARY_SCHEMA = "sentinel.nas-go-ordinary-runtime-binding/1"
ORDINARY_PATH = (
    controller.go.ROOT / "artifacts" / "sentinel" / "go-validation" /
    "stable-certification-ordinary-runtime.json"
)
_ORIGINAL_WRITE = controller._write_certification_cache
_ORIGINAL_LOAD = controller._load_certification_cache


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: dict) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".ordinary-runtime-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(_bytes(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _ordinary_id(runner, commit: str) -> Optional[str]:
    ref = "sentinel-go-runtime:%s" % commit
    digest = controller.go._inspect_image_id(runner, ref)
    if digest is None or controller.go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        return None
    return str(digest)


def _write_with_ordinary(commit: str, summary) -> None:
    _ORIGINAL_WRITE(commit, summary)
    if not summary.complete:
        return
    runner = controller.DiagnosticRunner()
    digest = _ordinary_id(runner, commit)
    if digest is None:
        # Never leave the reusable summary without its promotion-side identity.
        try:
            controller.CACHE_PATH.unlink()
        except OSError:
            pass
        raise controller.PhaseRefused(
            "certification completed but ordinary runtime identity was unavailable")
    evidence = {
        "schema": ORDINARY_SCHEMA,
        "git_commit": commit,
        "ordinary_runtime_image_digest": digest,
    }
    _atomic_write(ORDINARY_PATH, {**evidence, "evidence_sha256": _sha(evidence)})


def _ordinary_binding_matches(runner, commit: str) -> bool:
    try:
        payload = json.loads(ORDINARY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(payload, dict) or payload.get("schema") != ORDINARY_SCHEMA:
        return False
    supplied = str(payload.get("evidence_sha256") or "")
    evidence = {key: value for key, value in payload.items()
                if key != "evidence_sha256"}
    if supplied != _sha(evidence) or payload.get("git_commit") != commit:
        return False
    expected = str(payload.get("ordinary_runtime_image_digest") or "")
    if controller.go._IMAGE_DIGEST.fullmatch(expected) is None:
        return False
    return _ordinary_id(runner, commit) == expected


def _load_with_ordinary(runner, *, commit: str):
    summary = _ORIGINAL_LOAD(runner, commit=commit)
    if summary is None:
        return None
    if not _ordinary_binding_matches(runner, commit):
        return None
    return summary


def install() -> None:
    controller._write_certification_cache = _write_with_ordinary
    controller._load_certification_cache = _load_with_ordinary


def _strict_target(argv: Sequence[str]) -> None:
    # argparse does not reliably validate an environment-derived default. Keep
    # direct Python invocation as strict as the shell launcher.
    has_cli_target = any(
        item == "--target" or str(item).startswith("--target=") for item in argv)
    if not has_cli_target:
        target = str(os.environ.get("SENTINEL_GO_TARGET") or controller.TARGET_DUAL)
        if target not in controller.TARGETS:
            raise controller.PhaseRefused(
                "SENTINEL_GO_TARGET is not a supported deployment target")


def main(argv: Optional[Sequence[str]] = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    try:
        _strict_target(raw)
        install()
        return controller.main(raw)
    except controller.PhaseRefused as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
