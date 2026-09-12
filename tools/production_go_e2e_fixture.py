#!/usr/bin/env python3
"""Deterministic external-service and corpus fixture for the production GO E2E.

The fixture may substitute external Sharadar/Alpaca services and may establish
the pre-existing production corpus. It does not replace any Sentinel GO program:
the E2E driver invokes the ordinary operator entrypoint and the production
lifecycle runs unchanged against these deterministic boundaries.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
import zipfile

SECURITIES = 4000
SESSIONS = 260
TICKER_COLUMNS = (
    "table", "permaticker", "ticker", "category", "relatedtickers",
    "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange",
)
SEP_COLUMNS = (
    "ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated",
)
SFP_COLUMNS = (
    "ticker", "date", "open", "close", "closeadj", "closeunadj",
)
ACTION_COLUMNS = (
    "date", "action", "ticker", "name", "value", "contraticker", "contraname",
)


def market_sessions(target: str) -> list[str]:
    from sentinel.feed import calendar
    values = calendar.previous_sessions(target, SESSIONS)
    if len(values) != SESSIONS or values[-1] != target:
        raise RuntimeError("fixture target does not have the required XNYS history")
    return [str(value) for value in values]


def ticker_rows(target: str) -> list[dict]:
    sessions = market_sessions(target)
    first = sessions[0]
    return [
        {
            "table": "SEP",
            "permaticker": str(100000 + i),
            "ticker": f"E{i:04d}",
            "category": "Domestic Common Stock",
            "relatedtickers": "",
            "firstpricedate": first,
            "lastpricedate": target,
            "sector": "Technology",
            "isdelisted": "N",
            "exchange": "NYSE",
        }
        for i in range(SECURITIES)
    ]


def _close(i: int, day: int) -> float:
    base = 24.0 + (i % 240) * 0.21
    drift = 1.0 + day * (0.00028 + (i % 29) * 0.000007)
    wave = 1.0 + 0.012 * math.sin((day + (i % 17)) / 9.0)
    return round(base * drift * wave, 6)


def sep_rows(target: str):
    sessions = market_sessions(target)
    for day, session in enumerate(sessions):
        for i in range(SECURITIES):
            close = _close(i, day)
            open_ = round(close * (1.0 + (((day + i) % 5) - 2) * 0.0005), 6)
            yield {
                "ticker": f"E{i:04d}",
                "date": session,
                "open": open_,
                "close": close,
                "closeunadj": close,
                "volume": 2_000_000 + (i % 1000) * 1000,
                "lastupdated": session,
            }


def sfp_rows(target: str):
    sessions = market_sessions(target)
    for day, session in enumerate(sessions):
        for ticker, base in (("SPY", 420.0), ("BIL", 91.0)):
            close = round(base * (1.0 + day * (0.00035 if ticker == "SPY" else 0.00005)), 6)
            yield {
                "ticker": ticker,
                "date": session,
                "open": close,
                "close": close,
                "closeadj": close,
                "closeunadj": close,
            }


def action_rows(_target: str):
    return iter(())


def _bounded(rows, params: dict[str, str]):
    date_from = params.get("date.gte")
    date_to = params.get("date.lte")
    update_from = params.get("lastupdated.gte")
    update_to = params.get("lastupdated.lte")
    tickers = {
        token.strip().upper()
        for token in params.get("ticker", "").replace(";", ",").split(",")
        if token.strip()
    }
    for row in rows:
        day = str(row.get("date") or "")
        updated = str(row.get("lastupdated") or "")
        ticker = str(row.get("ticker") or "").upper()
        if date_from and day and day < date_from:
            continue
        if date_to and day and day > date_to:
            continue
        if update_from and updated and updated < update_from:
            continue
        if update_to and updated and updated > update_to:
            continue
        if tickers and ticker not in tickers:
            continue
        yield row


def rows_for(table: str, target: str, params: dict[str, str]):
    if table == "TICKERS":
        return iter(ticker_rows(target))
    if table == "SEP":
        return _bounded(sep_rows(target), params)
    if table == "SFP":
        return _bounded(sfp_rows(target), params)
    if table == "ACTIONS":
        return _bounded(action_rows(target), params)
    raise KeyError(table)


def columns_for(table: str) -> tuple[str, ...]:
    return {
        "TICKERS": TICKER_COLUMNS,
        "SEP": SEP_COLUMNS,
        "SFP": SFP_COLUMNS,
        "ACTIONS": ACTION_COLUMNS,
    }[table]


def zip_export(table: str, target: str, params: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        text = io.StringIO()
        writer = csv.DictWriter(text, fieldnames=columns_for(table), lineterminator="\n")
        writer.writeheader()
        for row in rows_for(table, target, params):
            writer.writerow({name: row.get(name) for name in columns_for(table)})
        archive.writestr(f"SHARADAR_{table}.csv", text.getvalue())
    return out.getvalue()


def seed_database(*, target: str, dsn: str, commit: str, image_id: str) -> None:
    """Establish a real published corpus through canonical feed code."""
    from sentinel import schema
    from sentinel.feed import ingest, store

    env = {
        "SENTINEL_DATABASE_URL": dsn,
        "SENTINEL_PUBLICATION_RECEIPT_KEY": os.environ["SENTINEL_PUBLICATION_RECEIPT_KEY"],
        "SENTINEL_GIT_COMMIT": commit,
        "SENTINEL_RUNTIME_IMAGE_DIGEST": image_id,
        "SENTINEL_FEED_AUTHORIZED": "CLEAN_HEAD_IMAGE_V1",
        "SENTINEL_FEED_GIT_COMMIT": commit,
        "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": image_id,
        "SENTINEL_IMAGE_SOURCE_REVISION": commit,
    }
    os.environ.update(env)
    conn = store.connect(dsn)
    try:
        store.migrate_schema(conn)
        schema.ensure_schema(conn)
        sessions = market_sessions(target)

        def fetch(table, params=None, **_kwargs):
            return rows_for(str(table), target, dict(params or {}))

        progress = ingest.seed(
            conn, date_from=sessions[0], date_to=target, fetch=fetch)
        if progress.status != "success":
            raise RuntimeError(f"fixture seed failed: {progress}")
        frontier = store.latest_visible_session(conn)
        if frontier != target:
            raise RuntimeError(
                f"fixture publication frontier mismatch: {frontier!r} != {target!r}")
    finally:
        conn.close()


class SharadarHandler(BaseHTTPRequestHandler):
    server_version = "SentinelSharadarE2E/1"
    protocol_version = "HTTP/1.1"

    @property
    def target(self) -> str:
        return self.server.target  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):
        print("[sharadar-e2e] " + (fmt % args), flush=True)

    def _json(self, payload: dict, status: int = 200):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _blob(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        query = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        if parsed.path.startswith("/exports/") and parsed.path.endswith(".zip"):
            table = parsed.path.rsplit("/", 1)[-1][:-4].upper()
            try:
                self._blob(zip_export(table, self.target, query))
            except KeyError:
                self._json({"error": "unknown table"}, 404)
            return

        prefix = "/api/v3/datatables/SHARADAR/"
        if not parsed.path.startswith(prefix) or not parsed.path.endswith(".json"):
            self._json({"error": "not found"}, 404)
            return
        table = parsed.path[len(prefix):-5].upper()
        try:
            columns = columns_for(table)
        except KeyError:
            self._json({"error": "unknown table"}, 404)
            return

        if query.get("qopts.export", "").lower() == "true":
            visible = {
                k: value for k, value in query.items()
                if k not in {"api_key", "qopts.export", "qopts.cursor_id"}
            }
            host = self.headers.get("Host", "127.0.0.1")
            link = f"http://{host}/exports/{table}.zip"
            if visible:
                link += "?" + urlencode(visible)
            self._json({
                "datatable_bulk_download": {
                    "file": {
                        "status": "fresh",
                        "link": link,
                        "data_snapshot_time": f"{self.target}T23:05:00Z",
                    },
                    "datatable": {
                        "last_refreshed_time": f"{self.target}T23:00:00Z",
                    },
                }
            })
            return

        visible = {
            k: value for k, value in query.items()
            if k not in {"api_key", "qopts.cursor_id"}
        }
        data = [
            [row.get(name) for name in columns]
            for row in rows_for(table, self.target, visible)
        ]
        self._json({
            "datatable": {
                "columns": [{"name": name} for name in columns],
                "data": data,
            },
            "meta": {"next_cursor_id": None},
        })


class AlpacaHandler(BaseHTTPRequestHandler):
    server_version = "SentinelAlpacaE2E/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[alpaca-e2e] " + (fmt % args), flush=True)

    def do_GET(self):  # noqa: N802
        if self.path != "/v2/account":
            self.send_error(404)
            return
        if (self.headers.get("APCA-API-KEY-ID") != "e2e-key"
                or self.headers.get("APCA-API-SECRET-KEY") != "e2e-secret"):
            self.send_error(401)
            return
        payload = {
            "id": "11111111-2222-3333-4444-555555555555",
            "account_number": "E2E-PAPER-ACCOUNT",
            "status": "ACTIVE",
            "multiplier": "1",
            "cash": "100000.00",
            "buying_power": "100000.00",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_sharadar(port: int, target: str) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), SharadarHandler)
    server.target = target  # type: ignore[attr-defined]
    print(f"SHARADAR_E2E_READY={port}", flush=True)
    server.serve_forever()


def serve_alpaca(port: int, cert: str, key: str) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), AlpacaHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert, keyfile=key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"ALPACA_E2E_READY={port}", flush=True)
    server.serve_forever()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed")
    seed.add_argument("--target", required=True)
    seed.add_argument("--dsn", required=True)
    seed.add_argument("--commit", required=True)
    seed.add_argument("--image-id", required=True)

    sharadar = sub.add_parser("serve-sharadar")
    sharadar.add_argument("--port", type=int, required=True)
    sharadar.add_argument("--target", required=True)

    alpaca = sub.add_parser("serve-alpaca")
    alpaca.add_argument("--port", type=int, required=True)
    alpaca.add_argument("--cert", required=True)
    alpaca.add_argument("--key", required=True)

    args = parser.parse_args(argv)
    if args.command == "seed":
        seed_database(
            target=args.target, dsn=args.dsn, commit=args.commit,
            image_id=args.image_id)
        return 0
    if args.command == "serve-sharadar":
        serve_sharadar(args.port, args.target)
        return 0
    if args.command == "serve-alpaca":
        serve_alpaca(args.port, args.cert, args.key)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
