"""Pure authority for continuing a path-dependent state across publications."""
from __future__ import annotations

from datetime import date
from typing import Mapping

SCHEMA = "sentinel.strategy-history-mutations/1"


class HistoryReconstructionRequired(ValueError):
    """A prior state cannot acquire the newer publication's historical identity."""


def validate_proof(proof: Mapping, *, version: int) -> dict:
    if not isinstance(proof, Mapping) or set(proof) != {
            "schema", "baseline_version", "publication_version", "changes"}:
        raise HistoryReconstructionRequired("historical mutation proof is missing or malformed")
    baseline = proof["baseline_version"]
    if (proof["schema"] != SCHEMA or type(baseline) is not int
            or baseline < 0 or type(proof["publication_version"]) is not int
            or proof["publication_version"] != version or baseline > version
            or not isinstance(proof["changes"], (list, tuple))):
        raise HistoryReconstructionRequired("historical mutation proof has invalid authority")
    previous = baseline
    changes = []
    for item in proof["changes"]:
        if (not isinstance(item, (list, tuple)) or len(item) != 2
                or type(item[0]) is not int or not previous < item[0] <= version
                or not isinstance(item[1], str)):
            raise HistoryReconstructionRequired("historical mutation proof has invalid ordering")
        try:
            day = date.fromisoformat(item[1]).isoformat()
        except ValueError as exc:
            raise HistoryReconstructionRequired("historical mutation proof has invalid date") from exc
        if day != item[1]:
            raise HistoryReconstructionRequired("historical mutation date is not canonical")
        changes.append([item[0], day])
        previous = item[0]
    return {**proof, "changes": changes}


def require_history_compatible(*, prior_version: int | None,
                               last_processed_session: str | None,
                               version: int, proof: Mapping | None) -> None:
    if prior_version is None or version == prior_version:
        return
    if version < prior_version:
        raise HistoryReconstructionRequired("corpus publication version moved backwards")
    checked = validate_proof(proof, version=version)
    if prior_version < checked["baseline_version"]:
        raise HistoryReconstructionRequired("historical mutation proof does not cover prior state")
    for changed_version, session in checked["changes"]:
        if (changed_version > prior_version and last_processed_session is not None
                and session <= last_processed_session):
            raise HistoryReconstructionRequired(
                f"STRATEGY_HISTORY_RECONSTRUCTION_REQUIRED: publication {changed_version} "
                f"changed history from {session}, at or before processed frontier "
                f"{last_processed_session}; retained state remains at publication {prior_version}")
