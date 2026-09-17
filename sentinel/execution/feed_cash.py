"""Bound snapshot inputs for the existing paper-entitlement calculator."""
from sentinel.execution import feed_inputs
from sentinel.feed import calendar
from sentinel.core.terminal import DIVIDEND_ACTIONS


class SnapshotCashInputs:
    def __init__(self, conn, pub):
        self.conn, self.pub = conn, pub
        self.refs = feed_inputs.references(conn, pub)

    def days(self, first, through):
        if str(first) < str(self.refs.manifest.window.start) or str(through) > self.pub.window_end:
            raise feed_inputs.ExecutionInputsRefused("ROLLING_DIVIDEND_HISTORY_UNAVAILABLE")
        return sorted({calendar.session_on_or_after(p["date"]) for _, p, _ in self.refs.actions
                       if str(first) <= p["date"] <= str(through) and p["action"].lower() in DIVIDEND_ACTIONS})

    def bars(self, wanted, held):
        with self.conn.cursor() as cur:
            cur.execute("SELECT security_id,ticker,close_signal,close_unadjusted,dividend_per_share "
                        "FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s "
                        "AND security_id=ANY(%s) ORDER BY security_id", (self.refs.candidate_id, wanted, held))
            return cur.fetchall()

    def actions(self, wanted, tickers):
        return [(p["date"], p["action"], p["ticker"], p["value"], source)
                for source, p, _ in self.refs.actions
                if p["action"].lower() in DIVIDEND_ACTIONS and p["ticker"].upper() in tickers
                and calendar.session_on_or_after(p["date"]) == wanted]

    def defensive_mark(self, wanted):
        with self.conn.cursor() as cur:
            cur.execute("SELECT bil_close_signal,bil_close_unadjusted FROM sentinel_snapshot_benchmarks "
                        "WHERE candidate_id=%s AND session=%s", (self.refs.candidate_id, wanted))
            return cur.fetchone()
