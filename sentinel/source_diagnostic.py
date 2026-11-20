"""Decode raw source failures inside the signed runtime."""
import json

from sentinel.archive_identifiers import FEED
from sentinel.source_coverage_summary import FAILURE_MARKER, collect_source_coverage, public_coverage

PREFIX = FEED['SOURCE_COVERAGE_PREFIX']
COLLISION_PREFIX = FEED['SOURCE_COLLISION_PREFIX']


def coverage_diagnostic(raw):
    if not isinstance(raw, str) or len(raw) > 32768:
        return None
    prefix = next((p for p in (PREFIX, COLLISION_PREFIX) if raw.startswith(p)), None)
    if prefix is None:
        return None
    try:
        value = json.loads(raw[len(prefix):])
    except (ValueError, TypeError, RecursionError):
        return None
    return public_coverage(value)
