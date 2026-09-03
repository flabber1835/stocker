#!/usr/bin/env python3
"""Certification-only completeness gate for canonical PIT metadata.

Replay/runtime policy may preserve deterministic behavior when metadata is unknown.
The official PIT certificate has a stronger universe-completeness contract: every
canonical observation that can enter the strategy must have authoritative historical
security type and sector metadata. This module enforces that contract without changing
strategy mechanics or canonical data.
"""
from __future__ import annotations

from collections.abc import Mapping


class CertificationMetadataIncomplete(RuntimeError):
    """Raised when the canonical corpus cannot prove metadata-complete certification."""


_REQUIRED_ZERO_COUNTS = (
    "unknown_security_type_observations",
    "unknown_sector_observations",
    "missing_active_metadata_observations",
)


def _nonnegative_int(counts: Mapping[str, object], key: str) -> int:
    if key not in counts:
        raise CertificationMetadataIncomplete(
            f"PIT metadata completeness cannot be proven: manifest count {key!r} is missing"
        )
    value = counts[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CertificationMetadataIncomplete(
            f"PIT metadata completeness cannot be proven: manifest count {key!r} "
            f"must be a non-negative integer, got {value!r}"
        )
    return value


def require_certification_metadata_complete(manifest: Mapping[str, object]) -> dict[str, int]:
    """Require zero unresolved type/sector observations before official certification.

    Unknown security type can remove a security from the eligible universe. Unknown sector
    changes the sector-grouping semantics through the singleton fallback. Either condition
    means universe behavior depends on missing historical authority and therefore cannot be
    certified as complete.
    """
    counts_obj = manifest.get("counts")
    if not isinstance(counts_obj, Mapping):
        raise CertificationMetadataIncomplete(
            "PIT metadata completeness cannot be proven: manifest counts object is missing"
        )
    counts = {key: _nonnegative_int(counts_obj, key) for key in _REQUIRED_ZERO_COUNTS}

    # In the canonical builder, missing active metadata is exactly the unknown-type set.
    # Keep this explicit invariant in the certificate so a future schema change cannot
    # silently weaken the completeness gate.
    if counts["missing_active_metadata_observations"] != counts["unknown_security_type_observations"]:
        raise CertificationMetadataIncomplete(
            "PIT metadata completeness cannot be proven: canonical metadata counters are "
            "internally inconsistent: "
            f"missing_active_metadata_observations={counts['missing_active_metadata_observations']}, "
            f"unknown_security_type_observations={counts['unknown_security_type_observations']}"
        )

    unresolved = {key: value for key, value in counts.items() if value != 0}
    if unresolved:
        detail = ", ".join(f"{key}={value}" for key, value in unresolved.items())
        raise CertificationMetadataIncomplete(
            "PIT metadata corpus incomplete for official certification: " + detail
        )
    return counts
