#!/usr/bin/env python3
"""Final host entry for the phased GO controller.

This wrapper closes host-side authority seams around the reusable phase
controller without duplicating its financial probes:

* retained certification also binds the ordinary runtime promoted later;
* reuse is bounded to the same host boot and a short retry horizon;
* a failed/incomplete certification can never reach mutable preparation;
* a failed preparation short-circuits the expensive read-only readiness work;
* final readiness requires the reviewed minimum *actual* pre-open margin;
* the public GO lifetime cannot outlive that remaining readiness margin.

The supported NAS entry is ``scripts/sentinel-go-validate.sh``, which invokes
this module. The lower-level controller remains an implementation module, not
an operator entrypoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
MAX_REUSE_AGE = timedelta(hours=24)
_ORIGINAL_WRITE = controller._write_certification_cache
_ORIGINAL_LOAD = controller._load_certification_cache
_ORIGINAL_CERTIFY = controller._certify_exact_artifacts
_ORIGINAL_PREPARATION = controller.entry.probe_prevalidation_preparation
_ORIGINAL_PARITY = controller.go.probe_active_wealth_parity
_ORIGINAL_READINESS = controller.go.probe_sharadar_readiness
_ORIGINAL_DATABASE = controller.go.probe_database_financial_health
_ORIGINAL_ACTUAL = controller._actual_remaining_ms
_ORIGINAL_DATABASE_VIEW = controller.DatabaseHealthView
_ORIGINAL_EMIT = controller.go.emit_bundle
_PHASE = {"certified": False, "prepared": False}


def _bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: dict) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z")


def _parse_utc(value: object) -> Optional[datetime]:
    try:
        text = str(value)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _boot_id_sha256() -> Optional[str]:
    try:
        value = BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    if not value:
        return None
    return hashlib.sha256(value.encode("ascii")).hexdigest()


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
        try:
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _ordinary_id(runner, commit: str) -> Optional[str]:
    ref = "sentinel-go-runtime:%s" % commit
    digest = controller.go._inspect_image_id(runner, ref)
    if digest is None or controller.go._IMAGE_DIGEST.fullmatch(str(digest)) is None:
        return None
    return str(digest)


def _disable_reuse_cache() -> None:
    for path in (controller.CACHE_PATH, ORDINARY_PATH):
        try:
            path.unlink()
        except OSError:
            pass


def _write_with_ordinary(commit: str, summary) -> None:
    _ORIGINAL_WRITE(commit, summary)
    if not summary.complete:
        return
    runner = controller.DiagnosticRunner()
    digest = _ordinary_id(runner, commit)
    if digest is None:
        _disable_reuse_cache()
        raise controller.PhaseRefused(
            "certification completed but ordinary runtime identity was unavailable")
    boot = _boot_id_sha256()
    if boot is None:
        # Initial certification remains valid for this run; only cross-process
        # reuse is disabled when the host cannot provide a boot identity.
        _disable_reuse_cache()
        return
    evidence = {
        "schema": ORDINARY_SCHEMA,
        "git_commit": commit,
        "ordinary_runtime_image_digest": digest,
        "certified_at": _utc(datetime.now(timezone.utc)),
        "host_boot_id_sha256": boot,
        "maximum_reuse_age_seconds": int(MAX_REUSE_AGE.total_seconds()),
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
    if payload.get("maximum_reuse_age_seconds") != int(
            MAX_REUSE_AGE.total_seconds()):
        return False
    boot = _boot_id_sha256()
    if boot is None or payload.get("host_boot_id_sha256") != boot:
        return False
    certified_at = _parse_utc(payload.get("certified_at"))
    if certified_at is None:
        return False
    age = datetime.now(timezone.utc) - certified_at
    if age < timedelta(0) or age > MAX_REUSE_AGE:
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


def _certify_guarded(*args, **kwargs):
    summary, gate = _ORIGINAL_CERTIFY(*args, **kwargs)
    _PHASE["certified"] = bool(
        gate.status == controller.go.PASS and summary.complete)
    _PHASE["prepared"] = False
    return summary, gate


def _unavailable_preparation(runtime_ref, reason: str):
    evidence = {"reason": reason, "mutation_attempted": False}
    return controller.go.PreparationSummary(
        status=controller.go.NOT_PROVEN,
        runtime_image_digest=(
            str(runtime_ref)
            if runtime_ref is not None
            and controller.go._IMAGE_DIGEST.fullmatch(str(runtime_ref))
            else None),
        schema_migration_attempted=False,
        bounded_sharadar_daily_attempted=False,
        broker_mutation_attempts=0,
        evidence_sha256=controller.go._evidence_digest(evidence),
    )


def _preparation_guarded(*args, **kwargs):
    if not _PHASE["certified"]:
        _PHASE["prepared"] = False
        return _unavailable_preparation(
            kwargs.get("runtime_ref"), "CERTIFICATION_NOT_PASS_NO_MUTATION")
    result = _ORIGINAL_PREPARATION(*args, **kwargs)
    _PHASE["prepared"] = bool(
        result.status == controller.go.PASS and result.complete)
    return result


def _parity_guarded(*args, **kwargs):
    if not _PHASE["prepared"]:
        return controller.go.make_gate(
            "wealth_core_nas_parity", controller.go.NOT_PROVEN,
            kwargs["now_text"], {"reason": "PREPARATION_NOT_PASS"})
    return _ORIGINAL_PARITY(*args, **kwargs)


def _readiness_guarded(*args, **kwargs):
    if not _PHASE["prepared"]:
        return controller.go.make_gate(
            "sharadar_readiness", controller.go.NOT_PROVEN,
            kwargs["now_text"], {"reason": "PREPARATION_NOT_PASS"})
    return _ORIGINAL_READINESS(*args, **kwargs)


def _database_guarded(*args, **kwargs):
    if not _PHASE["prepared"]:
        summary = controller.go.unavailable_database_health(
            runtime_image_digest=kwargs.get("runtime_ref"),
            reason="PREPARATION_NOT_PASS")
        return summary, controller.go.make_gate(
            "database_financial_health", controller.go.NOT_PROVEN,
            kwargs["now_text"], summary.to_dict())
    return _ORIGINAL_DATABASE(*args, **kwargs)


def _actual_guarded(*args, **kwargs):
    if not _PHASE["prepared"]:
        return None
    return _ORIGINAL_ACTUAL(*args, **kwargs)


class StrictDatabaseHealthView(_ORIGINAL_DATABASE_VIEW):
    def remaining_now_ms(self) -> Optional[int]:
        if type(self.actual_remaining_to_execution_open_ms) is not int:
            return None
        observed = _parse_utc(self.observed_at)
        if observed is None:
            return None
        elapsed = max(
            0, int((datetime.now(timezone.utc) - observed).total_seconds() * 1000))
        return max(0, self.actual_remaining_to_execution_open_ms - elapsed)

    @property
    def complete(self) -> bool:
        remaining = self.remaining_now_ms()
        return bool(
            self.base.complete
            and type(remaining) is int
            and remaining >= controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS
        )

    def to_dict(self) -> dict:
        value = super().to_dict()
        remaining = self.remaining_now_ms()
        value["actual_deadline"]["remaining_at_serialization_ms"] = remaining
        value["actual_deadline"]["minimum_required_remaining_ms"] = (
            controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS)
        value["actual_deadline"]["minimum_margin_satisfied"] = bool(
            type(remaining) is int
            and remaining >= controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS)
        return value


def _emit_at_completion(*args, **kwargs):
    completed_at = datetime.now(timezone.utc).replace(microsecond=0)
    kwargs["created_at"] = completed_at
    probes = args[0] if args else None
    health = getattr(probes, "database_health", None)
    if isinstance(health, StrictDatabaseHealthView) and health.complete:
        remaining = health.remaining_now_ms()
        if type(remaining) is int:
            # A GO verdict is meaningful only while the reviewed minimum margin
            # still remains. The public evidence lifetime cannot extend beyond
            # the point at which that volatile predicate becomes false.
            usable = remaining - controller.go.MIN_REMAINING_DEADLINE_MARGIN_MS
            if usable <= 0:
                raise controller.go.ValidationRefused(
                    "GO evidence lost its minimum pre-open margin before emission")
            requested = kwargs.get("valid_for", timedelta(hours=24))
            kwargs["valid_for"] = min(
                requested, timedelta(milliseconds=usable))
    return _ORIGINAL_EMIT(*args, **kwargs)


def install() -> None:
    controller._write_certification_cache = _write_with_ordinary
    controller._load_certification_cache = _load_with_ordinary
    controller._certify_exact_artifacts = _certify_guarded
    controller.entry.probe_prevalidation_preparation = _preparation_guarded
    controller.go.probe_active_wealth_parity = _parity_guarded
    controller.go.probe_sharadar_readiness = _readiness_guarded
    controller.go.probe_database_financial_health = _database_guarded
    controller._actual_remaining_ms = _actual_guarded
    controller.DatabaseHealthView = StrictDatabaseHealthView
    controller.go.emit_bundle = _emit_at_completion


def _strict_target(argv: Sequence[str]) -> None:
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
