"""One bounded provider snapshot shared by operational source consumers."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar

from sentinel.feed import calendar, progress, sharadar, snapshot_export

MAX_PRICE_SESSIONS = 300
_CURRENT = ContextVar("sentinel_operational_source", default=None)


class OperationalAcquisitionRefused(RuntimeError):
    pass


def current():
    return _CURRENT.get()


def price_window(target: str) -> tuple[str, str]:
    from sentinel.feed.operational_coherence import (
        OPERATIONAL_HISTORY_SESSIONS, ACTION_BOUNDARY_PREDECESSORS)
    required = OPERATIONAL_HISTORY_SESSIONS + ACTION_BOUNDARY_PREDECESSORS
    if required > MAX_PRICE_SESSIONS:
        raise OperationalAcquisitionRefused(
            f"startup requires {required} sessions, exceeding acquisition cap "
            f"{MAX_PRICE_SESSIONS}")
    sessions = calendar.previous_sessions(str(target), MAX_PRICE_SESSIONS)
    if len(sessions) != MAX_PRICE_SESSIONS or sessions[-1] != str(target):
        raise OperationalAcquisitionRefused(
            f"cannot establish {MAX_PRICE_SESSIONS} XNYS sessions through {target}")
    return sessions[0], sessions[-1]


def _months(start, end):
    lo, hi = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while lo <= hi:
        following = (lo.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        last = min(hi, following - dt.timedelta(days=1))
        yield lo.isoformat(), last.isoformat()
        lo = following


class OperationalCapture:
    def __init__(self, start: str, end: str):
        self.start, self.end = str(start), str(end)
        try:
            canonical = all(dt.date.fromisoformat(day).isoformat() == day
                            for day in (self.start, self.end))
        except ValueError:
            canonical = False
        if not canonical or self.start > self.end:
            raise OperationalAcquisitionRefused("acquisition requires ordered ISO date bounds")
        sessions = calendar.sessions_in_range(self.start, self.end)
        if not sessions or len(sessions) > MAX_PRICE_SESSIONS:
            raise OperationalAcquisitionRefused(
                f"acquisition interval {self.start}..{self.end} must contain "
                f"1..{MAX_PRICE_SESSIONS} XNYS sessions")
        self.directory = tempfile.TemporaryDirectory(prefix="sentinel-source-")
        self.db = sqlite3.connect(self.directory.name + "/source.sqlite")
        self.db.execute("CREATE TABLE source (table_code TEXT, day TEXT, "
                        "updated TEXT, ticker TEXT, action TEXT, payload TEXT)")
        self.snapshots = []
        self.evidence = []
        self.loaded = False

    def close(self):
        self.db.close()
        self.directory.cleanup()

    def require_window(self, start, end):
        if str(start) < self.start or str(end) > self.end or str(start) > str(end):
            raise OperationalAcquisitionRefused(
                f"operational acquisition requested {start}..{end}; allowed "
                f"{self.start}..{self.end} ({MAX_PRICE_SESSIONS} sessions); "
                "explicit maintenance is required for older inputs")

    def preflight(self):
        requests = [(sharadar.ACTIONS, {"date.gte": "1900-01-01", "date.lte": self.end}),
                    (sharadar.TICKERS, {})]
        requests.extend((sharadar.SEP, sharadar.date_params(lo, hi))
                        for lo, hi in _months(self.start, self.end))
        with progress.phase("source_preflight", date_from=self.start, date_to=self.end):
            for table, params in requests:
                snapshot = snapshot_export.probe_snapshot(table, params=params)
                self.snapshots.append(snapshot)
        self._require_sep_generation(self.snapshots)

    @staticmethod
    def _require_sep_generation(snapshots):
        markers = {s.refreshed for s in snapshots if s.table == sharadar.SEP}
        if len(markers) != 1:
            from sentinel.feed.authority import VendorPublicationUnstable
            raise VendorPublicationUnstable("bounded SEP export partitions crossed a table refresh")

    def corroborate(self):
        with progress.phase("source_refresh", date_from=self.start, date_to=self.end):
            for captured in self.snapshots:
                checked = snapshot_export.probe_snapshot(captured.table, params=captured.params)
                if checked.refreshed != captured.refreshed:
                    from sentinel.feed.authority import VendorPublicationUnstable
                    raise VendorPublicationUnstable(
                        f"Sharadar {captured.table} refresh changed during bounded acquisition; "
                        "captured inputs cannot publish")

    def acquire(self):
        if self.loaded:
            return
        if not self.snapshots:
            self.preflight()
        required = {
            sharadar.SEP: {"ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"},
            sharadar.ACTIONS: {"date", "action", "ticker", "name", "value", "contraticker", "contraname"},
            sharadar.TICKERS: {"table", "permaticker", "ticker"},
        }
        total = len(self.snapshots)
        for index, snapshot in enumerate(self.snapshots, 1):
            details = {"table": snapshot.table, "date_from": snapshot.params.get("date.gte", ""),
                       "date_to": snapshot.params.get("date.lte", ""),
                       "part": index, "parts": total}
            with progress.phase("source_download", **details) as count:
                rows, evidence = snapshot_export.download_snapshot(
                    snapshot, required=required[snapshot.table])
                if not rows:
                    raise snapshot_export.SharadarSnapshotExportError(
                        f"Sharadar {snapshot.table} bounded export returned zero rows")
                if snapshot.table == sharadar.SEP:
                    from sentinel.feed import session_envelope
                    rows = session_envelope.validate_rows(
                        rows, source="SEP", date_from=snapshot.params["date.gte"],
                        date_to=snapshot.params["date.lte"], operation="operational_capture")
                batch = []
                for row in rows:
                    day = str(row.get("date") or "")
                    if snapshot.table != sharadar.TICKERS and not (
                            snapshot.params["date.gte"] <= day <= snapshot.params["date.lte"]):
                        raise OperationalAcquisitionRefused(
                            f"Sharadar {snapshot.table} export returned off-window date {day}")
                    batch.append((
                        snapshot.table, day, str(row.get("lastupdated") or ""),
                        str(row.get("ticker") or ""), str(row.get("action") or ""), json.dumps(row)))
                    count[0] += 1
                    if len(batch) == 10000:
                        self.db.executemany("INSERT INTO source VALUES (?,?,?,?,?,?)", batch)
                        batch.clear()
                        progress.emit("source_download", "working", rows=count[0], **details)
                self.db.executemany("INSERT INTO source VALUES (?,?,?,?,?,?)", batch)
                self.db.commit()
                self.evidence.append(evidence)
                progress.emit("source_download", "observed", rows=count[0],
                              refreshed_at=snapshot.refreshed.isoformat(),
                              snapshot_at=snapshot.snapshot.isoformat(), **details)
        self.db.execute("CREATE INDEX source_dates ON source(table_code, day)")
        self.db.execute("CREATE INDEX source_updates ON source(table_code, updated)")
        self.corroborate()
        self.loaded = True

    def fetch_rows(self, table, params=None):
        if table not in (sharadar.SEP, sharadar.ACTIONS, sharadar.TICKERS):
            raise OperationalAcquisitionRefused("unsupported operational snapshot table")
        params = dict(params or {})
        allowed = {"date.gte", "date.lte", "lastupdated.gte", "lastupdated.lte", "ticker"}
        if table == sharadar.ACTIONS:
            allowed.add("action")
        if set(params) - allowed:
            raise OperationalAcquisitionRefused("unsupported operational snapshot request")
        if table == sharadar.SEP:
            self.require_window(params.get("date.gte", self.start), params.get("date.lte", self.end))
        self.acquire()
        clauses, values = ["table_code=?"], [table]
        for field, column, op in (("date.gte", "day", ">="), ("date.lte", "day", "<="),
                                  ("lastupdated.gte", "updated", ">="), ("lastupdated.lte", "updated", "<=")):
            if field in params:
                clauses.append(f"{column}{op}?")
                values.append(str(params[field]))
        for field in ("ticker", "action"):
            if field in params:
                selected = str(params[field]).split(",")
                clauses.append(field + " IN (" + ",".join("?" for _ in selected) + ")")
                values.extend(selected)
        details = {"table": table,
                   "date_from": params.get("date.gte", self.start if table == sharadar.SEP else ""),
                   "date_to": params.get("date.lte", self.end if table == sharadar.SEP else "")}
        if "lastupdated.gte" in params:
            details["updated_from"] = params["lastupdated.gte"]
        if "lastupdated.lte" in params:
            details["updated_to"] = params["lastupdated.lte"]
        progress.emit("source_replay", "started", **details)
        count = 0
        for (payload,) in self.db.execute("SELECT payload FROM source WHERE " + " AND ".join(clauses), values):
            count += 1
            if count % 100000 == 0:
                progress.emit("source_replay", "working", rows=count, **details)
            yield json.loads(payload)
        progress.emit("source_replay", "completed", rows=count, **details)

    def export_rows(self, table, params, *, required):
        rows = list(self.fetch_rows(table, params))
        if any(not required.issubset(row) for row in rows):
            raise snapshot_export.SharadarSnapshotExportError("captured export lacks required columns")
        parts = [e for e in self.evidence if e["table"] == table]
        return rows, {**parts[0], "source_rows": len(rows), "parts": parts,
                      "window": dict(params or {})}


@contextmanager
def acquisition(start, end):
    existing = current()
    if existing is not None:
        existing.require_window(start, end)
        yield existing
        return
    capture = OperationalCapture(start, end)
    token = _CURRENT.set(capture)
    try:
        capture.preflight()
        yield capture
    finally:
        _CURRENT.reset(token)
        capture.close()
