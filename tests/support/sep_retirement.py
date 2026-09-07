"""Synthetic dual-source authority for retirement mutation boundary tests."""
from __future__ import annotations

import datetime as dt

from sentinel.feed import sep_negative_space_guarded as guarded


def authorized_plan(keys, *, publication_version):
    start = min(key["session"] for key in keys)
    end = max(key["session"] for key in keys)
    boundary = "2026-09-07T20:00:00+00:00"
    source = {
        "authority": "nasdaq-data-link-table-export-composite/v1",
        "table": "SEP", "window": [start, end], "source_rows": 0,
        "observation_ceiling": "2026-09-07",
        "source_observation_boundary": boundary,
        "last_refreshed_time": "2026-09-07T19:59:00+00:00",
    }
    actions = {
        "authority": "nasdaq-data-link-table-export/v1", "table": "ACTIONS",
        "source_rows": 0, "verified_distinct_rows": 0,
        "verified_publication_version": publication_version,
        "verified_through": end,
        "data_snapshot_time": "2026-09-07T19:58:30+00:00",
        "last_refreshed_time": "2026-09-07T19:58:00+00:00",
    }

    def replay(*_args, **_kwargs):
        return iter(())

    replay._sentinel_sep_retirement_capability = guarded._SEP_RETIREMENT_CAPABILITY
    token = guarded._require_production_retirement_authority(
        source_authority_evidence=source, actions_authority_evidence=actions,
        observation_ceiling=dt.date(2026, 9, 7),
        source_observation_boundary=boundary, fetch=replay,
        start=start, end=end, source_rows=0)
    plan = {
        "schema": guarded.SCHEMA, "interval": [start, end], "count": len(keys),
        "keys": keys, "keys_sha256": guarded.core._keys_digest(keys),
        "source_rows": 0, "source_authority": source, "actions_authority": actions,
    }
    return plan, token
