"""Deterministic captured table fixtures for offline economic replay."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import random
import zipfile


from .model import Step
from .oracle import canonical_bytes, digest


COLUMNS = {
    "SEP": ("ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"),
    "SFP": ("ticker", "date", "open", "close", "closeadj", "closeunadj"),
    "TICKERS": ("table", "permaticker", "ticker", "category", "relatedtickers",
                "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange"),
    "ACTIONS": ("date", "action", "ticker", "name", "value", "contraticker", "contraname"),
}


class Provider:
    def __init__(self, *, page_size: int = 53, variation_seed: int = 0,
                 pending_polls: int = 0):
        if page_size < 1:
            raise ValueError("page size must be positive")
        self.page_size = page_size
        self.variation_seed = variation_seed
        self.pending_polls = pending_polls
        self.transcript: list[dict] = []
        self.step: Step | None = None
        self._views: dict = {}
        self._downloads: dict[str, bytes] = {}
        self._traversals: dict[str, int] = {}
        self._applied: set[str] = set()
        self._date_rows: dict[str, dict[str, list[dict]]] = {}
        self._prepared: dict[str, tuple[tuple, list[dict], bytes]] = {}

    def advance(self, step: Step) -> None:
        if self.step is not None and step.at <= self.step.at:
            raise ValueError("provider time must strictly advance")
        # Detach provider values from both the scenario and expected-state oracle.
        self.step = Step.model_validate_json(step.model_dump_json())
        self._views = dict(self.step.tables)
        self._downloads = {}
        self._traversals = {}
        self._applied = set()
        self._date_rows = {}
        self._prepared = {}

    def assert_revisions_applied(self) -> None:
        missing = {r.name for r in self.step.revisions} - self._applied
        if missing:
            raise AssertionError(f"scheduled provider revisions never activated: {sorted(missing)}")

    def _observation(self, table, channel, query, offset):
        key = json.dumps([table, channel, query], sort_keys=True)
        if offset == 0:
            self._traversals[key] = self._traversals.get(key, 0) + 1
        if key not in self._traversals:
            raise ValueError("cursor has no active source traversal")
        observation = self._traversals[key]
        activated = []
        for revision in self.step.revisions:
            if (revision.name not in self._applied and revision.table == table
                    and revision.channel == channel and revision.observation == observation
                    and offset >= revision.after_rows
                    and all(query.get(k) == v for k, v in revision.query.items())):
                self._views[table] = json.loads(json.dumps(revision.rows))
                self._date_rows.pop(table, None)
                self._prepared.pop(table, None)
                self._applied.add(revision.name)
                activated.append(revision.name)
        return observation, offset, activated

    def rows(self, table: str, query: dict[str, str]) -> list[dict]:
        if table not in COLUMNS:
            raise ValueError(f"unmodeled provider table: {table}")
        identity_filters = {"ACTIONS": {"action", "contraticker"},
                            "TICKERS": {"permaticker"}}.get(table, set())
        permitted = {"ticker", "date.gte", "date.lte", "lastupdated.gte", "lastupdated.lte", "table"}
        permitted |= identity_filters
        if set(query) - permitted:
            raise ValueError(f"unmodeled query fields: {sorted(set(query) - permitted)}")
        candidates = self._views[table]
        if "date.gte" in query or "date.lte" in query:
            if table not in self._date_rows:
                by_date: dict[str, list[dict]] = {}
                for row in candidates:
                    if row.get("date") is not None:
                        by_date.setdefault(str(row["date"]), []).append(row)
                self._date_rows[table] = by_date
            by_date = self._date_rows[table]
            candidates = itertools.chain.from_iterable(
                by_date[day] for day in sorted(by_date)
                if ("date.gte" not in query or day >= query["date.gte"])
                and ("date.lte" not in query or day <= query["date.lte"]))
        rows = []
        for row in candidates:
            if "ticker" in query and row.get("ticker") not in query["ticker"].split(","):
                continue
            if any(field in query and (row.get(field) is None or
                   str(row[field]) not in query[field].split(","))
                   for field in identity_filters):
                continue
            if "table" in query and row.get("table") != query["table"]:
                continue
            if any(key in query and (row.get(field) is None or
                   (str(row[field]) < query[key] if bound == "gte" else
                    str(row[field]) > query[key]))
                   for field in ("date", "lastupdated") for bound in ("gte", "lte")
                   for key in (f"{field}.{bound}",)):
                continue
            rows.append(dict(row))
        rows.sort(key=lambda r: (str(r.get("date", "")), str(r.get("ticker", "")),
                                 json.dumps(r, sort_keys=True)))
        if self.variation_seed:
            # Pagination requests share the same permutation of this query's rows.
            random.Random(self.variation_seed).shuffle(rows)
        return rows

    def _prepare_rows(self, table, query, faults):
        key = (tuple(sorted(query.items())),
               tuple(i for i, fault in enumerate(self.step.faults) if fault in faults))
        cached = self._prepared.get(table)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        rows = self.rows(table, query)
        for fault in faults:
            if fault.kind == "set_value":
                if fault.field not in COLUMNS[table]:
                    raise ValueError("field mutation must name a provider column")
                for row in rows:
                    if fault.ticker is None or row.get("ticker") == fault.ticker:
                        row[fault.field] = fault.value
            elif fault.kind == "omit_ticker":
                rows = [r for r in rows if r.get("ticker") != fault.ticker]
            elif fault.kind == "duplicate_row" and rows:
                rows.append(dict(rows[0]))
            elif fault.kind == "conflicting_row" and rows:
                duplicate = dict(rows[0])
                duplicate["close"] = 999
                rows.append(duplicate)
        encoded = canonical_bytes(rows)
        self._prepared[table] = key, rows, encoded
        return rows, encoded

    @staticmethod
    def _generation_digest(prefix, encoded_rows):
        # Preserve digest([*prefix, rows]) without canonicalizing rows again.
        fingerprint = hashlib.sha256()
        fingerprint.update(canonical_bytes(prefix)[:-1])
        fingerprint.update(b"," if prefix else b"")
        fingerprint.update(encoded_rows)
        fingerprint.update(b"]")
        return fingerprint.hexdigest()

    def captured(self, table, params, channel, *, offset=0):
        from sentinel.feed import archive_tables
        query = dict(params or {})
        observation, _, activated = self._observation(table, channel, query, offset)
        faults = [fault for fault in self.step.faults if fault.table == table and fault.channel == channel
                  and offset >= fault.after_rows and all(query.get(k) == v for k, v in fault.query.items())]
        rows, encoded = self._prepare_rows(table, query, faults)
        kinds = [fault.kind for fault in faults]
        self.transcript.append(dict(step=self.step.name, at=self.step.at.isoformat(), table=table,
            channel=channel, query=query, rows=len(rows), digest=hashlib.sha256(encoded).hexdigest(),
            observation=observation, offset=offset, activated_revisions=activated,
            revision_state=sorted(self._applied), faults=kinds))
        if 'http_400' in kinds:
            raise archive_tables.RequestError('HTTP 400 in the recorded observation')
        if set(kinds) & {'rate_limit', 'service_unavailable'}:
            raise archive_tables.RetryDeferred(3600)
        if set(kinds) & {'repeat_cursor', 'missing_cursor', 'invalid_json', 'row_width'}:
            raise archive_tables.ProtocolError('Recorded table traversal is incomplete')
        return rows, kinds, observation

    def fetch_rows(self, table, params=None):
        from sentinel.feed.archive_tables import ProtocolError
        offset = 0
        while True:
            rows, faults, _ = self.captured(table, params, 'pages', offset=offset)
            if 'missing_column' in faults:
                raise ProtocolError('Recorded table lacks a required column')
            yield from rows[offset:offset + self.page_size]
            offset += self.page_size
            if offset >= len(rows):
                break

    def snapshot(self, table, *, params=None):
        from sentinel.feed import snapshot_export
        rows, kinds, observed = self.captured(table, params, 'export')
        if observed <= self.pending_polls or 'creating_export' in kinds:
            raise snapshot_export.ExportPending(table, 'creating', params or {})
        if 'stale_export' in kinds:
            raise snapshot_export.SnapshotExportError('Captured file predates its generation')
        fields = [f for f in COLUMNS[table] if f != 'ticker' or 'missing_column' not in kinds]
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(zipfile.ZipInfo(table+'.csv', (2000, 1, 1, 0, 0, 0)), output.getvalue(),
                             compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
        raw = b'truncated' if 'invalid_zip' in kinds else buffer.getvalue()
        key = hashlib.sha256(raw).hexdigest()
        self._downloads[key] = raw
        generation = self.step.at - dt.timedelta(minutes=1)
        if any(r.table == table and r.name in self._applied for r in self.step.revisions):
            generation += dt.timedelta(seconds=1)
        return snapshot_export.ExportSnapshot(table, dict(params or {}), key, self.step.at, generation)

    def read_snapshot(self, snapshot, *, required):
        from sentinel.feed import acquisition_work
        raw = self._downloads[snapshot.link]
        if acquisition_work.read_cached(snapshot) is None:
            path = acquisition_work.cache_root() / (acquisition_work.file_key(snapshot) + '.zip')
            path.write_bytes(raw)
            path.with_suffix('.sha256').write_text(snapshot.link)
            self.transcript.append(dict(step=self.step.name, at=self.step.at.isoformat(), table=snapshot.table,
                channel='download', query=dict(snapshot.params), sha256=snapshot.link))
        return self._reader(snapshot, required=required)
