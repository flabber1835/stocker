"""Opt-in, read-only checkpoint price rehearsal; see docs/rolling-snapshot-readers.md."""
from __future__ import annotations

import argparse
import json
import os

from sentinel.feed.store import connect
from sentinel.identity import rehearsal_identity
from sentinel.rolling_rehearsal import rehearse
from sentinel.strategy import production_strategy


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--observation-id", required=True)
    args = parser.parse_args(argv)
    conn = None
    try:
        conn = connect(os.environ["SENTINEL_DATABASE_URL"], connect_timeout=10,
                       statement_timeout_ms=120000)
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        config, _identity = production_strategy()
        result = rehearse(conn, job_id=args.job_id, observation_id=args.observation_id,
                          controller_config=config)
        result["comparison_environment"] = rehearsal_identity()
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as exc:
        # Driver/provider exception strings can contain credentials. Emit only
        # our bounded refusal code or the type, never the connection string.
        from sentinel.core.rolling_reader import RollingReaderRefused
        reason = str(exc) if isinstance(exc, RollingReaderRefused) else type(exc).__name__
        print(json.dumps({"status": "REFUSED", "operational_go": False, "reason": reason}))
        return 1
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
