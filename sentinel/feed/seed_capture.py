"""Capture coherent seed inputs before replaying expensive database work."""
from __future__ import annotations

import datetime as dt
import pickle
import tempfile
from contextlib import ExitStack

from sentinel.feed import progress, sharadar, snapshot_export


class ActionsSnapshotSource:
    """One complete ACTIONS file corroborated by an independent refresh read."""

    def __init__(self, fetch):
        self.fetch = fetch
        self.request = None
        self.rows = None
        self.evidence = None

    def __call__(self, table, params=None, **kwargs):
        if table != sharadar.ACTIONS:
            def download():
                with progress.phase("download_" + table.lower()) as count:
                    for row in self.fetch(table, params, **kwargs):
                        count[0] += 1
                        if count[0] % 100000 == 0:
                            progress.emit("download_" + table.lower(), "working",
                                          rows=count[0])
                        yield row
            return download()
        request = dict(params or {})
        if set(request) != {"date.gte", "date.lte"}:
            raise ValueError("seed ACTIONS snapshot requires an exact date interval")
        lo, hi = (dt.date.fromisoformat(str(request[key]))
                  for key in ("date.gte", "date.lte"))
        if lo > hi or lo < dt.date(1900, 1, 1):
            raise ValueError("invalid seed ACTIONS snapshot interval")
        if self.request is None:
            with progress.phase("actions_export") as count:
                rows, evidence = snapshot_export.fetch_complete_actions(
                    through=hi.isoformat(), **kwargs)
                for row in rows:
                    day = dt.date.fromisoformat(str(row.get("date")))
                    if not dt.date(1900, 1, 1) <= day <= hi:
                        raise snapshot_export.SharadarSnapshotExportError(
                            "ACTIONS export row lies outside its requested interval")
                if not rows:
                    raise snapshot_export.SharadarSnapshotExportError(
                        "complete seed ACTIONS export returned zero rows")
                self.rows = [dict(row) for row in rows
                             if str(row["date"]) >= lo.isoformat()]
                self.evidence = evidence
                self.request = request
                count[0] = len(self.rows)
                progress.emit("actions_export", "observed", rows=len(self.rows),
                              refreshed_at=evidence["last_refreshed_time"],
                              snapshot_at=evidence["data_snapshot_time"])
        else:
            if self.request != request:
                raise ValueError("seed ACTIONS snapshot request changed")
            with progress.phase("actions_refresh"):
                checked = snapshot_export.require_actions_refresh(
                    through=hi.isoformat(), evidence=self.evidence, **kwargs)
                progress.emit("actions_refresh", "observed",
                              refreshed_at=checked["last_refreshed_time"],
                              snapshot_at=checked["data_snapshot_time"])
        return (dict(row) for row in self.rows)


class CapturedRows:
    """Private disk spools indexed by exact source request; no transport fallback."""

    def __init__(self):
        self.stack = ExitStack()
        self.files = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stack.close()

    @staticmethod
    def key(table, params):
        return table, tuple(sorted((params or {}).items()))

    def capture(self, fetch, table, params=None):
        key = self.key(table, params)
        if key in self.files:
            raise ValueError("duplicate seed capture request")
        spool = self.stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
        with progress.phase("capture_" + table.lower()) as count:
            for row in fetch(table, params):
                pickle.dump(dict(row), spool, protocol=pickle.HIGHEST_PROTOCOL)
                count[0] += 1
                if count[0] % 100000 == 0:
                    progress.emit("capture_" + table.lower(), "working", rows=count[0])
        self.files[key] = spool

    def __call__(self, table, params=None, **kwargs):
        if kwargs:
            raise ValueError("captured seed replay does not accept transport options")
        spool = self.files[self.key(table, params)]
        spool.seek(0)
        while True:
            try:
                yield pickle.load(spool)
            except EOFError:
                return


def run_generation(conn, *, recovery_plan, fetch, final_hi, boundary,
                   resolve_identity=None):
    from sentinel.feed import calendar, ingest

    source = ActionsSnapshotSource(fetch)
    tracked, guarded = ingest._seed_source(
        fetch, final_hi=final_hi, update_ceiling=boundary,
        acquisition_fetch=source)
    lo, hi = recovery_plan.date_from, recovery_plan.date_to
    with CapturedRows() as captured:
        captured.capture(guarded, sharadar.TICKERS)
        plan = None
        with progress.phase("identity_preflight"):
            try:
                ingest.identity_refresh.assert_candidate_history_safe(
                    conn, captured(sharadar.TICKERS))
            except ingest.universe.HistoricalIdentityMutation:
                plan = ingest.identity_rebuild.prepare(conn, date_from=lo, date_to=hi)
                progress.emit("identity_rebuild", "selected")
        full = plan is not None or bool(recovery_plan.retired_run_ids)
        action_start = (ingest.maintenance.ACTIONS_FULL_WINDOW_START if full
                        else calendar.action_date_window(lo, hi)[0])
        captured.capture(guarded, sharadar.ACTIONS,
                         sharadar.date_params(action_start, hi))
        captured.capture(guarded, sharadar.SFP,
                         {"ticker": ingest.SFP_REFERENCE_TICKERS,
                          **sharadar.date_params(lo, hi)})
        for start, end in sharadar.year_chunks(lo, hi):
            captured.capture(guarded, sharadar.SEP, sharadar.date_params(start, end))
        source.rows = None  # Database replay reads the private disk capture.
        authority = ingest._seed_authority(
            boundary=boundary, tracked=tracked, source_fetch=fetch,
            market_start=lo, market_end=hi, resolve_identity=resolve_identity)
        with progress.phase("seed_database_replay"):
            if full:
                result = ingest.reseed.full_reseed_locked(
                    conn, date_from=lo, date_to=hi, fetch=captured,
                    resolve_identity=resolve_identity, identity_rebuild_plan=plan,
                    on_run_started=authority.run_started,
                    before_success=authority.before_success,
                    record_identity_plan=authority.record_identity_plan)
            else:
                result = ingest._ordinary_seed_generation(
                    conn, date_from=lo, date_to=hi, fetch=captured,
                    resolve_identity=resolve_identity, seed_authority=authority)
        return result, tracked
