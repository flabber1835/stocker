"""Strict, bounded parsing of credential-free feed progress on Python 3.8."""
import json
import re
from datetime import datetime

PREFIX = "SENTINEL_FEED_PROGRESS="
ALPACA_STAGES = frozenset({"alpaca_part_acquire", "alpaca_part_persist", "alpaca_price_pairing"})
ALPACA_COUNTERS = (
    "requests", "retries", "response_bytes", "rate_limits", "pacing_ms",
    "http_ms", "decode_ms", "retry_backoff_ms",
)
COST_STAGES = frozenset({"rolling_identity", "rolling_normalization", "rolling_seal", "rolling_candidate_seal",
    "rolling_operational_validation", "rolling_source_corroboration",
    "rolling_operational_publication"})
VISIBILITY_STAGE = "rolling_operational_visibility"
STAGES = frozenset({
    "actions_export", "actions_refresh", "identity_preflight", "identity_rebuild",
    "seed_membership_preflight",
    "seed_database_replay", "post_seed_proof", "database_tickers",
    "database_actions", "database_spy", "database_prices",
    "source_preflight", "export_preflight", "source_download", "source_refresh",
    "source_replay", "source_classification", "bounded_recovery", "corpus_publication", "database_connect", "readiness_check",
    "backup_durability", "schema_migration", "daily_catchup", "publication_check",
    "readiness_history", "readiness_domains", "readiness_splits", "readiness_maintenance",
    "rolling_identity", "rolling_normalization", "rolling_seal", "rolling_candidate_seal",
    "rolling_operational_validation", "rolling_operational_publication",
    "rolling_source_corroboration", "rolling_writer_admission", VISIBILITY_STAGE,
    "rolling_comparison_publication", "historical_formation",
} | ALPACA_STAGES | {kind + "_" + table for kind in ("capture", "download")
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
                "ready", "retry_seconds", "remaining_seconds", "bytes", "job_id", "subphase",
                "sessions", "required_sessions", "session", "component", "selected",
                "cpu_ms", "commit_observed_at"}
    if isinstance(value, dict) and value.get("stage") == "alpaca_part_acquire":
        required.update(ALPACA_COUNTERS)
    elif (isinstance(value, dict) and value.get("stage") == "rolling_source_corroboration"
            and set(ALPACA_COUNTERS) & set(value)):
        if value.get("status") not in ("completed", "failed"):
            return None
        required.update(ALPACA_COUNTERS)
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        return None
    if not isinstance(value["stage"], str) or value["stage"] not in STAGES:
        return None
    if "cpu_ms" in value and (value["stage"] not in COST_STAGES
            or value["status"] not in ("completed", "failed")
            or type(value["cpu_ms"]) is not int or not 0 <= value["cpu_ms"] <= 10**12):
        return None
    if value["stage"] == VISIBILITY_STAGE:
        if (set(value) != required | {"job_id", "commit_observed_at"}
                or value["status"] != "completed" or value["rows"] != 0 or value["elapsed_ms"] != 0):
            return None
    elif "commit_observed_at" in value:
        return None
    if value["stage"] == "rolling_writer_admission" and (
            set(value) != required | {"job_id", "reason"}
            or value["status"] != "completed" or value["rows"] != 0
            or value["reason"] not in ("ACQUISITION", "PUBLICATION")):
        return None
    if value.get("stage") == "historical_formation":
        if (type(value.get("sessions")) is not int or not 0 <= value["sessions"] <= 126
                or type(value.get("required_sessions")) is not int or value["required_sessions"] != 126):
            return None
    elif {"sessions", "required_sessions", "session"} & set(value):
        return None
    if "job_id" in value and (not isinstance(value["job_id"], str) or not re.fullmatch(
            r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", value["job_id"])):
        return None
    if "subphase" in value and (not isinstance(value["subphase"], str)
                               or value["subphase"] not in {"alias_discovery", "independent_coverage", "alpaca_admission"}):
        return None
    if 'component' in value and (value.get('table') != 'TICKERS'
            or not isinstance(value['component'],str)
            or not re.fullmatch(r'TICKERS\.(ASSETS|PLAN|FIGI\.[1-9][0-9]{0,4})',value['component'])):
        return None
    if 'selected' in value and (value['stage'] != 'rolling_identity'
            or value.get('subphase') != 'alpaca_admission'
            or type(value['selected']) is not int or not 0 <= value['selected'] <= 100000):
        return None
    if "reason" in value and (not isinstance(value["reason"], str)
                             or not re.fullmatch(r"[A-Z][A-Z_0-9]{0,79}", value["reason"])):
        return None
    if "table" in value and (not isinstance(value["table"], str)
                             or value["table"] not in {"SEP", "SFP", "TICKERS", "ACTIONS"}):
        return None
    for field in ("date_from", "date_to", "updated_from", "updated_to", "session"):
        if field in value:
            day = value[field]
            if field == "session" and not day:
                return None
            if not isinstance(day, str) or (day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
                return None
            try:
                if day:
                    datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                return None
    for field in ("part", "parts"):
        maximum = 99999 if value.get('stage') == 'source_classification' else 1000
        if field in value and (type(value[field]) is not int or not 1 <= value[field] <= maximum):
            return None
    for field in ("ready", "retry_seconds", "remaining_seconds", "bytes"):
        if field in value and (type(value[field]) is not int or not 0 <= value[field] <= 10**12):
            return None
    for field in ("refreshed_at", "snapshot_at", "commit_observed_at"):
        if field in value:
            stamp = value[field]
            if not isinstance(stamp, str) or not re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", stamp):
                return None
            try:
                datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                return None
    if not isinstance(value["status"], str) or value["status"] not in {
            "started", "working", "completed", "failed", "selected", "observed",
            "fresh", "creating", "regenerating"}:
        return None
    if any(type(value[k]) is not int or not 0 <= value[k] <= 10**12
           for k in required - {"stage", "status"}):
        return None
    return value


def describe(value):
    if value["stage"] == VISIBILITY_STAGE:
        return "closing publication commit observed at " + value["commit_observed_at"]
    if value["stage"] == "rolling_writer_admission":
        return "%s writer admission in %s ms" % (
            value["reason"].lower(), format(value["elapsed_ms"], ","))
    text = value["stage"].replace("_", " ")
    if value.get("subphase"):
        text += " " + value["subphase"].replace("_", " ")
    if value.get("table"):
        text += " " + (value.get('component') or value["table"])
    if value.get("date_from") or value.get("date_to"):
        text += " " + (value.get("date_from") or "all") + ".." + (value.get("date_to") or "all")
    if value.get("part") and value.get("parts"):
        text += " partition %s/%s" % (value["part"], value["parts"])
    if value.get("updated_from") or value.get("updated_to"):
        text += "; updated " + (value.get("updated_from") or "all") + ".." + (value.get("updated_to") or "all")
    text += ": %s" % value["status"]
    if value["stage"] == "historical_formation":
        text += "; %s/%s sessions" % (value["sessions"], value["required_sessions"])
        if value.get("session"):
            text += "; through " + value["session"]
    elif value["stage"] in {"rolling_normalization", "rolling_candidate_seal"} and value.get("rows"):
        text += "; %s equity price rows" % format(value["rows"], ",")
    elif value["stage"] not in {"schema_migration", "database_connect", "source_preflight", "export_preflight"}:
        text += "; %s rows" % format(value["rows"], ",")
    if "ready" in value:
        text += "; %s/%s exports ready" % (value["ready"], value.get("parts", "?"))
    if "retry_seconds" in value:
        text += "; next poll in %ss" % value["retry_seconds"]
    if "remaining_seconds" in value:
        text += "; acquisition budget remaining %ss" % value["remaining_seconds"]
    if "bytes" in value:
        text += "; %s bytes received" % format(value["bytes"], ",")
    if value["stage"] in ALPACA_STAGES and value["status"] in {"completed", "failed"}:
        text += "; elapsed %s ms" % format(value["elapsed_ms"], ",")
    if set(ALPACA_COUNTERS).issubset(value):
        text += (
            "; %(requests)s requests, %(retries)s retries, %(rate_limits)s rate limits,"
            " %(response_bytes)s bytes received, %(pacing_ms)s ms pacing, %(http_ms)s ms HTTP,"
            " %(decode_ms)s ms decoding, %(retry_backoff_ms)s ms retry backoff"
        ) % value
    if "cpu_ms" in value:
        text += "; %s ms elapsed, %s ms publisher CPU" % (
            format(value["elapsed_ms"], ","), format(value["cpu_ms"], ","))
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
