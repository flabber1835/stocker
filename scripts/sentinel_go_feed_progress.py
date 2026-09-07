"""Strict, bounded parsing of credential-free feed progress on Python 3.8."""
import json
import re
from datetime import datetime

PREFIX = "SENTINEL_FEED_PROGRESS="
STAGES = frozenset({
    "actions_export", "actions_refresh", "identity_preflight", "identity_rebuild",
    "seed_database_replay", "post_seed_proof", "database_tickers",
    "database_actions", "database_spy", "database_prices",
} | {kind + "_" + table for kind in ("capture", "download")
     for table in ("sep", "sfp", "tickers", "actions")})


def parse(line):
    if len(line) > 512 or not line.startswith(PREFIX):
        return None
    try:
        value = json.loads(line[len(PREFIX):])
    except (ValueError, TypeError):
        return None
    required = {"stage", "status", "rows", "elapsed_ms"}
    if not isinstance(value, dict) or set(value) not in (
            required, required | {"refreshed_at", "snapshot_at"}):
        return None
    for field in ("refreshed_at", "snapshot_at"):
        if field in value:
            stamp = value[field]
            if not isinstance(stamp, str) or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", stamp):
                return None
            try:
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                return None
    if not isinstance(value["stage"], str) or value["stage"] not in STAGES:
        return None
    if not isinstance(value["status"], str) or value["status"] not in {
            "started", "working", "completed", "failed", "selected", "observed"}:
        return None
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10**12
           for k in ("rows", "elapsed_ms")):
        return None
    return value


def collect(output):
    events = []
    for line in output.splitlines():
        value = parse(line)
        if value is not None:
            events.append(value)
    # Keep final failure/proof events as well as bounded source progress.
    return events[-512:]
