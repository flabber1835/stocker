"""Shared, non-routing support for the Sentinel command-line interface."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from functools import wraps
import inspect
import stat
import subprocess
import sys


EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_NOT_ESTABLISHED = 2

AUTHORIZED_RUNTIME_ENV = "SENTINEL_AUTHORIZED_RUNTIME"
AUTHORIZED_RUNTIME_VALUE = "SIGNED_DIGEST_SERVICE_V1"
AUTHORIZED_RUNTIME_MARKER = Path("/opt/sentinel/authorized-runtime-v1")
AUTHORIZED_RUNTIME_MARKER_BYTES = b"sentinel-authorized-runtime/1\n"
AUTHORIZED_RUNTIME_CAPABILITY = Path(
    "/opt/sentinel/bin/authorized-runtime-capability-v1")
AUTHORIZED_RUNTIME_CAPABILITY_BYTES = b"sentinel-authorized-capability/1\n"

# Commands which construct a broker, establish broker authority, or enable
# unattended operation. Emergency fencing remains available in the ordinary
# runtime so loss of the authorized image cannot prevent revocation.
AUTHORIZED_RUNTIME_COMMANDS = frozenset({
    "migration-plan",
    "inspect-paper-account",
    "inspect-empty-paper-account",
    "bind-empty-paper-account",
    "prepare-paper-plan",
    "execute-paper-plan",
    "install-administrative-certificate",
    "activate-administrative-certificate",
    "install-system-certificate",
    "activate-system-certificate",
    "rotate-system-certificate",
    "set-paper-rollout-mode",
    "activate-paper-automation",
    "release-paper-automation-kill-switch",
    "automation-run",
    "migrate-account",
    "adopt-restored-account",
})

PINNED_ROLLOUT_RISK_WARNING = (
    "PINNED_1_00 forces 100% Wealth Core exposure and may increase exposure "
    "and risk from the current controller allocation")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def _authorized_capability_executes() -> bool:
    """Prove the reviewed image contains its executable capability seam."""
    try:
        mode = AUTHORIZED_RUNTIME_CAPABILITY.lstat().st_mode
        if (not stat.S_ISREG(mode) or stat.S_ISLNK(mode)
                or mode & 0o111 == 0):
            return False
        result = subprocess.run(
            [str(AUTHORIZED_RUNTIME_CAPABILITY)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return (result.returncode == 0
            and result.stdout == AUTHORIZED_RUNTIME_CAPABILITY_BYTES
            and result.stderr == b"")


def _authorized_marker_bytes() -> bytes | None:
    """Read the fixed marker without following a substituted symlink."""
    try:
        mode = AUTHORIZED_RUNTIME_MARKER.lstat().st_mode
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            return None
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(AUTHORIZED_RUNTIME_MARKER), flags)
        try:
            return os.read(fd, len(AUTHORIZED_RUNTIME_MARKER_BYTES) + 1)
        finally:
            os.close(fd)
    except OSError:
        return None


def require_authorized_runtime(command: str) -> int | None:
    """Refuse broker/authority commands outside the reviewed image surface."""
    if command not in AUTHORIZED_RUNTIME_COMMANDS:
        return None
    # Formerly AUTHORIZED_RUNTIME_MARKER.read_bytes(); the no-follow read keeps
    # the same fixed-byte proof without accepting a substituted symlink.
    marker = _authorized_marker_bytes()
    if (os.environ.get(AUTHORIZED_RUNTIME_ENV) == AUTHORIZED_RUNTIME_VALUE
            and marker == AUTHORIZED_RUNTIME_MARKER_BYTES
            and _authorized_capability_executes()):
        return None
    print(
        "REFUSED: this command requires the executable-capability, marker-bearing, "
        "digest-qualified authorized Sentinel runtime; use "
        "scripts/sentinel-authorized-cli.sh",
        file=sys.stderr,
    )
    return EXIT_CONFIG


def authorized_handler(command: str):
    """Gate an image-exclusive handler even when invoked outside CLI dispatch."""
    if command not in AUTHORIZED_RUNTIME_COMMANDS:
        raise ValueError(f"{command!r} is not an authorized runtime command")

    def decorate(handler):
        if inspect.iscoroutinefunction(handler):
            @wraps(handler)
            async def async_guarded(*args, **kwargs):
                refusal = require_authorized_runtime(command)
                if refusal is not None:
                    return refusal
                return await handler(*args, **kwargs)
            return async_guarded

        @wraps(handler)
        def guarded(*args, **kwargs):
            refusal = require_authorized_runtime(command)
            if refusal is not None:
                return refusal
            return handler(*args, **kwargs)
        return guarded

    return decorate


def paper_refusal_types() -> tuple[type[BaseException], ...]:
    """Safety refusals reported as an operator checkpoint, not a traceback."""
    from sentinel import (
        authority, binding as binding_mod, empty_account, handover, paper,
        schema,
    )
    from sentinel.automation import model as automation_model
    from sentinel.controller import frozen_rule
    from sentinel.core import catchup
    from sentinel.execution import (
        alpaca, certification, contract, executor, journal, projection,
    )
    from sentinel.feed import calendar, publication

    return (
        schema.SchemaMigrationRefused,
        paper.PaperActivationRefused,
        automation_model.AutomationRefused,
        authority.AuthorityRefused,
        binding_mod.AccountNotBound,
        binding_mod.AccountMismatch,
        empty_account.EmptyAccountRefused,
        handover.MigrationRefused,
        executor.StalePlanRefused,
        executor.RiskEnvelopeViolation,
        journal.WriterLockUnavailable,
        journal.PlanAuthorityMissing,
        journal.PlanEconomicsChanged,
        journal.CommandEconomicsChanged,
        journal.RecoveredOrderConflict,
        journal.StoredKeyMismatch,
        certification.AdapterNotCertified,
        contract.CapabilityNotCertified,
        contract.IncompleteObservation,
        alpaca.MalformedBrokerPayload,
        alpaca.UnmappedBrokerStatus,
        projection.ProjectionRefused,
        catchup.SessionsIncomplete,
        catchup.StateNotDurable,
        catchup.NavUnobserved,
        calendar.CalendarUnavailable,
        frozen_rule.FrozenRuleMissing,
        frozen_rule.FrozenRuleTampered,
        publication.CorpusBusy,
        publication.CorpusIncoherent,
        publication.NoPublishedVersion,
        ValueError,
    )


def paper_refused(exc: BaseException) -> int:
    print(f"REFUSED: {exc}", file=sys.stderr)
    return EXIT_NOT_ESTABLISHED


__all__ = [
    "AUTHORIZED_RUNTIME_CAPABILITY",
    "AUTHORIZED_RUNTIME_CAPABILITY_BYTES",
    "AUTHORIZED_RUNTIME_COMMANDS",
    "AUTHORIZED_RUNTIME_ENV",
    "AUTHORIZED_RUNTIME_MARKER",
    "AUTHORIZED_RUNTIME_MARKER_BYTES",
    "AUTHORIZED_RUNTIME_VALUE",
    "authorized_handler",
    "EXIT_CONFIG",
    "EXIT_NOT_ESTABLISHED",
    "EXIT_OK",
    "PINNED_ROLLOUT_RISK_WARNING",
    "paper_refusal_types",
    "paper_refused",
    "require_authorized_runtime",
    "setup_logging",
]
