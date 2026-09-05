#!/usr/bin/env python3
"""Allocate retained PIT authority to the frozen Champion closure worklist."""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


EXPECTED = {
    "worklist": "0c891b2e4f505cb7b21c857c373a12df4dcb766c430812678d9200e69b165c5b",
    "session_ledger": "2116177eb72436dc1c6fe5d59e57d739ff46a751cf5917748f3dd482dc604369",
    "v4_type_events": "",  # bound through the V4 artifact SHA256SUMS file
}
BASELINE = {"worklist": 6914, "unknown_type": 1751, "terminal": 1405}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _int(value: object) -> int:
    text = str(value or "").strip()
    return 0 if not text else int(float(text))


def _float_rank(value: object) -> int:
    text = str(value or "").strip()
    return 10**9 if not text else int(float(text))


def _read_csv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _verify_sums(root: Path) -> None:
    sums = root / "SHA256SUMS.txt"
    if not sums.is_file():
        raise RuntimeError("V4 artifact lacks SHA256SUMS.txt")
    for raw in sums.read_text(encoding="utf-8").splitlines():
        digest, name = raw.split(maxsplit=1)
        path = root / name.lstrip("*")
        if not path.is_file() or sha256_file(path) != digest:
            raise RuntimeError(f"V4 artifact member hash mismatch: {name}")


def _type_priority(row: dict[str, str]) -> tuple[str, int]:
    ranked = _int(row["durable_ranked_sessions"])
    leadership = _int(row["recent_leadership_sessions"])
    held = _int(row["held_sessions"])
    if ranked or leadership:
        return "1_REACHED_RANK_OR_LEADERSHIP", 1
    if _bool(row["potential_displacer"]):
        return "2_COUNTERFACTUAL_RANKING_REQUIRED", 2
    if held:
        return "3_HELD_HISTORY_ONLY", 3
    return "4_REMAINING_BOUNDARY", 4


def _terminal_priority(row: dict[str, str]) -> tuple[str, int]:
    if _int(row["held_sessions"]):
        return "1_HELD_POSITION", 1
    if _int(row["durable_ranked_sessions"]) or _int(row["recent_leadership_sessions"]):
        return "2_LEADERSHIP_PATH", 2
    return "3_CANDIDATE_BOUNDARY", 3


