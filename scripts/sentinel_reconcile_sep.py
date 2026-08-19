#!/usr/bin/env python3
"""Broker-free complete SEP value/key reconciliation for launch/certification.

Usage inside the Sentinel runtime/container:

    python scripts/sentinel_reconcile_sep.py --through 2026-08-18

Requires only ``SENTINEL_DATABASE_URL`` and ``SHARADAR_API_KEY``. It never
constructs a broker or repairs corpus rows. Every published year is read twice
from Sharadar, normalized through the production identity/price path, and proven
equal to the local published keys AND strategy-critical values.

For an upgraded installation that predates the #185 mutation cursor, this full
proof is also the ONLY supported way (besides a complete source-stable seed) to
earn the initial SEP ``lastupdated`` watermark. The watermark is written only
after every partition passes, and it is tied to the still-pinned current corpus
publication. A failed/partial sweep therefore cannot skip historical changes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from sentinel.feed import maintenance, publication, sep_reconciliation, sharadar, store


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "prove every published SEP year/value against stable Sharadar source "
            "and safely establish the mutation watermark"))
    parser.add_argument(
        "--through", required=True,
        help="current-source cutoff date, YYYY-MM-DD (normally today's feed date)")
    return parser


def _max_lastupdated(results):
    observed = [row.max_lastupdated for row in results
                if row.max_lastupdated is not None]
    return max(observed) if observed else None


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        sharadar.validate_date_range(args.through, args.through)
        sharadar.validate_config()
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
            if not results:
                raise sep_reconciliation.SepReconciliationStateInvalid(
                    "complete SEP reconciliation produced no published partitions")

            max_updated = _max_lastupdated(results)
            existing_cursor = maintenance.load_sep_cursor(conn)
            if max_updated is None and existing_cursor is None:
                raise maintenance.MutationCursorUnavailable(
                    "all stable SEP partitions lack a usable lastupdated value; "
                    "the corpus matches current source but no safe CDC bootstrap "
                    "boundary can be established")
            cutoff = dt.date.fromisoformat(args.through)
            if max_updated is not None and max_updated > cutoff:
                raise maintenance.SharadarMutationRefused(
                    f"stable SEP source reports lastupdated={max_updated} beyond "
                    f"the requested current-source cutoff {cutoff}")

            cursor = existing_cursor
            if (max_updated is not None and
                    (cursor is None or max_updated > cursor.processed_through)):
                current = publication.require_current(conn)
                cursor = maintenance.establish_sep_cursor_after_complete_reconciliation(
                    conn, through=max_updated,
                    publication_version=current.version)
    except Exception as exc:  # noqa: BLE001 -- CLI renders typed refusal safely
        print(
            f"REFUSED: complete SEP reconciliation failed: "
            f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    print(json.dumps({
        "schema": "sentinel.sharadar_sep_reconciliation/2",
        "status": "PASS",
        "through": args.through,
        "mutation_cursor": (
            None if cursor is None else {
                "processed_through": cursor.processed_through.isoformat(),
                "publication_version": cursor.publication_version,
            }),
        "partitions": [
            {
                "year": row.year,
                "window": [row.start, row.end],
                "rows": row.rows,
                "source_key_digest": row.digest,
                "source_value_digest": row.value_digest,
                "max_lastupdated": (
                    row.max_lastupdated.isoformat()
                    if row.max_lastupdated is not None else None),
                "publication_version": row.publication_version,
            }
            for row in results
        ],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
