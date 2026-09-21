"""Sixty-minute economic comparison with reconstructed classification and SPY."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from decimal import Decimal
import gzip
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import time
import traceback
import zipfile

# Resolve the explicitly supplied read-only production checkout before imports.
import sys
_WORKER_STARTED = time.monotonic()
_boot = argparse.ArgumentParser(add_help=False)
_boot.add_argument("--harness", type=Path, required=True)
_boot_args, _ = _boot.parse_known_args()
_HARNESS = _boot_args.harness.resolve()
sys.path[:0] = [str(_HARNESS), str(_HARNESS / "shared")]

from stock_strategy_shared.wealth_core.feed import SecurityMeta
from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.session import FeedAnchor, PublishedSession, SessionState
from sentinel.feed.calendar import previous_sessions
from sentinel.strategy import production_strategy
from research.bounded_20y.inputs import BASE_ARCHIVE_SHA256, BASE_DATASET_SHA256, SFP_SOURCE, sha256, validate_manifest
from research.bounded_20y.run import (START, END, PRODUCTION_REVISION, EconomicPath, distributions,
                  dump, metadata, number, terminals, vendor, verify_production)
from research.bounded_20y.supplement import supplemented_terminals
from .inputs import Classification, OVERLAY_SHA256, progress

REFERENCE_SHA256 = "f26288218dd76d0092efe8414d9ac8c39075b256ff9a023a711227f9416ff21a"
ORIGIN = "2006-01-03"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


class JanuaryInputs:
    def __init__(self, archive, sfp):
        if sha256(archive) != BASE_ARCHIVE_SHA256:
            raise ValueError("archive hash differs")
        self.archive = zipfile.ZipFile(archive)
        self.classification = Classification()
        if len(self.archive.namelist()) != len(set(self.archive.namelist())):
            raise ValueError("duplicate archive member")
        self.manifest = json.loads(self.archive.read("manifest.json"))
        if self.manifest["dataset_hash"] != BASE_DATASET_SHA256:
            raise ValueError("dataset differs")
        validate_manifest(self.manifest, self.archive.read)
        if sha256(sfp) != self.manifest["source_files"][SFP_SOURCE]["sha256"]:
            raise ValueError("SPY source differs")
        self.benchmark = {}
        level = Decimal(1)
        with gzip.open(sfp, "rt", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["ticker"] != "SPY" or row["date"] < "2004-01-01":
                    continue
                factor = Decimal(row["close_to_close_factor"])
                if not factor.is_finite() or factor <= 0:
                    raise ValueError("invalid SPY factor")
                if row["date"] in self.benchmark:
                    raise ValueError("duplicate SPY date")
                level *= factor
                self.benchmark[row["date"]] = level
        scale = self.benchmark[ORIGIN]
        self.benchmark = {d: v/scale for d, v in self.benchmark.items()}

    def rows(self, member):
        with self.archive.open(member) as binary:
            with gzip.GzipFile(fileobj=binary) as compressed:
                yield from csv.DictReader(io.TextIOWrapper(compressed, encoding="utf-8"))

    def sessions(self, after=None):
        previous = after
        for year in range(int((after or ORIGIN)[:4]), 2027):
            for day, group in itertools.groupby(self.rows(f"observations-{year}.csv.gz"),
                                                 key=lambda r: r["session"]):
                if after and day <= after:
                    continue
                rows = [self.classification.apply(row) for row in group]
                if previous and previous_sessions(day, 2)[0] != previous:
                    raise ValueError("nonadjacent observation session")
                if not previous and day != ORIGIN:
                    raise ValueError("January origin absent")
                if len({r["security_id"] for r in rows}) != len(rows):
                    raise ValueError("duplicate security observation")
                previous = day
                yield day, rows


def reference():
    path = _HARNESS / "research/bounded_20y/reference-daily.csv.gz"
    if sha256(path) != REFERENCE_SHA256:
        raise ValueError("retained reference bytes differ")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return {r["date"]: Decimal(r["nav"]) for r in csv.DictReader(f)}


def load_supplements(path, applied, last_session):
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    by_id = {}
    for row in rows:
        key = row["id"]
        if key in by_id:
            raise ValueError("duplicate supplemental identity")
        if (not row.get("sources") or any(not u.startswith("https://") for u in row["sources"])
                or row["known_by"] > row["effective_session"]
                or row["original_event_session"] > row["effective_session"]):
            raise ValueError("supplement lacks causal evidence")
        if (last_session and row["effective_session"] <= last_session
                and key not in applied):
            raise ValueError("new supplement would rewrite processed history")
        by_id[key] = row
    if any(by_id.get(key) != row for key, row in applied.items()):
        raise ValueError("applied supplemental evidence changed")
    return by_id


def write_checkpoint(output, packet):
    directory = output / "checkpoints"
    directory.mkdir(exist_ok=True)
    day = packet["state"]["last_processed_session"] or "genesis"
    path = directory / f"checkpoint-{day}.json.gz"
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=1) as f:
        json.dump(packet, f, separators=(",", ":"), allow_nan=False)
    checksum = sha256(temporary)
    os.replace(temporary, path)
    pointer = {"path": str(path.resolve()), "sha256": checksum,
               "bytes": path.stat().st_size, "last_session": packet["state"]["last_processed_session"]}
    temp_pointer = output / "latest-checkpoint.tmp"
    dump(temp_pointer, pointer)
    os.replace(temp_pointer, output / "latest-checkpoint.json")
    print("CHECKPOINT", day, pointer["bytes"], flush=True)
    return pointer


def read_checkpoint(pointer_path, binding):
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    path = Path(pointer["path"])
    if sha256(path) != pointer["sha256"]:
        raise ValueError("checkpoint bytes changed")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        packet = json.load(f)
    if packet["binding"] != binding:
        raise ValueError("checkpoint source/input binding differs")
    state = SessionState.from_dict(packet["state"])
    if state.state_hash != packet["state_sha256"] or state.last_processed_session != pointer["last_session"]:
        raise ValueError("checkpoint state commitment differs")
    return packet, state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", type=Path, required=True)
    for name in ("archive", "sfp", "output", "supplements"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--verify-resume", action="store_true")
    args = parser.parse_args()
    if not 0 < args.seconds <= 3600:
        raise ValueError("run budget exceeds authorization")
    started = _WORKER_STARTED
    deadline = started + args.seconds
    root = _HARNESS
    manifest = json.loads((_HARNESS / "research/bounded_20y/production-source.json").read_text())
    verify_production(root, manifest)
    binding = {"production": PRODUCTION_REVISION, "production_manifest": digest(manifest),
               "dataset": BASE_DATASET_SHA256, "reference": REFERENCE_SHA256,
               "harness": {n: sha256(_HARNESS / "research/bounded_20y" / n) for n in
                           ("january.py", "run.py", "inputs.py", "supplement.py")},
               "capital": "100000", "origin": ORIGIN, "measurement": START,
               "classification_intervals": OVERLAY_SHA256,
               "economic_runner": sha256(Path(__file__)),
               "economic_inputs": sha256(Path(__file__).with_name("inputs.py"))}
    config, identity = production_strategy()
    if args.resume:
        packet, state = read_checkpoint(args.resume, binding)
        meta = {sid: SecurityMeta(**r) for sid, r in packet["metadata"].items()}
        sectors, factors, economics, stats, applied = (packet[k] for k in
            ("sectors", "factors", "economics", "statistics", "applied_supplements"))
        total = packet["total_sessions"]
        if args.verify_resume:
            print(json.dumps({"status": "RESUME_VERIFIED", "last_session": state.last_processed_session,
                              "state_sha256": state.state_hash, "total_sessions": total}), flush=True)
            return 0
    else:
        if args.verify_resume:
            raise ValueError("verify-resume requires a checkpoint")
        state = SessionState.fresh(starting_cash=100000, controller=Controller(config), strategy_identity=identity)
        meta, sectors, factors, stats, applied = {}, {}, {}, {}, {}
        economics = {"strategy_nav": "100000", "last_session": None,
                     "pending_allocation": None, "held_allocation": None}
        total = 0
    args.output.mkdir(parents=True, exist_ok=False)
    dump(args.output / "identity.json", {**binding, "strategy_identity": identity,
         "seconds": args.seconds, "resume": str(args.resume) if args.resume else None})
    print("VERIFYING_INPUTS", flush=True)
    data, refs = JanuaryInputs(args.archive, args.sfp), reference()
    cash = {r["session"]: r for r in data.rows("cash.csv.gz")}
    terminal = terminals(supplemented_terminals(data.rows("terminal-events.csv.gz")))
    spins = distributions(data.rows("actions.csv.gz"))
    print("INPUTS_VERIFIED", round(time.monotonic()-started, 2), flush=True)
    account = EconomicPath(100000)
    status = {"date": state.last_processed_session, "phase": "FORMATION",
              "cagr": None, "reference_cagr": None}

    def checkpoint():
        return write_checkpoint(args.output, {"binding": binding,
            "state": state._canonical_mapping(_copy_feed=False), "state_sha256": state.state_hash,
            "metadata": {sid: asdict(m) for sid, m in meta.items()}, "sectors": sectors,
            "factors": factors, "economics": economics, "statistics": stats,
            "applied_supplements": applied, "total_sessions": total})

    def report(kind, **extra):
        payload = {**status, "status": kind, "total_sessions": total,
                   "elapsed_seconds": round(time.monotonic()-started, 2), **extra}
        dump(args.output / "status.json", payload)
        print(json.dumps(payload), flush=True)

    with (args.output / "daily.jsonl").open("w", encoding="utf-8") as trace:
        for day, rows in data.sessions(after=state.last_processed_session):
            if day > END or time.monotonic() >= deadline:
                break
            next_meta, next_sectors = dict(meta), dict(sectors)
            for row in rows:
                sid = row["security_id"]
                next_meta[sid], next_sectors[sid] = metadata(row), row["ff12"] or None
            anchors = {r["security_id"]: FeedAnchor(r["security_id"], r["ticker"],
                next_meta[r["security_id"]].issuer_key()[0], factors.get(r["security_id"], 1.0))
                for r in rows if r["security_id"] not in state.feed["series"]}
            spy_days = previous_sessions(day, 253)
            waiting_for = None
            while time.monotonic() < deadline:
                supplements = load_supplements(args.supplements, applied, state.last_processed_session)
                selected = {k: r for k, r in supplements.items() if r["effective_session"] == day}
                events = list(terminal.get(day, ()))
                extra = terminals(selected.values()).get(day, ()) if selected else ()
                if extra:
                    ids = {t.security_id for t in extra}
                    events = [t for t in events if t.security_id not in ids] + list(extra)
                try:
                    published = PublishedSession(session=day, data_version=1,
                        bars=[vendor(r) for r in rows], meta=next_meta, sectors=next_sectors,
                        spy_closeadj=[float(data.benchmark[d]) for d in spy_days],
                        spy_sessions=spy_days, spy_expected_sessions=spy_days, feed_anchors=anchors,
                        terminal_events=events, spinoff_distributions=spins.get(day, ()))
                    candidate = advance_session(state, published, controller_config=config, strategy_identity=identity)
                    gap, intraday = Decimal(cash[day]["gap_factor"]), Decimal(cash[day]["intraday_factor"])
                    prices = {"bil_open_signal": str(gap), "bil_close_signal": str(gap*intraday),
                        "bil_close_adjusted": str(gap*intraday), "bil_close_unadjusted": str(gap*intraday),
                        "bil_previous_close_adjusted": "1", "bil_previous_session": previous_sessions(day, 2)[0]}
                    next_economics = account.advance(previous=economics, state=candidate, strategy_prices=prices)
                except Exception as exc:
                    fingerprint = digest(supplements)
                    if waiting_for != fingerprint:
                        waiting_for = fingerprint
                        checkpoint()
                        failure = {"session": day, "error_type": type(exc).__name__, "error": str(exc),
                                   "held": state.wealth_core["episodes"], "traceback": traceback.format_exc()}
                        dump(args.output / f"blocked-{day}.json", failure)
                        report("WAITING_FOR_EVIDENCE", blocked_session=day, error=str(exc))
                    # Wait for independently researched terms without retrying the
                    # same failed transition or changing a production guard.
                    while time.monotonic() < deadline:
                        time.sleep(min(2, max(0, deadline-time.monotonic())))
                        if digest(load_supplements(args.supplements, applied, state.last_processed_session)) != fingerprint:
                            break
                    continue
                state, economics, meta, sectors = candidate, next_economics, next_meta, next_sectors
                applied.update(selected)
                for r in rows:
                    factors[r["security_id"]] = factors.get(r["security_id"], 1.0)*number(r["split_ratio"])
                total += 1
                stats, status = progress(stats, day, economics["strategy_nav"], refs, data.benchmark)
                trace.write(json.dumps({**status, "core_nav": economics["parent_core_close_equity"],
                    "spy_level": str(data.benchmark[day]),
                    "held_count": len(state.wealth_core["episodes"]), "decision": state.last_decision,
                    "economics": economics}, allow_nan=False)+"\n")
                trace.flush()
                if total % 20 == 0 or day == START or total == 1:
                    report("RUNNING")
                if total % 100 == 0:
                    checkpoint()
                break
            if time.monotonic() >= deadline:
                break
    saved = checkpoint()
    report("COMPLETE" if state.last_processed_session == END else "STOPPED_RESUMABLE", checkpoint=saved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
