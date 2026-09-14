"""Historical maintenance cannot withdraw publication of later prices."""
import datetime as dt

import pytest

from sentinel.feed import actions_reconcile_v7, calendar, maintenance, sharadar
from sentinel.feed import publication as P
from sentinel.feed import store as S
from test_action_lifecycle import CONTROL_ACTION, _domain_bar, conn, pg  # noqa: F401


@pytest.mark.parametrize("repair", ["action_economics", "sep_mutation"])
def test_historical_repair_preserves_the_published_frontier(conn, repair):
    first, event, frontier = "2024-05-31", "2024-06-03", "2024-08-30"
    axis = calendar.sessions_in_range(first, frontier)
    prices = [dict(ticker="AAA", date=day, open=50., close=50.,
                   closeunadj=100. if day < event else 50., volume=1000000,
                   lastupdated="2024-09-02" if day == event else "2024-08-30")
              for day in axis]
    action_rows = [CONTROL_ACTION, dict(ticker="AAA", date=event,
                   action="split", value=2.0, contraticker=None)]

    def fetch(table, params=None):
        assert table == sharadar.SEP
        params = params or {}
        return [dict(row) for row in prices
                if all(params.get(field + ".gte", "0000-00-00") <= row[field]
                       <= params.get(field + ".lte", "9999-99-99")
                       for field in ("date", "lastupdated"))]

    with S.corpus_write_lock(conn):
        run = S.IngestRun(conn, "fixture", date_from=first, date_to=frontier)
        S.write_actions(conn, action_rows, run_id=run.progress.run_id,
                        window_start="1900-01-01", window_end=frontier)
        S.write_bars(conn, [_domain_bar(row["date"], close_signal=row["close"],
                     raw_close=row["closeunadj"], ratio=2. if row["date"] == event else 1.)
                     for row in prices], run_id=run.progress.run_id, require_lock=True)
        run.finish("success")
        before = P.publish(conn, run_id=run.progress.run_id,
                           window_start=first, window_end=frontier)
        later_before = conn.execute(
            "SELECT session,close_unadjusted,last_written_run_id FROM sentinel_bars "
            "WHERE session>%s ORDER BY session", ("2024-06-04",)).fetchall()
        if repair == "action_economics":
            actions_reconcile_v7._cash_semantic_migration(
                conn, fetch=fetch, through=dt.date.fromisoformat(frontier))
        else:
            maintenance.establish_sep_cursor_after_complete_reconciliation(
                conn, through=dt.date(2024, 9, 1), publication_version=before.version)
            maintenance._reconcile_sep_mutations_core(conn, fetch=fetch, through="2024-09-02")
        after = P.require_current(conn)
        assert after.version > before.version
        assert (after.window_start, after.window_end) == (first, frontier)
        assert after.evidence["replay_windows"][-1]["end"] < frontier
        assert conn.execute(
            "SELECT session,close_unadjusted,last_written_run_id FROM sentinel_bars "
            "WHERE session>%s ORDER BY session", ("2024-06-04",)).fetchall() == later_before
        assert S.latest_visible_session(conn) == frontier
