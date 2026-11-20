"""Bounded public coverage fields shared by the runtime and the standalone NAS reader."""
import json
import re

# Released host evidence limit after its 49-character framing prefix.
MAX_STRUCTURED_CHARS = 32719
FAILURE_MARKER = "SENTINEL_GO_PREPARATION_FAILURE="
_PROHIBITED = ("http://", "https://", "api_key", "api-key", "password",
               "authorization", "postgres://", "postgresql://", "apca-api-")


def _bounded_public(value, depth=0):
    if depth > 7:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if isinstance(value, str):
        return (len(value) <= 256 and "\n" not in value and "\r" not in value
                and not any(word in value.lower() for word in _PROHIBITED))
    if isinstance(value, list):
        return len(value) <= 16 and all(_bounded_public(v, depth + 1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 16 and all(
            isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k)
            and _bounded_public(v, depth + 1) for k, v in value.items())
    return False


def public_coverage(value):
    """Project validated fields before attaching any child-supplied data to a bundle."""
    if not isinstance(value, dict):
        return None
    keys = ("session", "expected_eligible", "received_eligible", "missing_eligible_total",
            "missing_eligible", "unresolved_source_tickers", "unexpected_eligible_total",
            "unexpected_eligible", "unresolved_eligible_risk_total", "identity_diagnostics",
            "identity_collision_total", "collision_source_rows_total", "identity_collisions",
            "collision_sha256")
    result = {key: value[key] for key in keys if key in value}
    if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(result.get("session", "")))
            or not _bounded_public(result)):
        return None
    return result


def collect_source_coverage(output):
    """Parse the final marker defensively before placing its data in the ZIP."""
    for line in reversed(str(output or "").splitlines()):
        if not line.startswith(FAILURE_MARKER) or len(line) > 65536:
            continue
        try:
            payload = json.loads(line[len(FAILURE_MARKER):])
            value = payload.get("source_coverage")
        except (ValueError, TypeError, AttributeError, RecursionError):
            continue
        if value is not None:
            # Keep the historical maximum serialized payload size of a coverage
            # record, independently of the runtime's source-specific wire prefix.
            try:
                if len(json.dumps(value)) > MAX_STRUCTURED_CHARS:
                    return None
            except (ValueError, TypeError, RecursionError):
                return None
            return public_coverage(value)
    return None
