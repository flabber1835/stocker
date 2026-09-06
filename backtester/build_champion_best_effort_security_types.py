#!/usr/bin/env python3
"""Build the time-boxed Champion common-stock eligibility estimate."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path


SCHEMA = "backtester.champion-best-effort-security-types/1"
LABEL = "BEST_EFFORT_NOT_PIT_CERTIFIED"
EXPECTED = {
    "worklist": "0c891b2e4f505cb7b21c857c373a12df4dcb766c430812678d9200e69b165c5b",
    "session_ledger": "2116177eb72436dc1c6fe5d59e57d739ff46a751cf5917748f3dd482dc604369",
    "stage1_priority": "d7a94b293eb9014843039684f0c892781a2e7ad80fb3e3e656ff46de8fbac3ef",
    "tickers": "308bcc46f4efaffe6f6fc4f7236af82df5c57a9f2be07c677089f0e6fba2eebf",
}
COMMON_CATEGORIES = frozenset({
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
    "Domestic Common Stock Secondary Class",
    "ADR Common Stock",
    "ADR Common Stock Primary Class",
    "ADR Common Stock Secondary Class",
    "Canadian Common Stock",
    "Canadian Common Stock Primary Class",
    "Canadian Common Stock Secondary Class",
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _int(value: object) -> int:
    text = str(value or "").strip()
    return int(float(text)) if text else 0


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_tickers(path: Path) -> tuple[dict[str, dict[str, str]], set[str]]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"TICKERS archive requires exactly one CSV: {members}")
        with archive.open(members[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            rows: dict[str, dict[str, str]] = {}
            duplicates: set[str] = set()
            for row in reader:
                if str(row.get("table") or "") != "SEP":
                    continue
                ticker = str(row.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                if ticker in rows:
                    duplicates.add(ticker)
                else:
                    rows[ticker] = row
    return rows, duplicates


def _category_classification(category: str) -> str:
    if category in COMMON_CATEGORIES:
        return "common"
    lowered = category.lower()
    if "preferred stock" in lowered or "warrant" in lowered:
        return "non_common"
    return "unknown"


def _known_class(row: dict[str, str]) -> str:
    common = _int(row.get("known_common_base_sessions"))
    non_common = _int(row.get("known_non_common_base_sessions"))
    if common and non_common:
        return "conflict"
    if common:
        return "common"
    if non_common:
        return "non_common"
    return "unknown"


def _unknown_session_bounds(
    path: Path, required: set[str]
) -> tuple[dict[str, list[object]], int]:
    bounds = {sid: [None, None, 0] for sid in required}
    observations = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for raw in handle:
            payload = json.loads(raw)
            session = str(payload["session"])
            for sid0 in payload.get("base_candidate_unknown") or ():
                sid = str(sid0)
                if sid not in bounds:
                    raise RuntimeError(f"unknown security absent from worklist: {sid}")
                value = bounds[sid]
                value[0] = value[0] or session
                value[1] = session
                value[2] = int(value[2]) + 1
                observations += 1
    return bounds, observations


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(
    *,
    worklist: Path,
    session_ledger: Path,
    stage1_priority: Path,
    tickers: Path,
    output: Path,
    enforce_frozen_inputs: bool = True,
) -> dict:
    inputs = {
        "worklist": worklist,
        "session_ledger": session_ledger,
        "stage1_priority": stage1_priority,
        "tickers": tickers,
    }
    hashes = {name: sha256_file(path) for name, path in inputs.items()}
    if enforce_frozen_inputs and hashes != EXPECTED:
        raise RuntimeError(f"frozen input hash mismatch: {hashes}")

    work_rows = _read_csv(worklist)
    work_by_sid = {str(row["security_id"]): row for row in work_rows}
    if len(work_by_sid) != len(work_rows):
        raise RuntimeError("duplicate security ID in Champion worklist")
    required = {
        sid for sid, row in work_by_sid.items()
        if str(row.get("potential_displacer") or "").lower() == "true"
    }
    if enforce_frozen_inputs and len(required) != 1751:
        raise RuntimeError(f"expected 1751 unknown-type securities, got {len(required)}")

    priority_rows = _read_csv(stage1_priority)
    priority = {str(row["security_id"]): row for row in priority_rows}
    if set(priority) != required:
        raise RuntimeError("stage-one priority does not exactly cover unknown worklist")
    bounds, observations = _unknown_session_bounds(session_ledger, required)
    metadata, duplicate_tickers = _load_tickers(tickers)

    ledger: list[dict[str, object]] = []
    dispositions = Counter()
    classes = Counter()
    inferred_observations = Counter()
    categories = Counter()
    for sid in sorted(required):
        base = work_by_sid[sid]
        prior = priority[sid]
        ticker = str(base["ticker"]).strip().upper()
        first, last, count0 = bounds[sid]
        count = int(count0)
        if count != _int(base.get("unknown_type_base_sessions")):
            raise RuntimeError(f"unknown observation mismatch for {sid}: {count}")

        row = metadata.get(ticker)
        category = "" if row is None else str(row.get("category") or "").strip()
        categories[category or "MISSING"] += 1
        inferred = _category_classification(category)
        known = _known_class(base)
        v4_common = _int(prior.get("v4_common_sessions"))
        v4_non_common = _int(prior.get("v4_non_common_sessions"))
        v4_class = (
            "conflict" if v4_common and v4_non_common else
            "common" if v4_common else
            "non_common" if v4_non_common else "unknown"
        )

        meta_first = "" if row is None else str(row.get("firstpricedate") or "")[:10]
        meta_last = "" if row is None else str(row.get("lastpricedate") or "")[:10]
        covers = bool(
            row is not None and first and last and meta_first
            and meta_first <= str(first)
            and (not meta_last or meta_last >= str(last))
        )
        if ticker in duplicate_tickers:
            disposition, accepted, reason = "REJECTED_DUPLICATE_SEP_TICKER", "unknown", "ticker has multiple SEP securities-master rows"
        elif row is None:
            disposition, accepted, reason = "REJECTED_NO_SEP_METADATA", "unknown", "ticker absent from SEP securities master"
        elif inferred == "unknown":
            disposition, accepted, reason = "REJECTED_AMBIGUOUS_CATEGORY", "unknown", f"unmapped category: {category or 'MISSING'}"
        elif not covers:
            disposition, accepted, reason = "REJECTED_PRICE_INTERVAL", "unknown", "metadata price bounds do not cover every unknown candidate session"
        elif known in {"common", "non_common", "conflict"} and known != inferred:
            disposition, accepted, reason = "REJECTED_KNOWN_PATH_CONFLICT", "unknown", f"known path class {known} conflicts with vendor {inferred}"
        elif v4_class in {"common", "non_common", "conflict"} and v4_class != inferred:
            disposition, accepted, reason = "REJECTED_V4_CONFLICT", "unknown", f"V4 class {v4_class} conflicts with vendor {inferred}"
        else:
            disposition = "INFERRED_COMMON" if inferred == "common" else "INFERRED_NON_COMMON"
            accepted, reason = inferred, "unique SEP row; category unambiguous; interval covered; no admitted conflict"

        inferred_count = count if accepted != "unknown" else 0
        dispositions[disposition] += 1
        classes[accepted] += 1
        inferred_observations[accepted] += inferred_count
        ledger.append({
            "security_id": sid,
            "ticker": ticker,
            "classification": accepted,
            "disposition": disposition,
            "label": LABEL,
            "category": category,
            "unknown_first_session": first or "",
            "unknown_last_session": last or "",
            "unknown_sessions": count,
            "inferred_observations": inferred_count,
            "metadata_firstpricedate": meta_first,
            "metadata_lastpricedate": meta_last,
            "vendor_permaticker": "" if row is None else str(row.get("permaticker") or ""),
            "figi": "" if row is None else str(row.get("figi") or ""),
            "cusips": "" if row is None else str(row.get("cusips") or ""),
            "stage1_status": str(prior.get("allocation_status") or ""),
            "known_path_class": known,
            "v4_class": v4_class,
            "reason": reason,
        })

    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "security-type-best-effort.csv"
    summary_path = output / "summary.json"
    _write_csv(ledger_path, ledger)
    accepted_observations = sum(inferred_observations.values())
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "label": LABEL,
        "certification_eligible": False,
        "source_hashes": hashes,
        "counts": {
            "security_count": len(required),
            "unknown_candidate_observations": observations,
            "classification": dict(sorted(classes.items())),
            "disposition": dict(sorted(dispositions.items())),
            "inferred_observations": dict(sorted(inferred_observations.items())),
            "remaining_uncertain_observations": observations - accepted_observations,
        },
        "coverage": {
            "security_fraction": (len(required) - classes["unknown"]) / len(required),
            "observation_fraction": accepted_observations / observations,
        },
        "category_counts": dict(sorted(categories.items())),
        "contract": {
            "common_categories": sorted(COMMON_CATEGORIES),
            "excluded_category_tokens": ["Preferred Stock", "Warrant"],
            "historical_availability_proven": False,
            "permitted_use": "best-effort sensitivity replay only",
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [ledger_path, summary_path]
    sums_path = output / "SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--session-ledger", type=Path, required=True)
    parser.add_argument("--stage1-priority", type=Path, required=True)
    parser.add_argument("--tickers", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-fixtures", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    summary = build(
        worklist=args.worklist,
        session_ledger=args.session_ledger,
        stage1_priority=args.stage1_priority,
        tickers=args.tickers,
        output=args.output,
        enforce_frozen_inputs=not args.allow_fixtures,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
