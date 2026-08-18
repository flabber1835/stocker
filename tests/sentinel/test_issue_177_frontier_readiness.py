from __future__ import annotations

import pytest

from sentinel.feed import readiness as R
from tests.sentinel.test_readiness import (  # noqa: F401
    TODAY,
    by_name,
    conn,
    load,
    pg,
    sessions,
)


@pytest.mark.parametrize(
    ("column", "label"),
    [
        ("close_signal", "signal domain"),
        ("open_unadjusted", "raw open"),
        ("volume", "volume"),
    ],
)
def test_current_session_collapse_cannot_be_diluted_by_healthy_history(
        conn, column, label):
    load(conn, n_sessions=300, n_secs=20)
    frontier = sessions(300)[-1]
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE sentinel_bars SET {column}=NULL WHERE session=%s",
            (frontier,))
    conn.commit()

    result = R.check_readiness(conn, today=TODAY)
    checks = by_name(result)

    # This is the issue-177 falsifier: 126 healthy sessions dilute one completely
    # broken newest session to roughly 99.2%, so the historical-density check is
    # intentionally still green. Authority comes from the separate frontier gate.
    assert checks[label].status == R.PASS
    assert checks[f"frontier {label}"].status == R.FAIL
    assert checks[f"frontier {label}"].value["coverage"] == 0.0
    assert checks["frontier population"].status == R.PASS
    assert not result.ready


def test_frontier_raw_close_is_an_explicit_readiness_contract(conn):
    # close_unadjusted is NOT NULL in the schema, so a stored-corpus nullifier is
    # impossible by construction. Issue 177 still requires the domain to be a
    # named frontier contract; missing raw close is caught on raw SEP before the
    # normaliser can drop the row, and this verifies readiness does not omit the
    # corresponding stored-domain verdict.
    load(conn, n_sessions=300, n_secs=20)
    result = R.check_readiness(conn, today=TODAY)
    check = by_name(result)["frontier raw close"]
    assert check.status == R.PASS
    assert check.value["coverage"] == 1.0
