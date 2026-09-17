"""Bound snapshot inputs for the existing paper-entitlement calculator."""
from datetime import timedelta
from sentinel.execution import feed_inputs
from sentinel.feed import calendar
from sentinel.core.terminal import DIVIDEND_ACTIONS


class SnapshotCashInputs:
    def __init__(self, conn, pub):
        self.conn, self.pub = conn, pub
        self.refs = feed_inputs.references(conn, pub)

    def days(self, first, through):
        from sentinel.feed import action_history
        if str(through) > self.pub.window_end:
            raise feed_inputs.ExecutionInputsRefused("ROLLING_DIVIDEND_HISTORY_UNAVAILABLE")
        try:
            covered = action_history.coverage(self.conn, self.pub, start=first, end=through)
        except feed_inputs.ExecutionInputsRefused as exc:
            raise feed_inputs.ExecutionInputsRefused("ROLLING_DIVIDEND_HISTORY_UNAVAILABLE") from exc
        if covered is not None:
            self.retained = action_history.records(self.conn, version=self.pub.version,
                start=first - timedelta(days=1), end=through)
            return sorted(day for day, item in self.retained.items()
                          if any(p['action'].lower() in DIVIDEND_ACTIONS for p in item['sources']))
        if str(first) < str(self.refs.manifest.window.start) or str(through) > self.pub.window_end:
            raise feed_inputs.ExecutionInputsRefused("ROLLING_DIVIDEND_HISTORY_UNAVAILABLE")
        return sorted({calendar.session_on_or_after(p["date"]) for _, p, _ in self.refs.actions
                       if str(first) <= p["date"] <= str(through) and p["action"].lower() in DIVIDEND_ACTIONS})

    def bars(self, wanted, held):
        item = self._retained(wanted)
        if item is not None:
            return [tuple(row[:5]) for row in item['bars'] if row[0] in held]
        with self.conn.cursor() as cur:
            cur.execute("SELECT security_id,ticker,close_signal,close_unadjusted,dividend_per_share "
                        "FROM sentinel_snapshot_bars WHERE candidate_id=%s AND session=%s "
                        "AND security_id=ANY(%s) ORDER BY security_id", (self.refs.candidate_id, wanted, held))
            return cur.fetchall()

    def actions(self, wanted, tickers):
        item = self._retained(wanted)
        if item is not None:
            return [(p['date'], p['action'], p['ticker'], p['value'], p['source_row_id'])
                    for p in item['sources'] if p['action'].lower() in DIVIDEND_ACTIONS
                    and p['ticker'].upper() in tickers]
        return [(p["date"], p["action"], p["ticker"], p["value"], source)
                for source, p, _ in self.refs.actions
                if p["action"].lower() in DIVIDEND_ACTIONS and p["ticker"].upper() in tickers
                and calendar.session_on_or_after(p["date"]) == wanted]

    def defensive_mark(self, wanted):
        item = self._retained(wanted)
        if item is not None:
            return tuple(item['defensive'][-1][1:])
        with self.conn.cursor() as cur:
            cur.execute("SELECT bil_close_signal,bil_close_unadjusted FROM sentinel_snapshot_benchmarks "
                        "WHERE candidate_id=%s AND session=%s", (self.refs.candidate_id, wanted))
            return cur.fetchone()

    def _retained(self, wanted):
        from datetime import date, timedelta
        from sentinel.feed import action_history
        day = date.fromisoformat(str(wanted))
        return action_history.records(self.conn, version=self.pub.version,
                                      start=day - timedelta(days=1), end=day).get(str(wanted))
