"""Export and AUTHENTICATE a rehearsal. ONE validator, both entry paths.

The finalizer had two entrances. `--run-id` read the row and checked its status,
mode, window, summary and parity hashes. `--from-json` skipped all of it and
went straight to reading `book_artifact` — so a hand-written file with the right
window and fabricated equivalence and reconciliation fields bypassed every check
the other path had just gained.

A second entrance with weaker locks is not a second entrance. It is the
entrance.

So both now converge here:

```text
--run-id     -> export()        reads the row, writes the ENVELOPE
--from-json  -> (that envelope, or nothing)
                    |
                authenticate()  the same checks, always
                    |
                book.json
```

## What an envelope has to carry

An export from this script, not "some JSON with a book in it". The required
fields are exactly the ones the checks read, so a file missing any of them is
refused rather than partially validated.

## The ROW's claims and the RUN's payload are SEPARATE, permanently

```text
{
  "schema": ..., "run_id": ..., "status": ..., "mode": ...,   <- the DB row
  "spec": {...}, "parity_hashes": {...},                          says these
  "summary": { ... book_artifact, equivalence, ... }          <- the RUN
}                                                                 produced this
```

The first version flattened the summary over the row fields with `**summary`,
so a summary containing `status` or `mode` would OVERWRITE what the database
actually said. Today's `ChainRehearsal` carries neither, so nothing was wrong in
practice — and the authentication boundary was defeated structurally, which is
the kind of defect that waits for a field to be added rather than announcing
itself.

Nesting is preferred over merely re-ordering the merge because ordering is a
property someone has to keep getting right, while nesting makes the two
categories impossible to confuse: a payload field can never be READ as a row
claim, whatever it is called.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ENVELOPE_SCHEMA = "sentinel.rehearsal_envelope/1"

#: Every TOP-LEVEL field the authentication reads. Listed rather than
#: discovered so a file missing one is REFUSED, not silently checked against
#: `None`. `book_artifact` lives under `summary` — it is payload, not a claim
#: the row makes.
REQUIRED = ("schema", "run_id", "status", "mode", "spec", "parity_hashes",
            "summary")


def export(run_id: str, out: Path) -> int:
    import psycopg

    dsn = os.environ.get("BT_DATABASE_URL")
    if not dsn:
        print("REFUSED: BT_DATABASE_URL is unset", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as c, c.cursor() as cur:
        cur.execute("SELECT mode, spec, status, summary, parity_hashes,"
                    " started_at, completed_at FROM bt_wealth_core_runs"
                    " WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
    if not row:
        print(f"REFUSED: no run {run_id}", file=sys.stderr)
        return 1
    mode, spec, status, summary, parity, started, completed = row
    # NESTED, never flattened. `**summary` would let a payload field named
    # `status` or `mode` overwrite what the row said — the authentication
    # boundary defeated by a merge order.
    env = {"schema": ENVELOPE_SCHEMA, "run_id": run_id, "mode": mode,
           "status": status, "spec": spec or {}, "parity_hashes": parity,
           "started_at": str(started), "completed_at": str(completed),
           "summary": summary or {}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(env, indent=2, sort_keys=True, default=str))
    print(f"  exported run {run_id} -> {out}")
    return 0


def authenticate(envelope: Path, book_out: Path, start: str, end: str) -> int:
    """Every check, on every path. Returns 0 only when all of them hold."""
    try:
        env = json.loads(Path(envelope).read_text())
    except Exception as exc:                                 # noqa: BLE001
        print(f"REFUSED: {envelope} could not be read: {exc}", file=sys.stderr)
        return 1

    problems: list[str] = []

    if env.get("schema") != ENVELOPE_SCHEMA:
        problems.append(
            f"schema is {env.get('schema')!r}, not {ENVELOPE_SCHEMA!r}. An old "
            f"summary export is not an authenticated envelope — re-export it "
            f"with `sentinel_rehearsal.py export --run-id ...`, which reads the "
            f"row's own claims rather than trusting a file")
    missing = [k for k in REQUIRED if k not in env]
    if missing:
        problems.append(f"missing required field(s): {missing}")

    if env.get("status") != "success":
        problems.append(f"status is {env.get('status')!r}, not 'success' — a "
                        f"run that did not complete cannot certify an interval")
    if env.get("mode") != "chain_rehearsal":
        problems.append(
            f"mode is {env.get('mode')!r}, not 'chain_rehearsal'. Only the "
            f"chain rehearsal proves the session-by-session path reproduces the "
            f"bulk replay, which is what the hashes mean")

    spec = env.get("spec") or {}
    if str(spec.get("start_date")) != start or str(spec.get("end_date")) != end:
        problems.append(
            f"the run covered {spec.get('start_date')}..{spec.get('end_date')} "
            f"and you are finalizing {start}..{end}")
    if not env.get("parity_hashes"):
        problems.append("no parity_hashes — nothing to bind the manifest to")

    # THE ENGINE THAT RAN IT. Recorded by bt-engine AT RUN START, because a
    # container cannot discover its own image and inspecting a mutable
    # `:latest` tag afterwards answers a different question — what the tag
    # points at NOW, not what produced these numbers.
    ident = spec.get("engine_identity") or {}
    if not ident:
        problems.append(
            "spec.engine_identity is MISSING. This run was produced by an "
            "engine that did not record what it was, so the manifest cannot "
            "bind its numbers to any particular Wealth Core source. Re-run on "
            "the current bt-engine image")
    else:
        if not ident.get("wealth_core_source_hash"):
            problems.append(
                "spec.engine_identity carries no wealth_core_source_hash")
        if not ident.get("bt_engine_app_source_hash"):
            problems.append(
                "spec.engine_identity carries no bt_engine_app_source_hash — "
                "the Wealth Core tree alone does not identify the engine that "
                "LOADED the corpus and built the rehearsal inputs")
        if not ident.get("image_id"):
            problems.append(
                "spec.engine_identity has no image_id. Two bt-engine containers "
                "can carry the same Wealth Core tree and different interpreters, "
                "dependencies, loader code and client libraries — and bt-engine "
                "is what reads the corpus. Start it with "
                "`scripts/bt-engine-up.sh`, which builds, inspects the image and "
                "injects BT_ENGINE_IMAGE_ID before the container starts, then "
                "re-run the rehearsal")

    summary = env.get("summary")
    if summary is not None and not isinstance(summary, dict):
        problems.append("summary is not an object")
        summary = {}
    summary = summary or {}
    book = summary.get("book_artifact")
    if not book:
        problems.append(
            "no book_artifact. An older engine produced this run — one that had "
            "the RunResult in hand and discarded it. Re-run the rehearsal "
            "rather than writing the book by hand: a hand-written book is "
            "exactly what this removes")
    else:
        w = book.get("window") or {}
        if (w.get("start"), w.get("end")) != (start, end):
            problems.append(
                f"the book covers {w.get('start')}..{w.get('end')} and you are "
                f"finalizing {start}..{end}. A book for a different window "
                f"omits every name held outside it, and a refused row on one of "
                f"those would then be cleared by admission floors that do not "
                f"govern it")

    if problems:
        for p in problems:
            print(f"  REFUSED: {p}", file=sys.stderr)
        return 1

    book_out.parent.mkdir(parents=True, exist_ok=True)
    book_out.write_text(json.dumps(book, indent=2, sort_keys=True))
    print(f"  run {env['run_id']}  mode={env['mode']}  status={env['status']}")
    print(f"  spec {spec.get('start_date')}..{spec.get('end_date')} "
          f"retention={spec.get('retention_mode')}")
    print(f"  engine wealth_core {ident.get('wealth_core_source_hash', '?')[:16]}"
          f"  image_id={ident.get('image_id')}")
    print(f"  held={len(book['held'])} "
          f"pending_terminal={len(book['pending_terminal'])}")
    print(f"  -> {book_out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--run-id", required=True)
    e.add_argument("--out", required=True)
    a = sub.add_parser("authenticate")
    a.add_argument("--envelope", required=True)
    a.add_argument("--book-out", required=True)
    a.add_argument("--start", required=True)
    a.add_argument("--end", required=True)
    args = ap.parse_args(list(argv or sys.argv[1:]))
    if args.cmd == "export":
        return export(args.run_id, Path(args.out))
    return authenticate(Path(args.envelope), Path(args.book_out),
                        args.start, args.end)


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
