"""Export or database-finalize a Wealth Core rehearsal.

JSON exports are portable audit artefacts, not authentication. The finalization
command accepts only a run id and reads the authoritative PostgreSQL row in the
same invocation that validates and extracts its book.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping

ENVELOPE_SCHEMA = "sentinel.rehearsal_envelope/1"
REQUIRED = ("schema", "run_id", "status", "mode", "spec", "parity_hashes",
            "summary")


def _load_envelope(run_id: str) -> dict | None:
    """Read row claims and payload from the authority, without flattening."""
    import psycopg

    dsn = os.environ.get("BT_DATABASE_URL")
    if not dsn:
        print("REFUSED: BT_DATABASE_URL is unset", file=sys.stderr)
        return None
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT mode, spec, status, summary, parity_hashes, started_at, "
            "completed_at FROM bt_wealth_core_runs WHERE run_id = %s",
            (run_id,))
        row = cur.fetchone()
    if not row:
        print(f"REFUSED: no run {run_id}", file=sys.stderr)
        return None
    mode, spec, status, summary, parity, started, completed = row
    return {
        "schema": ENVELOPE_SCHEMA,
        "run_id": run_id,
        "mode": mode,
        "status": status,
        "spec": spec or {},
        "parity_hashes": parity,
        "started_at": str(started),
        "completed_at": str(completed),
        "summary": summary or {},
    }


def _write_envelope(env: Mapping, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(env, indent=2, sort_keys=True, default=str))


def export(run_id: str, out: Path) -> int:
    """Write a non-authoritative audit export."""
    env = _load_envelope(run_id)
    if env is None:
        return 1
    _write_envelope(env, out)
    print(f"  exported run {run_id} -> {out}")
    return 0


def validate_envelope(env: Mapping, book_out: Path,
                      start: str, end: str) -> int:
    """Validate a row just read from PostgreSQL and extract its book."""
    problems: list[str] = []
    if env.get("schema") != ENVELOPE_SCHEMA:
        problems.append(
            f"schema is {env.get('schema')!r}, not {ENVELOPE_SCHEMA!r}")
    missing = [key for key in REQUIRED if key not in env]
    if missing:
        problems.append(f"missing required field(s): {missing}")
    if env.get("status") != "success":
        problems.append(f"status is {env.get('status')!r}, not 'success'")
    if env.get("mode") != "chain_rehearsal":
        problems.append(
            f"mode is {env.get('mode')!r}, not 'chain_rehearsal'")

    spec = env.get("spec") or {}
    if not isinstance(spec, Mapping):
        problems.append("spec is not an object")
        spec = {}
    if str(spec.get("start_date")) != start or str(spec.get("end_date")) != end:
        problems.append(
            f"the run covered {spec.get('start_date')}..{spec.get('end_date')} "
            f"and finalization requested {start}..{end}")
    if not env.get("parity_hashes"):
        problems.append("no parity_hashes")

    identity = spec.get("engine_identity") or {}
    if not isinstance(identity, Mapping):
        identity = {}
    for field in ("wealth_core_source_hash", "bt_engine_app_source_hash"):
        if not identity.get(field):
            problems.append(f"spec.engine_identity carries no {field}")
    if not identity.get("image_id"):
        problems.append(
            "spec.engine_identity carries no image_id; start the frozen image "
            "with scripts/bt-engine-up.sh before submitting the run")

    summary = env.get("summary")
    if not isinstance(summary, Mapping):
        problems.append("summary is not an object")
        summary = {}
    book = summary.get("book_artifact")
    if not isinstance(book, Mapping):
        problems.append("no book_artifact")
        book = {}
    window = book.get("window") if isinstance(book, Mapping) else None
    window = window if isinstance(window, Mapping) else {}
    if (window.get("start"), window.get("end")) != (start, end):
        problems.append(
            f"the book covers {window.get('start')}..{window.get('end')} "
            f"and finalization requested {start}..{end}")
    for field in ("held", "pending_terminal"):
        if field not in book or not isinstance(book.get(field), list):
            problems.append(f"book_artifact.{field} is missing or not a list")

    if problems:
        for problem in problems:
            print(f"  REFUSED: {problem}", file=sys.stderr)
        return 1

    book_out.parent.mkdir(parents=True, exist_ok=True)
    book_out.write_text(json.dumps(book, indent=2, sort_keys=True))
    print(f"  run {env['run_id']} mode={env['mode']} status={env['status']}")
    print(f"  spec {start}..{end} retention={spec.get('retention_mode')}")
    print(f"  engine wealth_core "
          f"{str(identity['wealth_core_source_hash'])[:16]} "
          f"image_id={identity['image_id']}")
    print(f"  held={len(book['held'])} "
          f"pending_terminal={len(book['pending_terminal'])}")
    print(f"  -> {book_out}")
    return 0


def finalize(run_id: str, book_out: Path, start: str, end: str,
             envelope_out: Path | None = None) -> int:
    """Read and validate one authoritative row; never consume an input file."""
    env = _load_envelope(run_id)
    if env is None:
        return 1
    if envelope_out is not None:
        _write_envelope(env, envelope_out)
    return validate_envelope(env, book_out, start, end)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("--run-id", required=True)
    export_parser.add_argument("--out", required=True)
    final_parser = sub.add_parser("finalize")
    final_parser.add_argument("--run-id", required=True)
    final_parser.add_argument("--book-out", required=True)
    final_parser.add_argument("--envelope-out")
    final_parser.add_argument("--start", required=True)
    final_parser.add_argument("--end", required=True)
    args = parser.parse_args(list(argv or sys.argv[1:]))
    if args.cmd == "export":
        return export(args.run_id, Path(args.out))
    return finalize(
        args.run_id, Path(args.book_out), args.start, args.end,
        Path(args.envelope_out) if args.envelope_out else None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
