"""Deterministic Tables/Exporter HTTP simulator. No production imports."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import itertools
import json
import random
import time
import zipfile

import httpx

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
                 pending_polls: int = 0, clock=None, link_lifetime=1800):
        if page_size < 1:
            raise ValueError("page size must be positive")
        self.page_size = page_size
        self.variation_seed = variation_seed
        self.pending_polls = pending_polls
        self.clock = clock or time.monotonic
        self.link_lifetime = link_lifetime
        self._expires = {}
        self.transcript: list[dict] = []
        self.step: Step | None = None
        self._views: dict = {}
        self._downloads: dict[str, bytes] = {}
        self._download_sources: dict[str, dict] = {}
        self._traversals: dict[str, int] = {}
        self._applied: set[str] = set()
        self._date_rows: dict[str, dict[str, list[dict]]] = {}
        self._prepared: dict[str, tuple[tuple, list[dict], bytes]] = {}
        self._exports: dict[str, dict[tuple, tuple[int, str, str]]] = {}

    def advance(self, step: Step) -> None:
        if self.step is not None and step.at <= self.step.at:
            raise ValueError("provider time must strictly advance")
        # Detach provider values from both the scenario and expected-state oracle.
        self.step = Step.model_validate_json(step.model_dump_json())
        self._views = json.loads(json.dumps(self.step.tables))
        self._downloads = {}
        self._download_sources = {}
        self._traversals = {}
        self._applied = set()
        self._date_rows = {}
        self._prepared = {}
        self._exports = {}

    def assert_revisions_applied(self) -> None:
        missing = {r.name for r in self.step.revisions} - self._applied
        if missing:
            raise AssertionError(f"scheduled provider revisions never activated: {sorted(missing)}")

    def _observation(self, table, channel, query):
        filters = {k: v for k, v in query.items() if k not in {"api_key", "qopts.cursor_id"}}
        key = json.dumps([table, channel, filters], sort_keys=True)
        if "qopts.cursor_id" not in query:
            self._traversals[key] = self._traversals.get(key, 0) + 1
        if key not in self._traversals:
            raise ValueError("cursor has no active source traversal")
        observation = self._traversals[key]
        offset = int(query.get("qopts.cursor_id", "0"))
        activated = []
        for revision in self.step.revisions:
            if (revision.name not in self._applied and revision.table == table
                    and revision.channel == channel and revision.observation == observation
                    and offset >= revision.after_rows
                    and all(query.get(k) == v for k, v in revision.query.items())):
                self._views[table] = json.loads(json.dumps(revision.rows))
                self._date_rows.pop(table, None)
                self._prepared.pop(table, None)
                self._exports.pop(table, None)
                self._applied.add(revision.name)
                activated.append(revision.name)
        return observation, offset, activated

    def rows(self, table: str, query: dict[str, str]) -> list[dict]:
        if table not in COLUMNS:
            raise ValueError(f"unmodeled provider table: {table}")
        identity_filters = {"ACTIONS": {"action", "contraticker"},
                            "TICKERS": {"permaticker"}}.get(table, set())
        permitted = {"api_key", "ticker", "date.gte", "date.lte", "lastupdated.gte",
                     "lastupdated.lte", "qopts.cursor_id", "qopts.export", "table"}
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
        key = (tuple(sorted((k, v) for k, v in query.items()
                            if k not in {"api_key", "qopts.cursor_id"})),
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

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.step is None:
            raise RuntimeError("provider has no published view")
        if request.method != "GET":
            raise RuntimeError("simulator permits GET only")
        if request.url.host == "exports.sharadar-replay.invalid":
            if self.clock() >= self._expires.get(str(request.url), float("inf")):
                return httpx.Response(403, request=request)
            body = self._downloads.get(str(request.url))
            if body is None:
                raise RuntimeError("unknown or expired export generation")
            self.transcript.append({"step": self.step.name, "at": self.step.at.isoformat(),
                                    "channel": "download", "sha256": hashlib.sha256(body).hexdigest(),
                                    **self._download_sources[str(request.url)]})
            return httpx.Response(200, content=body, request=request)
        if (request.url.host != "data.nasdaq.com" or
                not request.url.path.startswith("/api/v3/datatables/SHARADAR/")):
            raise RuntimeError("request left the simulated Sharadar boundary")
        table = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        query = dict(request.url.params)
        channel = "export" if query.get("qopts.export") == "true" else "pages"
        observation, offset, activated = self._observation(table, channel, query)
        faults = [f for f in self.step.faults if f.table == table and f.channel == channel
                  and int(query.get("qopts.cursor_id", "0")) >= f.after_rows
                  and all(query.get(k) == v for k, v in f.query.items())]
        export_key = (tuple(sorted(query.items())),
                      tuple(i for i, fault in enumerate(self.step.faults) if fault in faults))
        exported = self._exports.get(table, {}).get(export_key) if channel == "export" else None
        if exported is None:
            rows, encoded_rows = self._prepare_rows(table, query, faults)
            row_count, row_digest = len(rows), hashlib.sha256(encoded_rows).hexdigest()
        else:
            row_count, row_digest, _ = exported
        entry = {"step": self.step.name, "at": self.step.at.isoformat(), "table": table,
                 "channel": channel, "query": {k: v for k, v in query.items() if k != "api_key"},
                 "rows": row_count, "digest": row_digest,
                 "observation": observation, "offset": offset,
                 "activated_revisions": activated, "revision_state": sorted(self._applied),
                 "faults": [f.kind for f in faults]}
        self.transcript.append(entry)
        if any(f.kind in {'rate_limit', 'service_unavailable'} for f in faults):
            status = 429 if any(f.kind == 'rate_limit' for f in faults) else 503
            return httpx.Response(status, headers={'Retry-After': '3600'}, request=request)
        if any(f.kind == "invalid_json" for f in faults):
            return httpx.Response(200, content=b'{"datatable":', request=request)
        if any(f.kind == "http_400" for f in faults):
            return httpx.Response(400, json={"error": "scheduled provider interruption"}, request=request)
        columns = list(COLUMNS[table])
        if any(f.kind == "missing_column" for f in faults):
            columns.remove("ticker")
        if channel == "export":
            if exported is None:
                csv_text = io.StringIO(newline="")
                writer = csv.DictWriter(csv_text, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    info = zipfile.ZipInfo(f"{table}.csv", date_time=(2000, 1, 1, 0, 0, 0))
                    archive.writestr(info, csv_text.getvalue())
                generation = self._generation_digest([self.step.name, table, query], encoded_rows)
                link = f"https://exports.sharadar-replay.invalid/{generation}.zip"
                self._downloads[link] = buffer.getvalue()
                self._expires[link] = self.clock() + self.link_lifetime
                self._download_sources[link] = {"download_table": table,
                    "download_query": {k: v for k, v in query.items() if k != "api_key"},
                    "generation": self._generation_digest([table], encoded_rows)}
                if any(f.kind == "invalid_zip" for f in faults):
                    self._downloads[link] = b"truncated ZIP archive"
                self._exports.setdefault(table, {})[export_key] = row_count, row_digest, link
            else:
                _, _, link = exported
                if self.clock() >= self._expires[link]:
                    old = link
                    link = old.split("?")[0] + f"?renew={observation}"
                    self._downloads[link] = self._downloads[old]
                    self._download_sources[link] = self._download_sources[old]
                    self._expires[link] = self.clock() + self.link_lifetime
                    self._exports[table][export_key] = row_count, row_digest, link
            refreshed = self.step.at - dt.timedelta(minutes=1)
            if any(r.table == table for r in self.step.revisions if r.name in self._applied):
                refreshed += dt.timedelta(seconds=1)
            snapshot = self.step.at
            if any(f.kind == "stale_export" for f in faults):
                snapshot = refreshed - dt.timedelta(minutes=1)
            payload = {"datatable_bulk_download": {
                "file": {"status": "fresh", "link": link,
                         "data_snapshot_time": snapshot.isoformat()},
                "datatable": {"last_refreshed_time": refreshed.isoformat()}}}
            if observation <= self.pending_polls or any(f.kind == "creating_export" for f in faults):
                payload["datatable_bulk_download"]["file"] = {"status": "creating", "link": None}
        else:
            cursor = int(query.get("qopts.cursor_id", "0"))
            page = rows[cursor:cursor + self.page_size]
            next_cursor = str(cursor + self.page_size) if cursor + self.page_size < len(rows) else None
            if any(f.kind == "repeat_cursor" for f in faults) and page:
                next_cursor = str(self.page_size)
            payload = {"datatable": {"columns": [{"name": c} for c in columns],
                                      "data": [[r.get(c) for c in columns] for r in page]},
                       "meta": {"next_cursor_id": next_cursor}}
            if any(f.kind == "row_width" for f in faults) and page:
                payload["datatable"]["data"][0].pop()
            if any(f.kind == "missing_cursor" for f in faults):
                payload["meta"] = {}
        return httpx.Response(200, json=payload, request=request)
