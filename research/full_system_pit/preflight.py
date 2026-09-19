"""Cheap authority checks that must pass before the physical replay starts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from . import authority as a


class HistoricalAuthorityIncomplete(RuntimeError):
    pass


def production_warmup_sessions() -> list[str]:
    from sentinel.feed.calendar import previous_sessions

    sessions = previous_sessions(
        a.WARMUP, a.PRODUCTION_WARMUP_SESSIONS + 1)
    if len(sessions) != a.PRODUCTION_WARMUP_SESSIONS + 1:
        raise HistoricalAuthorityIncomplete(
            "the production calendar cannot supply the required warmup")
    if sessions[-1] != a.WARMUP:
        raise HistoricalAuthorityIncomplete(
            "the production warmup is not anchored at the first transition")
    return sessions[:-1]


def assess(truth: Path, *, required_sessions=None) -> dict:
    required = list(
        production_warmup_sessions()
        if required_sessions is None else required_sessions)
    with sqlite3.connect(
            f"file:{truth.resolve()}?mode=ro", uri=True) as conn:
        available = {
            str(row[0])
            for row in conn.execute(
                "SELECT day FROM reference WHERE day<? ORDER BY day",
                (a.WARMUP,))
        }
        observations = {
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT day FROM obs WHERE day<? ORDER BY day",
                (a.WARMUP,))
        }
    missing_reference = [day for day in required if day not in available]
    missing_observations = [day for day in required if day not in observations]
    return {
        "schema": "full-system-pit-preflight/1",
        "status": (
            "PASS" if not missing_reference and not missing_observations
            else "REFUSED_INCOMPLETE_PRODUCTION_WARMUP"),
        "first_transition": a.WARMUP,
        "required_sessions": len(required),
        "required_first": required[0] if required else None,
        "required_last": required[-1] if required else None,
        "available_reference_sessions": len(available.intersection(required)),
        "available_observation_sessions": len(
            observations.intersection(required)),
        "missing_reference_sessions": missing_reference,
        "missing_observation_sessions": missing_observations,
    }


def require_authority(truth: Path) -> dict:
    report = assess(truth)
    if report["status"] != "PASS":
        raise HistoricalAuthorityIncomplete(
            "canonical package cannot run the production compact champion from "
            f"{a.WARMUP}: requires {report['required_sessions']} exact prior "
            "XNYS sessions with market, SPY, metadata and terminal authority; "
            f"found {report['available_observation_sessions']} market and "
            f"{report['available_reference_sessions']} SPY sessions")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = assess(args.truth)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["status"] != "PASS":
        raise SystemExit(
            "historical authority refused: immutable pre-2006 production "
            "warmup is incomplete; see " + str(args.output))
