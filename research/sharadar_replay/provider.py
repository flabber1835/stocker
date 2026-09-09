"""Deterministic Tables/Exporter HTTP simulator. No production imports."""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import zipfile

import httpx

from .model import Step
from .oracle import digest


COLUMNS = {
    "SEP": ("ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"),
    "SFP": ("ticker", "date", "open", "close", "closeadj", "closeunadj"),
    "TICKERS": ("table", "permaticker", "ticker", "category", "relatedtickers",
                "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange"),
    "ACTIONS": ("date", "action", "ticker", "name", "value", "contraticker", "contraname"),
}


class Provider:
    def __init__(self, *, page_size: int = 53):
        if page_size < 1:
            raise ValueError("page size must be positive")
        self.page_size = page_size
        self.transcript: list[dict] = []
        self.step: Step | None = None
        self._views: dict = {}
        self._downloads: dict[str, bytes] = {}

    def advance(self, step: Step) -> None:
        if self.step is not None and step.at <= self.step.at:
            raise ValueError("provider time must strictly advance")
        # Detach provider values from both the scenario and expected-state oracle.
        self.step = Step.model_validate_json(step.model_dump_json())
        self._views = json.loads(json.dumps(self.step.tables))
        self._downloads = {}

    def rows(self, table: str, query: dict[str, str]) -> list[dict]:
        if table not in COLUMNS:
            raise ValueError(f"unmodeled provider table: {table}")
        permitted = {"api_key", "ticker", "date.gte", "date.lte", "lastupdated.gte",
                     "lastupdated.lte", "qopts.cursor_id", "qopts.export", "table"}
        if set(query) - permitted:
            raise ValueError(f"unmodeled query fields: {sorted(set(query) - permitted)}")
        rows = []
        for row in self._views[table]:
            if "ticker" in query and row.get("ticker") not in query["ticker"].split(","):
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
        return sorted(rows, key=lambda r: (str(r.get("date", "")), str(r.get("ticker", "")),
                                          json.dumps(r, sort_keys=True)))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.step is None:
            raise RuntimeError("provider has no published view")
        if request.method != "GET":
            raise RuntimeError("simulator permits GET only")
        if request.url.host == "exports.sharadar-replay.invalid":
            body = self._downloads.get(str(request.url))
            if body is None:
                raise RuntimeError("unknown or expired export generation")
            self.transcript.append({"step": self.step.name, "at": self.step.at.isoformat(),
                                    "channel": "download", "sha256": digest(list(body))})
            return httpx.Response(200, content=body, request=request)
        if (request.url.host != "data.nasdaq.com" or
                not request.url.path.startswith("/api/v3/datatables/SHARADAR/")):
            raise RuntimeError("request left the simulated Sharadar boundary")
        table = request.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        query = dict(request.url.params)
        channel = "export" if query.get("qopts.export") == "true" else "pages"
        rows = self.rows(table, query)
        faults = [f for f in self.step.faults if f.table == table and f.channel == channel]
        for fault in faults:
            if fault.kind == "omit_ticker":
                rows = [r for r in rows if r.get("ticker") != fault.ticker]
            elif fault.kind == "duplicate_row" and rows:
                rows.append(dict(rows[0]))
        entry = {"step": self.step.name, "at": self.step.at.isoformat(), "table": table,
                 "channel": channel, "query": {k: v for k, v in query.items() if k != "api_key"},
                 "rows": len(rows), "digest": digest(rows),
                 "faults": [f.kind for f in faults]}
        self.transcript.append(entry)
        if any(f.kind == "http_400" for f in faults):
            return httpx.Response(400, json={"error": "scheduled provider interruption"}, request=request)
        columns = list(COLUMNS[table])
        if any(f.kind == "missing_column" for f in faults):
            columns.remove("ticker")
        if channel == "export":
            csv_text = io.StringIO(newline="")
            writer = csv.DictWriter(csv_text, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                info = zipfile.ZipInfo(f"{table}.csv", date_time=(2000, 1, 1, 0, 0, 0))
                archive.writestr(info, csv_text.getvalue())
            link = f"https://exports.sharadar-replay.invalid/{digest([self.step.name, table, query, rows])}.zip"
            self._downloads[link] = buffer.getvalue()
            refreshed = self.step.at - dt.timedelta(minutes=1)
            snapshot = self.step.at
            if any(f.kind == "stale_export" for f in faults):
                snapshot = refreshed - dt.timedelta(minutes=1)
            payload = {"datatable_bulk_download": {
                "file": {"status": "fresh", "link": link,
                         "data_snapshot_time": snapshot.isoformat()},
                "datatable": {"last_refreshed_time": refreshed.isoformat()}}}
        else:
            cursor = int(query.get("qopts.cursor_id", "0"))
            page = rows[cursor:cursor + self.page_size]
            next_cursor = str(cursor + self.page_size) if cursor + self.page_size < len(rows) else None
            if any(f.kind == "repeat_cursor" for f in faults) and page:
                next_cursor = str(self.page_size)
            payload = {"datatable": {"columns": [{"name": c} for c in columns],
                                      "data": [[r.get(c) for c in columns] for r in page]},
                       "meta": {"next_cursor_id": next_cursor}}
        return httpx.Response(200, json=payload, request=request)
