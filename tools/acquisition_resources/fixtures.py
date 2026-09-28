"""Disk-streamed Tables fixture, kept outside the measured acquisition worker."""
from __future__ import annotations

import argparse
import csv
from datetime import date, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import itertools
import json
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlparse
import zipfile

from pydantic import BaseModel, Field

from sentinel.feed.rolling_contract import FormationWindow, PriceWindow
from sentinel.feed.operational_source import _months
from tools.acquisition_resources.profiles import SPECS

END = "2026-09-25"
REFRESH = "2026-09-26T00:00:00+00:00"


class Profile(BaseModel):
    name: str
    securities: int = Field(gt=0)
    tickers: int = Field(gt=0)
    actions: int = Field(gt=0)
    formation: bool = True

    def window(self):
        return (FormationWindow if self.formation else PriceWindow).through(END)


PROFILES = {name: Profile(name=name, **spec) for name, spec in SPECS.items()}
COLUMNS = {
    "SEP": ["ticker", "date", "open", "high", "low", "close", "closeunadj", "volume", "lastupdated"],
    "SFP": ["ticker", "date", "open", "close", "closeadj", "closeunadj", "volume"],
    "ACTIONS": ["date", "action", "ticker", "name", "value", "contraticker", "contraname"],
    "TICKERS": ["table", "permaticker", "ticker", "name", "category", "relatedtickers",
                "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange"],
}


def rows(profile, table, lo=None, hi=None):
    window = profile.window()
    if table == "TICKERS":
        for i in range(profile.tickers):
            active = i < profile.securities
            yield ["SEP", str(i + 1), f"S{i:05}", f"Synthetic security {i:05}",
                   "Domestic Common Stock", None,
                   str(window.start) if active else "1990-01-01",
                   END if active else "2000-01-01", "Technology", "N" if active else "Y", "NYSE"]
    elif table == "ACTIONS":
        for i in range(profile.actions):
            # Unique semantic records with realistic names and decimal spelling.
            day = date(1960, 1, 1) + timedelta(days=90 * (i // profile.securities))
            yield [str(day), "dividend", f"S{i % profile.securities:05}",
                   f"Synthetic Corporation {i % profile.securities:05} ordinary cash distribution",
                   "0.125", None, None]
    else:
        for day in window.sessions:
            if lo and not lo <= str(day) <= hi:
                continue
            count = 2 if table == "SFP" else profile.securities
            for i in range(count):
                if table == "SFP":
                    yield [("SPY", "BIL")[i], str(day), "100", "101", "102", "101", "1000000"]
                else:
                    # Vary price text across rows without allocating a full table.
                    price = f"{50 + i % 900}.{day.day:02}"
                    yield [f"S{i:05}", str(day), price, price, price, price, price,
                           str(100000 + i), END]


def export_key(table, lo=None, hi=None):
    return table + (f"-{lo}-{hi}" if table == "SEP" else "")


def build(profile, root):
    root.mkdir(parents=True, exist_ok=True)
    window = profile.window()
    requests = [("ACTIONS", None, None), ("TICKERS", None, None)]
    requests += [("SEP", lo, hi) for lo, hi in _months(str(window.start), END)]
    manifest = {}
    for table, lo, hi in requests:
        key = export_key(table, lo, hi)
        path = root / (key + ".zip")
        count = 0
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            info = zipfile.ZipInfo(table + ".csv", (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(info, "w") as raw:
                with io.TextIOWrapper(raw, encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(COLUMNS[table])
                    for row in rows(profile, table, lo, hi):
                        writer.writerow(row)
                        count += 1
            uncompressed = archive.getinfo(table + ".csv").file_size
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest[key] = dict(rows=count, compressed_bytes=path.stat().st_size,
                             csv_bytes=uncompressed, sha256=sha)
    return manifest


def handler(profile, root, manifest):
    class Handler(BaseHTTPRequestHandler):
        downloads = 0
        transferred = 0
        def log_message(self, *_args):
            pass  # No authenticated URL logging, including synthetic credentials.
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            table = Path(parsed.path).stem.upper()
            if parsed.path == "/metrics":
                payload = dict(downloads=self.downloads, transferred_bytes=self.transferred,
                               manifest=manifest, profile=profile.model_dump())
            elif parsed.path.startswith("/exports/"):
                key = Path(parsed.path).stem
                if key not in manifest:
                    self.send_error(404)
                    return
                path = root / (key + ".zip")
                self.send_response(200)
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile, length=65536)
                type(self).downloads += 1
                type(self).transferred += path.stat().st_size
                return
            elif table in COLUMNS and query.get("qopts.export") == ["true"]:
                key = export_key(table, query.get("date.gte", [None])[0], query.get("date.lte", [None])[0])
                if key not in manifest:
                    self.send_error(404)
                    return
                payload = {"datatable_bulk_download": {
                    "file": {"status": "fresh", "data_snapshot_time": REFRESH,
                             "link": f"http://{self.headers['Host']}/exports/{key}.zip"},
                    "datatable": {"last_refreshed_time": REFRESH}}}
            elif table in {"TICKERS", "SFP"}:
                offset = int(query.get("qopts.cursor_id", ["0"])[0])
                page = list(itertools.islice(rows(profile, table), offset, offset + 5001))
                cursor = str(offset + 5000) if len(page) > 5000 else None
                payload = {"datatable": {"columns": [{"name": c, "type": "text"} for c in COLUMNS[table]],
                                         "data": page[:5000]}, "meta": {"next_cursor_id": cursor}}
            else:
                self.send_error(404)
                return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, required=True)
    parser.add_argument("--root", type=Path, default=Path("/fixtures"))
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    manifest = build(profile, args.root)
    print(json.dumps({"event": "fixture_ready", "profile": profile.name}), flush=True)
    HTTPServer(("0.0.0.0", 8080), handler(profile, args.root, manifest)).serve_forever()


if __name__ == "__main__":
    main()
