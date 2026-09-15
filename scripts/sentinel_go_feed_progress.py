"""Strict, bounded parsing of credential-free feed progress on Python 3.8."""
import json
import re
from datetime import datetime

PREFIX = "SENTINEL_FEED_PROGRESS="
STAGES = frozenset({
    "actions_export", "actions_refresh", "identity_preflight", "identity_rebuild",
    "seed_membership_preflight",
    "seed_database_replay", "post_seed_proof", "database_tickers",
    "database_actions", "database_spy", "database_prices",
    "source_preflight", "export_preflight", "source_download", "source_refresh",
    "source_replay", "bounded_recovery", "corpus_publication", "database_connect", "readiness_check",
    "backup_durability", "schema_migration", "daily_catchup", "publication_check",
    "readiness_history", "readiness_domains", "readiness_splits", "readiness_maintenance",
} | {kind + "_" + table for kind in ("capture", "download")
     for table in ("sep", "sfp", "tickers", "actions")})


def parse(line):
    if len(line) > 1024 or not line.startswith(PREFIX):
        return None
    try:
        value = json.loads(line[len(PREFIX):])
    except (ValueError, TypeError):
        return None
    required = {"stage", "status", "rows", "elapsed_ms"}
    optional = {"refreshed_at", "snapshot_at", "table", "date_from", "date_to",
                "updated_from", "updated_to", "part", "parts", "reason",
                "ready", "retry_seconds", "remaining_seconds", "bytes"}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        return None
    if "reason" in value and (not isinstance(value["reason"], str)
                             or not re.fullmatch(r"[A-Z][A-Z_0-9]{0,79}", value["reason"])):
        return None
    if "table" in value and (not isinstance(value["table"], str)
                             or value["table"] not in {"SEP", "SFP", "TICKERS", "ACTIONS"}):
        return None
    for field in ("date_from", "date_to", "updated_from", "updated_to"):
        if field in value:
            day = value[field]
            if not isinstance(day, str) or (day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
                return None
            try:
                if day:
                    datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                return None
    for field in ("part", "parts"):
        if field in value and (type(value[field]) is not int or not 1 <= value[field] <= 1000):
            return None
    for field in ("ready", "retry_seconds", "remaining_seconds", "bytes"):
        if field in value and (type(value[field]) is not int or not 0 <= value[field] <= 10**12):
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
            "started", "working", "completed", "failed", "selected", "observed",
            "fresh", "creating", "regenerating"}:
        return None
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10**12
           for k in ("rows", "elapsed_ms")):
        return None
    return value


def describe(value):
    text = value["stage"].replace("_", " ")
    if value.get("table"):
        text += " " + value["table"]
    if value.get("date_from") or value.get("date_to"):
        text += " " + (value.get("date_from") or "all") + ".." + (value.get("date_to") or "all")
    if value.get("part") and value.get("parts"):
        text += " partition %s/%s" % (value["part"], value["parts"])
    if value.get("updated_from") or value.get("updated_to"):
        text += "; updated " + (value.get("updated_from") or "all") + ".." + (value.get("updated_to") or "all")
    text += ": %s" % value["status"]
    if value["stage"] not in {"schema_migration", "database_connect", "source_preflight", "export_preflight"}:
        text += "; %s rows" % format(value["rows"], ",")
    if "ready" in value:
        text += "; %s/%s exports ready" % (value["ready"], value.get("parts", "?"))
    if "retry_seconds" in value:
        text += "; next poll in %ss" % value["retry_seconds"]
    if "remaining_seconds" in value:
        text += "; acquisition budget remaining %ss" % value["remaining_seconds"]
    if "bytes" in value:
        text += "; %s bytes received" % format(value["bytes"], ",")
    if value.get("reason"):
        text += "; reason " + value["reason"]
    if value.get("refreshed_at"):
        text += "; refreshed " + value["refreshed_at"]
    if value.get("snapshot_at"):
        text += "; snapshot " + value["snapshot_at"]
    return text


def collect(output):
    events = []
    for line in output.splitlines():
        value = parse(line)
        if value is not None:
            events.append(value)
    # Keep final failure/proof events as well as bounded source progress.
    return events[-512:]
