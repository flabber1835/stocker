"""Shared command-line parsing for explicit, signed physical coverage witnesses."""
import argparse
import hashlib
import json
import signal
from pathlib import Path

from sentinel import chain_progress_recovery as shared
from sentinel.feed import store


def run(description, snapshot, apply, argv=None):
    from sentinel.restore_validation import _database_url

    parser = argparse.ArgumentParser(description=description, allow_abbrev=False)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--snapshot', action='store_true')
    mode.add_argument('--apply', type=Path)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--marker')
    parser.add_argument('--metadata-sha256')
    parser.add_argument('--confirm-witness-sha256')
    parser.add_argument('--expect-account')
    parser.add_argument('--deployment-id')
    args = parser.parse_args(argv)
    try:
        signal.alarm(600)
        with store.connect(_database_url(), connect_timeout=3, statement_timeout_ms=15000) as conn:
            if args.snapshot:
                result = snapshot(conn, backup=args.backup, marker=args.marker,
                                  metadata_sha256=args.metadata_sha256)
                conn.rollback()
            else:
                raw = args.apply.read_bytes()
                shared._require(hashlib.sha256(raw).hexdigest() == args.confirm_witness_sha256,
                                'exact witness confirmation required')
                result = apply(conn, shared._document(raw), expected_backup=args.backup,
                               expected_account=args.expect_account,
                               expected_deployment=args.deployment_id)
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 0
    except Exception as exc:
        print('REFUSED: ' + type(exc).__name__ + ': ' + str(exc))
        return 2
    finally:
        signal.alarm(0)
