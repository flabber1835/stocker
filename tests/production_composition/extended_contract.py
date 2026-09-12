"""Second-layer production fault catalogue for composition seams.

The base contract proves authority edges.  This contract targets faults that only
appear when already-correct components are composed across host/runtime/persistence
boundaries.  Every category is exercised with the same deterministic campaign so
new production seams cannot quietly remain happy-path only.
"""
from __future__ import annotations

from dataclasses import dataclass


EXTENDED_VARIANTS = (
    "happy",
    "crash_before",
    "crash_after",
    "stale",
    "corrupt",
    "retry",
    "concurrent",
    "reboot",
)


@dataclass(frozen=True)
class FaultCategory:
    name: str
    description: str
    requires_real_boundary: bool = True


FAULT_CATEGORIES = (
    FaultCategory("cold_reboot", "cold NAS restart with no inherited process authority"),
    FaultCategory("restore_upgrade_go", "restored persisted state upgraded through current GO"),
    FaultCategory("phase_boundary_kill", "SIGTERM/SIGKILL around every mutable GO boundary"),
    FaultCategory("filesystem_nas_fault", "rename/fsync/permission/read-only/storage faults"),
    FaultCategory("docker_lifecycle_fault", "daemon/container/network/image lifecycle faults"),
    FaultCategory("concurrency_cross_actor", "GO racing backup/ingest/automation/panel/another GO"),
    FaultCategory("clock_calendar_boundary", "session/DST/holiday/clock-jump boundaries"),
    FaultCategory("network_auth_partial", "partial GitHub/GHCR/vendor/broker network or auth failure"),
    FaultCategory("promotion_handoff_atomicity", "validated runtime promotion and panel handoff atomicity"),
    FaultCategory("evidence_survivability", "crash-safe authority/evidence artifacts"),
)


EXTENDED_CASES = tuple(
    (category, variant)
    for category in FAULT_CATEGORIES
    for variant in EXTENDED_VARIANTS
)
