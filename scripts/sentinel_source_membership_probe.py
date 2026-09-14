#!/usr/bin/env python3
"""Bounded read-only Sharadar membership evidence; host Python 3.8+, no DB access."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener

FIELDS = {
    "TICKERS": ("table", "permaticker", "ticker", "category", "isdelisted",
                "firstpricedate", "lastpricedate", "relatedtickers", "lastupdated"),
    "SEP": ("ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"),
    "ACTIONS": ("date", "action", "ticker", "name", "value", "contraticker", "contraname"),
}
MAX_BYTES = 4 * 1024 * 1024
MAX_PAGES = 4


class ProbeRefused(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeRefused("source redirect refused")


def fetch_rows(table, params, api_key, *, opener=None):
    """Fixed-origin GET, bounded pages/bytes, no URL or exception text in output."""
    if table not in FIELDS:
        raise ProbeRefused("unsupported table")
    opener = opener or build_opener(NoRedirect())
    rows, page_digests, cursor = [], [], None
    for _ in range(MAX_PAGES):
        query = dict(params, api_key=api_key)
        if cursor:
            query["qopts.cursor_id"] = cursor
        url = "https://data.nasdaq.com/api/v3/datatables/SHARADAR/%s.json?%s" % (
            table, urlencode(query))
        try:
            with opener.open(url, timeout=30) as response:
                raw = response.read(MAX_BYTES + 1)
        except HTTPError as exc:
            raise ProbeRefused("source HTTP status %s" % exc.code) from None
        except Exception:
            raise ProbeRefused("source request failed (details withheld)") from None
        if len(raw) > MAX_BYTES:
            raise ProbeRefused("source response exceeds diagnostic byte bound")
        try:
            payload = json.loads(raw)
            data = payload["datatable"]
            columns = [item["name"] for item in data["columns"]]
            if len(columns) != len(set(columns)):
                raise ValueError("duplicate columns")
            for values in data["data"]:
                if len(values) != len(columns):
                    raise ValueError("column count")
                row = dict(zip(columns, values))
                rows.append({key: row.get(key) for key in FIELDS[table]})
            cursor = payload.get("meta", {}).get("next_cursor_id")
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("cursor type")
        except (KeyError, TypeError, ValueError):
            raise ProbeRefused("source response shape invalid") from None
        page_digests.append(hashlib.sha256(raw).hexdigest())
        if not cursor:
            return {"rows": rows, "page_sha256": page_digests}
    raise ProbeRefused("source pagination exceeds diagnostic bound")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    parser.add_argument("--tickers", required=True)
    args = parser.parse_args(argv)
    args.symbols = args.tickers.split(",")
    if not 1 <= len(args.symbols) <= 16 or any(
            not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", item) for item in args.symbols):
        parser.error("provide 1-16 comma-separated uppercase symbols")
    if not 0 <= (args.end - args.start).days <= 31:
        parser.error("date interval must be ordered and at most 31 days")
    return args


def main(argv=None):
    args = arguments(argv)
    # Also supports a downloaded copy in /tmp, with the operator in the repo.
    scripts = Path.cwd() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        from sentinel_env import load
        env = load(Path.cwd() / ".env", required=True)
        key = env.get("SHARADAR_API_KEY", "").strip()
        if not key:
            raise ProbeRefused("SHARADAR_API_KEY is absent from the repository .env")
        result = {
            "schema": "sentinel.source-membership-diagnostic/1",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "authority": "DIAGNOSTIC_ONLY_NOT_A_STABLE_PUBLICATION",
            "requested_interval": [args.start.isoformat(), args.end.isoformat()],
            "requested_tickers": args.symbols,
            "tickers": fetch_rows("TICKERS", {"table": "SEP", "ticker": args.tickers}, key),
            "sep": fetch_rows("SEP", {"ticker": args.tickers,
                                      "date.gte": args.start.isoformat(),
                                      "date.lte": args.end.isoformat()}, key),
        }
        for field in ("ticker", "contraticker"):
            result["actions_by_" + field] = fetch_rows(
                "ACTIONS", {field: args.tickers, "date.gte": args.start.isoformat(),
                            "date.lte": args.end.isoformat()}, key)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ProbeRefused as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
    except Exception:
        print("REFUSED: cannot load local environment or diagnostic runtime", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
