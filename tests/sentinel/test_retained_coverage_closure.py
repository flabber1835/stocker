"""Audit-only fault probes: preservation of publication-bound action coverage."""
from datetime import date

import psycopg
import pytest

from sentinel.execution import feed_actions
from tests.sentinel.test_rolling_history_retention import (  # noqa: F401
    conn, pg, source, operational_source, aged)


@pytest.mark.parametrize('version', [1, 2, 3])
def test_missing_required_coverage_refuses_before_reconciliation(conn, aged, version):
    start, end = date(2024, 12, 13), date(2026, 9, 14)
    assert feed_actions.action_lookup(conn, start=start, end=end)('1') == 6
    conn.execute('SET LOCAL session_replication_role=replica')
    conn.execute('DELETE FROM sentinel_action_coverage WHERE publication_version=%s', (version,))
    conn.commit()
    with psycopg.connect(conn.info.dsn) as restarted:
        with pytest.raises(ValueError, match='RETAINED_ACTION_COVERAGE_MISSING'):
            feed_actions.action_lookup(restarted, start=start, end=end)
__all__ = ['aged', 'conn', 'operational_source', 'pg', 'source']
