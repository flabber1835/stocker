#!/usr/bin/env python3
"""Gap-safe causal wrapper for the historical IWB/R1000 proxy builder.

The BlackRock/iShares historical holdings archive is sparse on some month-end
request dates. A missing month-end snapshot must not abort the PIT experiment
and must never be filled from the future. This wrapper carries the most recent
successfully authenticated prior snapshot until a newer historical snapshot is
available, with a hard staleness ceiling.

This changes only membership acquisition robustness. It does not alter Wealth
Core, Sentinel, LD-RC, peer construction, or any strategy parameter.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pandas as pd

from backtester import build_r1000_iwb_membership_sep as base

MAX_STALENESS_DAYS = int(os.environ.get("R1000_MAX_STALENESS_DAYS", "62"))
_original_resolve_snapshot = base.resolve_snapshot
_last_successful_snapshot: dict | None = None
_carry_events: list[dict] = []


def resolve_snapshot_gap_safe(requested: pd.Timestamp, max_lookback_days: int = 7) -> dict:
    """Resolve a contemporaneous snapshot or causally carry the last known one."""
    global _last_successful_snapshot
    requested = pd.Timestamp(requested).normalize()
    try:
        snapshot = _original_resolve_snapshot(requested, max_lookback_days)
    except RuntimeError as exc:
        if _last_successful_snapshot is None:
            raise
        prior_as_of = pd.Timestamp(_last_successful_snapshot["as_of_date"]).normalize()
        staleness_days = int((requested - prior_as_of).days)
        if staleness_days < 0 or staleness_days > MAX_STALENESS_DAYS:
            raise RuntimeError(
                f"R1000 archive gap exceeds causal carry ceiling before {requested.date()}: "
                f"prior_as_of={prior_as_of.date()} staleness_days={staleness_days} "
                f"max={MAX_STALENESS_DAYS}"
            ) from exc
        carried = deepcopy(_last_successful_snapshot)
        carried["requested_date"] = requested.strftime("%Y-%m-%d")
        carried["lookback_days"] = staleness_days
        carried["carried_forward"] = True
        _carry_events.append(
            {
                "requested_date": requested.strftime("%Y-%m-%d"),
                "carried_as_of": prior_as_of.strftime("%Y-%m-%d"),
                "staleness_days": staleness_days,
                "reason": str(exc),
            }
        )
        print(
            f"[R1000] no new authenticated snapshot near {requested.date()}; "
            f"carry prior as-of {prior_as_of.date()} ({staleness_days} days stale)",
            flush=True,
        )
        return carried

    snapshot = deepcopy(snapshot)
    snapshot["carried_forward"] = False
    _last_successful_snapshot = deepcopy(snapshot)
    return snapshot


def _output_dir_from_argv() -> Path:
    for index, value in enumerate(sys.argv[:-1]):
        if value == "--output":
            return Path(sys.argv[index + 1])
    raise RuntimeError("--output is required")


def main() -> int:
    base.resolve_snapshot = resolve_snapshot_gap_safe
    rc = base.main()
    output = _output_dir_from_argv()
    manifest_path = output / "r1000_iwb_membership_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive_gap_policy"] = (
        "when no new snapshot exists within the normal 7-day backward probe, "
        "carry the latest authenticated prior snapshot; never use a future snapshot"
    )
    manifest["maximum_allowed_staleness_days"] = MAX_STALENESS_DAYS
    manifest["carried_forward_request_count"] = len(_carry_events)
    manifest["maximum_carried_staleness_days"] = max(
        (event["staleness_days"] for event in _carry_events), default=0
    )
    manifest["carried_forward_requests"] = _carry_events
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"[R1000] archive gaps carried={len(_carry_events)} "
        f"max_staleness_days={manifest['maximum_carried_staleness_days']}",
        flush=True,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