def _load_authority(root: Path):
    _verify_sums(root)
    events = _read_csv(root / "v4_authorized_security_type_events.csv.gz")
    conflicts = _read_csv(root / "security_type_conflicts_v4.csv.gz")
    conflict_keys = {
        (str(row["security_id"]), str(row["usable_after"])) for row in conflicts
    }
    grouped: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    rejected_conflicts = 0
    for row in events:
        sid = str(row["security_id"])
        date = str(row["usable_after"])
        classification = str(row["classification"])
        if classification not in {"common", "non_common"}:
            raise RuntimeError(f"invalid V4 classification: {classification!r}")
        if (sid, date) in conflict_keys:
            rejected_conflicts += 1
            continue
        existing = grouped[sid].get(date)
        if existing and existing["classification"] != classification:
            raise RuntimeError(f"unlisted V4 conflict for {sid} on {date}")
        grouped[sid][date] = row
    axes = {}
    rows = {}
    for sid, by_date in grouped.items():
        dates = tuple(sorted(by_date))
        axes[sid] = dates
        rows[sid] = tuple(by_date[date] for date in dates)
    return axes, rows, rejected_conflicts


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(*, worklist: Path, session_ledger: Path, v4_root: Path, output: Path,
          enforce_frozen_inputs: bool = True) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if enforce_frozen_inputs:
        if sha256_file(worklist) != EXPECTED["worklist"]:
            raise RuntimeError("Champion worklist hash mismatch")
        if sha256_file(session_ledger) != EXPECTED["session_ledger"]:
            raise RuntimeError("Champion session-ledger hash mismatch")

    source_rows = _read_csv(worklist)
    if len(source_rows) != BASELINE["worklist"]:
        raise RuntimeError("Champion worklist count mismatch")
    by_sid = {str(row["security_id"]): row for row in source_rows}
    if len(by_sid) != len(source_rows):
        raise RuntimeError("Champion worklist contains duplicate security IDs")
    unknown = {sid for sid, row in by_sid.items() if _bool(row["potential_displacer"])}
    terminals = {
        sid for sid, row in by_sid.items() if _int(row["incomplete_terminal_sessions"])
    }
    if len(unknown) != BASELINE["unknown_type"] or len(terminals) != BASELINE["terminal"]:
        raise RuntimeError("Champion closure baseline count mismatch")

    axes, authority_rows, rejected_conflicts = _load_authority(v4_root)
    resolved = Counter()
    classes: dict[str, Counter] = defaultdict(Counter)
    first_resolved: dict[str, str] = {}
    last_resolved: dict[str, str] = {}
    authority_accessions: dict[str, set[str]] = defaultdict(set)
    allocated_rows: list[dict[str, object]] = []
    observed_unknown = Counter()

    with gzip.open(session_ledger, "rt", encoding="utf-8") as handle:
        for raw in handle:
            payload = json.loads(raw)
            session = str(payload["session"])
            for sid0 in payload["base_candidate_unknown"]:
                sid = str(sid0)
                if sid not in unknown:
                    raise RuntimeError(f"session ledger unknown SID absent from worklist: {sid}")
                observed_unknown[sid] += 1
                dates = axes.get(sid, ())
                index = bisect.bisect_left(dates, session) - 1
                if index < 0:
                    continue
                evidence = authority_rows[sid][index]
                classification = evidence["classification"]
                resolved[sid] += 1
                classes[sid][classification] += 1
                first_resolved.setdefault(sid, session)
                last_resolved[sid] = session
                authority_accessions[sid].add(str(evidence["accession"]))
                allocated_rows.append({
                    "session": session,
                    "security_id": sid,
                    "ticker": by_sid[sid]["ticker"],
                    "classification": classification,
                    "usable_after": evidence["usable_after"],
                    "cik": evidence["cik"],
                    "accession": evidence["accession"],
                    "origin": evidence["origin"],
                })

    for sid in unknown:
        expected = _int(by_sid[sid]["unknown_type_base_sessions"])
        if observed_unknown[sid] != expected:
            raise RuntimeError(
                f"unknown session count mismatch for {sid}: {observed_unknown[sid]} != {expected}"
            )

    type_rows = []
    status_counts = Counter()
    for sid in unknown:
        row = by_sid[sid]
        total = observed_unknown[sid]
        count = resolved[sid]
        observed_classes = set(classes[sid])
        if count == 0:
            status = "UNRESOLVED"
        elif count < total:
            status = "PARTIAL"
        elif observed_classes == {"common"}:
            status = "ELIGIBLE"
        elif observed_classes == {"non_common"}:
            status = "INELIGIBLE"
        elif count == total:
            status = "TIME_VARYING_RESOLVED"
        else:
            raise AssertionError("unreachable classification state")
        status_counts[status] += 1
        label, number = _type_priority(row)
        type_rows.append({
            "priority": label,
            "security_id": sid,
            "ticker": row["ticker"],
            "first_touch_session": row["first_touch_session"],
            "last_touch_session": row["last_touch_session"],
            "unknown_sessions": total,
            "v4_resolved_sessions": count,
            "v4_unresolved_sessions": total - count,
            "v4_common_sessions": classes[sid]["common"],
            "v4_non_common_sessions": classes[sid]["non_common"],
            "allocation_status": status,
            "first_v4_resolved_session": first_resolved.get(sid, ""),
            "last_v4_resolved_session": last_resolved.get(sid, ""),
            "v4_accession_count": len(authority_accessions[sid]),
            "best_durable_rank": row["best_durable_rank"],
            "durable_ranked_sessions": row["durable_ranked_sessions"],
            "recent_leadership_sessions": row["recent_leadership_sessions"],
            "pending_sessions": row["pending_sessions"],
            "held_sessions": row["held_sessions"],
            "_priority_number": number,
        })
    type_rows.sort(key=lambda row: (
        row["_priority_number"], _float_rank(row["best_durable_rank"]),
        -_int(row["held_sessions"]), -_int(row["durable_ranked_sessions"]),
        -_int(row["unknown_sessions"]), str(row["security_id"]),
    ))
    for row in type_rows:
        row.pop("_priority_number")

    terminal_rows = []
    for sid in terminals:
        row = by_sid[sid]
        label, number = _terminal_priority(row)
        terminal_rows.append({
            "priority": label,
            "security_id": sid,
            "ticker": row["ticker"],
            "first_touch_session": row["first_touch_session"],
            "last_touch_session": row["last_touch_session"],
            "incomplete_terminal_sessions": row["incomplete_terminal_sessions"],
            "held_sessions": row["held_sessions"],
            "pending_sessions": row["pending_sessions"],
            "durable_ranked_sessions": row["durable_ranked_sessions"],
            "recent_leadership_sessions": row["recent_leadership_sessions"],
            "best_durable_rank": row["best_durable_rank"],
            "_priority_number": number,
        })
    terminal_rows.sort(key=lambda row: (
        row["_priority_number"], -_int(row["held_sessions"]),
        _float_rank(row["best_durable_rank"]),
        -_int(row["recent_leadership_sessions"]), str(row["security_id"]),
    ))
    for row in terminal_rows:
        row.pop("_priority_number")

    type_path = output / "security-type-priority.csv"
    terminal_path = output / "terminal-priority.csv"
    allocated_path = output / "v4-allocated-observations.csv.gz"
    _write_csv(type_path, type_rows, list(type_rows[0]))
    _write_csv(terminal_path, terminal_rows, list(terminal_rows[0]))
    with allocated_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as binary:
            import io
            with io.TextIOWrapper(binary, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(allocated_rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows(allocated_rows)

    summary = {
        "schema": "backtester.research-champion-pit-authority-allocation/1",
        "status": "PASS",
        "source": {
            "champion_run_id": "33994291853",
            "champion_source_sha": "53dc0bf9adbe7d3ee60b2a54d9769dcdfdea7306",
            "champion_worklist_sha256": sha256_file(worklist),
            "champion_session_ledger_sha256": sha256_file(session_ledger),
            "v4_run_id": "33720489684",
            "v4_sha256s_sha256": sha256_file(v4_root / "SHA256SUMS.txt"),
        },
        "baseline": BASELINE,
        "security_type": {
            "status_counts": dict(sorted(status_counts.items())),
            "resolved_securities": sum(1 for sid in unknown if resolved[sid]),
            "resolved_observations": sum(resolved.values()),
            "common_observations": sum(value["common"] for value in classes.values()),
            "non_common_observations": sum(value["non_common"] for value in classes.values()),
            "remaining_unresolved_observations": sum(observed_unknown.values()) - sum(resolved.values()),
            "rank_or_leadership_securities_touched": sum(
                1 for row in type_rows
                if row["priority"] == "1_REACHED_RANK_OR_LEADERSHIP"
                and _int(row["v4_resolved_sessions"])
            ),
            "rejected_conflicted_authority_rows": rejected_conflicts,
        },
        "terminal": {
            "starting_worklist": len(terminal_rows),
            "held_position_cases": sum(_int(row["held_sessions"]) > 0 for row in terminal_rows),
            "leadership_cases": sum(
                _int(row["durable_ranked_sessions"]) > 0
                or _int(row["recent_leadership_sessions"]) > 0
                for row in terminal_rows
            ),
        },
        "next_gate": "publish allocated ledger as immutable input, rebuild corpus, and measure ranking/trade deltas",
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [type_path, terminal_path, allocated_path, summary_path]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--session-ledger", type=Path, required=True)
    parser.add_argument("--v4-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fixtures", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    result = build(
        worklist=args.worklist,
        session_ledger=args.session_ledger,
        v4_root=args.v4_root,
        output=args.output,
        enforce_frozen_inputs=not args.allow_fixtures,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
