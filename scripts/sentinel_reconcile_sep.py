#!/usr/bin/env python3
"""Broker-free full SEP key-set reconciliation for launch/certification.

Usage inside the Sentinel runtime/container:

    python scripts/sentinel_reconcile_sep.py --through 2026-08-18

Requires only ``SENTINEL_DATABASE_URL`` and ``SHARADAR_API_KEY``.  It never
constructs a broker and never mutates the corpus.  It does persist the successful
rotation checkpoint after each verified year so ordinary nightly maintenance can
continue from the first year not yet proven if the command is interrupted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sentinel.feed import sep_reconciliation, sharadar, store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="prove every published SEP year against stable Sharadar source")
    parser.add_argument(
        "--through", required=True,
        help="current-source cutoff date, YYYY-MM-DD (normally today's feed date)")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        sharadar.validate_date_range(args.through, args.through)
        sharadar.validate_config()
        # Refuse before opening PostgreSQL/holding its corpus lock. A missing
        # production credential is a source configuration error, not an ingest
        # or reconciliation lifecycle event.
        sharadar._api_key()
    except (sharadar.MissingApiKey, TypeError, ValueError) as exc:
        print(f"REFUSED: invalid Sharadar reconciliation configuration: {exc}",
              file=sys.stderr)
        return 2

    dsn = os.getenv("SENTINEL_DATABASE_URL", "").strip()
    if not dsn:
        print("REFUSED: SENTINEL_DATABASE_URL is unset", file=sys.stderr)
        return 2

    conn = store.connect(dsn)
    try:
        store.require_feed_schema(conn)
        with store.corpus_write_lock(conn):
            results = sep_reconciliation.reconcile_all(
                conn, through=args.through)
    except Exception as exc:  # noqa: BLE001 -- CLI renders typed refusal safely
        print(
            f"REFUSED: complete SEP reconciliation failed: "
            f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(json.dumps({
        "schema": "sentinel.sharadar_sep_reconciliation/1",
        "status": "PASS",
        "through": args.through,
        "partitions": [
            {
                "year": row.year,
                "window": [row.start, row.end],
                "rows": row.rows,
                "source_digest": row.digest,
                "publication_version": row.publication_version,
            }
            for row in results
        ],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
