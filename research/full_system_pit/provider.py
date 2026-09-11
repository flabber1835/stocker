"""Historical Tables/Exporter service with an advancing publication frontier."""
from __future__ import annotations

import bisect
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import zipfile

import httpx

from research.sharadar_replay.provider import COLUMNS
from .evidence import digest


class FileStream(httpx.SyncByteStream):
    def __init__(self, path):
        self.path = path

    def __iter__(self):
        with self.path.open("rb") as source:
            yield from iter(lambda: source.read(1024*1024), b"")


class Provider:
    def __init__(self, truth: Path, exports: Path, *, page_size=10000, observe=None):
        if page_size < 1:
            raise ValueError("invalid page size")
        self.db = sqlite3.connect(f"file:{truth.resolve()}?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.exports = exports
        exports.mkdir(parents=True, exist_ok=False)
        self.page_size, self.observe = page_size, observe
        self.step = None
        self.downloads, self.cursors, self.export_receipts = {}, {}, {}
        self.splits = {}
        for r in self.db.execute("SELECT sid,day,split FROM splits ORDER BY sid,day"):
            self.splits.setdefault(r["sid"], []).append((r["day"], r["split"]))
        self.identity = json.loads(self.db.execute("SELECT body FROM identity").fetchone()[0])
        self.cash_levels = {}
        level = 100.
        for r in self.db.execute("SELECT * FROM reference ORDER BY day"):
            op = level * r["gap"]
            level = op * r["intraday"]
            self.cash_levels[r["day"]] = (op, level)

    def advance(self, at):
        if at.tzinfo is None or (self.step and at <= self.step.at):
            raise ValueError("provider time must advance")
        self.step = SimpleNamespace(at=at, name=at.isoformat())
        self.cursors.clear()
        for path in self.downloads.values():
            path.unlink()
        self.downloads.clear()
        self.export_receipts.clear()
        self.factors, self.updated = {}, {}
        for sid, events in self.splits.items():
            factor, updated = 1., None
            for day, split in events:
                if day > str(at.date()):
                    factor *= split
                else:
                    updated = day
            self.factors[sid], self.updated[sid] = factor, updated

    def sep_observations(self, start, end, query):
        lower = query.get("lastupdated.gte", "0001-01-01")
        upper = query.get("lastupdated.lte", "9999-12-31")
        sql = "SELECT * FROM obs WHERE day BETWEEN ? AND ?"
        params = [max(start, lower), min(end, upper)]
        revised = sorted(sid for sid, day in self.updated.items()
                         if day is not None and lower <= day <= upper)
        if start < lower and revised:
            sql += (" UNION ALL SELECT * FROM obs WHERE day BETWEEN ? AND ?"
                    " AND day<? AND sid IN (" + ",".join("?" for _ in revised) + ")")
            params.extend([start, end, lower, *revised])
        return self.db.execute(sql + " ORDER BY day,sid", params)

    def row_stream(self, table, query):
        if self.step is None or table not in COLUMNS:
            raise ValueError("provider view is unavailable")
        permitted = {"api_key", "ticker", "table", "date.gte", "date.lte", "lastupdated.gte",
                     "lastupdated.lte", "qopts.cursor_id", "qopts.export"}
        if set(query) - permitted:
            raise ValueError("unmodeled provider query")
        end = min(query.get("date.lte", "9999-12-31"), str(self.step.at.date()))
        start = query.get("date.gte", "0001-01-01")
        symbols = set(query["ticker"].split(",")) if "ticker" in query else None
        if table == "SEP":
            for r in self.sep_observations(start, end, query):
                factor = self.factors.get(r["sid"], 1.)
                signal = r["signal"] * factor if r["signal"] else None
                row = dict(ticker=r["ticker"], date=r["day"], close=signal, closeunadj=r["raw"],
                    open=r["op"]*signal/r["raw"] if r["op"] and signal and r["raw"] else None,
                    volume=r["volume"]/factor if r["volume"] is not None else None,
                    lastupdated=max(r["day"], self.updated.get(r["sid"]) or r["day"]))
                if any(k in query and (row["lastupdated"] < query[k] if k.endswith("gte") else row["lastupdated"] > query[k])
                       for k in ("lastupdated.gte", "lastupdated.lte")):
                    continue
                if symbols is None or row["ticker"] in symbols:
                    yield row
        elif table == "TICKERS":
            # One immutable pairing per observed listing; old symbols remain
            # present with their last observed date. No future IPO or delisting.
            sql = """SELECT m.body, (SELECT MAX(o.day) FROM obs o WHERE o.sid=m.sid
                AND o.ticker=m.ticker AND o.day<=?) last_day FROM meta m WHERE m.day<=?
                AND NOT EXISTS(SELECT 1 FROM meta n WHERE n.sid=m.sid AND n.ticker=m.ticker
                    AND n.day<=? AND n.day>m.day) ORDER BY m.sid,m.ticker"""
            for r in self.db.execute(sql, (end, end, end)):
                row = json.loads(r["body"])
                row.update(lastpricedate=r["last_day"], isdelisted="N")
                if (symbols is None or row["ticker"] in symbols) and query.get("table", "SEP") == "SEP":
                    yield row
        elif table == "SFP":
            for r in self.db.execute("SELECT * FROM reference WHERE day BETWEEN ? AND ? ORDER BY day", (start, end)):
                op, close = self.cash_levels[r["day"]]
                for ticker, opened, closed in (("SPY", r["spy"], r["spy"]), ("BIL", op, close)):
                    if symbols is None or ticker in symbols:
                        yield dict(ticker=ticker, date=r["day"], open=opened,
                            close=closed, closeadj=closed, closeunadj=closed)
        else:
            for r in self.db.execute("SELECT * FROM actions WHERE day BETWEEN ? AND ? ORDER BY day,sid,body", (start, end)):
                item = json.loads(r["body"])
                if str(item.get("known_by") or r["day"])[:10] > str(self.step.at.date()):
                    continue
                value = item.get("vendor_value")
                if value not in (None, "", "None"):
                    value = float(value)
                    if item["action"] in {"dividend", "spinoffdividend", "specialdividend"}:
                        value *= self.factors.get(r["sid"], 1.)
                else:
                    value = None
                row = dict(date=r["day"], action=item["action"], ticker=item["ticker"],
                    value=value, name=None, contraticker=None, contraname=None)
                if symbols is None or row["ticker"] in symbols:
                    yield row

    def __call__(self, request):
        if request.method != "GET":
            raise ValueError("provider permits only GET")
        if request.url.host == "exports.full-system-pit.invalid":
            path = self.downloads.get(str(request.url))
            if path is None:
                raise ValueError("expired export generation")
            return httpx.Response(200, stream=FileStream(path), request=request)
        prefix = "/api/v3/datatables/SHARADAR/"
        if request.url.host != "data.nasdaq.com" or not request.url.path.startswith(prefix):
            raise ValueError("request left simulated Sharadar")
        table = request.url.path.removeprefix(prefix).removesuffix(".json")
        query = dict(request.url.params)
        columns = COLUMNS[table]
        clean = {k:v for k,v in query.items() if k not in {"api_key", "qopts.cursor_id"}}
        key = digest([self.step.name, table, clean])
        if query.get("qopts.export") == "true":
            path = self.exports / (key + ".zip")
            link = f"https://exports.full-system-pit.invalid/{key}.zip"
            payload = {"datatable_bulk_download": {"file": {"status": "fresh", "link": link,
                "data_snapshot_time": self.step.at.isoformat()}, "datatable": {
                "last_refreshed_time": (self.step.at - timedelta(minutes=1)).isoformat()}}}
            if key in self.export_receipts:
                if self.observe:
                    self.observe(dict(self.export_receipts[key], reused=True))
                return httpx.Response(200, json=payload, request=request)
            count, h = 0, hashlib.sha256()
            with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                with archive.open(table + ".csv", "w", force_zip64=True) as member:
                    wrapper = io.TextIOWrapper(member, newline="")
                    writer = csv.DictWriter(wrapper, fieldnames=columns, extrasaction="ignore")
                    writer.writeheader()
                    for row in self.row_stream(table, query):
                        writer.writerow(row)
                        h.update(json.dumps(row, sort_keys=True).encode())
                        count += 1
                    wrapper.flush()
            self.downloads[link] = path
            receipt = dict(query=clean, table=table, count=count, rows_sha256=h.hexdigest(), export=key)
            self.export_receipts[key] = dict(receipt)
        else:
            token = query.get("qopts.cursor_id")
            if token:
                view_key, iterator, first = self.cursors.pop(token)
                if view_key != key:
                    raise ValueError("cursor query or generation changed")
                page = [first]
            else:
                iterator, page = iter(self.row_stream(table, query)), []
            while len(page) < self.page_size:
                row = next(iterator, None)
                if row is None:
                    break
                page.append(row)
            extra = next(iterator, None)
            next_token = None
            if extra is not None:
                next_token = digest([key, token, page[-1]])
                self.cursors[next_token] = (key, iterator, extra)
            payload = {"datatable": {"columns": [{"name": c} for c in columns],
                "data": [[r.get(c) for c in columns] for r in page]}, "meta": {"next_cursor_id": next_token}}
            receipt = dict(query=clean, table=table, response=payload, count=len(page))
        if self.observe:
            self.observe(receipt)
        return httpx.Response(200, json=payload, request=request)
