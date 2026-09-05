#!/usr/bin/env python3
"""Stage B2: historical-price-path identity reconstruction for IWB/IWM proxy holdings.

BlackRock archival holdings preserve historical quantities, values and unit prices even
when some descriptive security-master fields have been updated retrospectively.  This
pass therefore requires price agreement on the historical session before accepting a
reported ticker, and uses repeated CUSIP/ISIN/SEDOL + price paths to recover historical
security episodes.  SEC N-Q name-only rows are resolved only by normalized issuer-name
continuity plus exact implied-price agreement.

This is a HISTORICAL_STATE_PROXY reconstruction.  It does not claim that later archival
identity evidence was information available to a model on the historical date.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from backtester.r3000_proxy_identity_closure import (
    CAVEAT,
    STATUSES,
    legal_name_key,
    read_csv,
    security_key,
    sha256_file,
    strict_name_key,
    ticker_key,
    verify_sha256s,
    write_csv_gz,
)

SCHEMA = "stocker.r3000-proxy.identity-closure/2"
EXTRA_FIELDS = (
    "identity_target_session",
    "reported_sedol",
    "reported_exchange",
    "reported_country_of_risk",
    "reported_unit_price",
    "identity_method",
    "identity_candidate_count",
    "identity_reason",
    "identity_price_candidate_count",
    "identity_price_match_cents",
    "identity_path_support",
    "identity_canonical_security_type",
    "identity_canonical_issuer_source",
    "identity_canonical_identity_source",
    "identity_canonical_listing_active",
    "identity_canonical_tradeable",
)


def _number(value: str) -> Decimal | None:
    text = (value or "").replace(",", "").replace("$", "").strip()
    if not text or text == "-":
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _cents(value: str | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else _number(str(value))
    if number is None or not number.is_finite() or number <= 0:
        return None
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_sec_name(value: str) -> str:
    text = (value or "").strip()
    # SEC N-Q schedule footnote markers are lower-case letters appended to the
    # security name (for example "Amazon.com Inc. a" or "Issuer Inc. a,b").
    text = re.sub(r"(?:\s+[a-z](?:\s*,\s*[a-z])*)\s*$", "", text)
    text = re.sub(r"\s+\*+\s*$", "", text)
    return text.strip()


def _name_key(value: str, *, drop_class: bool) -> str:
    text = _clean_sec_name(value)
    if drop_class:
        text = re.sub(
            r"\b(?:CLASS|CL)\s+[A-Z0-9]+\b", " ", text, flags=re.IGNORECASE
        )
        text = re.sub(r"\b(?:COMMON|ORDINARY)\s+SHARES?\b", " ", text, flags=re.IGNORECASE)
    return legal_name_key(text)


def _dp(payload: dict, key: str):
    point = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"][key]
    value = point.get("formattedValue")
    return value if isinstance(value, list) else point.get("value")


def _source_row_id(row: dict[str, str]) -> str:
    return "|".join(
        (
            row.get("fund", ""),
            row.get("holdings_effective_date", ""),
            row.get("source_sha256", ""),
            row.get("source_row_number", ""),
        )
    )


def _evidence(
    method: str,
    *,
    dataset_hash: str,
    session: str,
    row: dict[str, str],
    detail: str,
) -> str:
    return json.dumps(
        {
            "method": method,
            "canonical_dataset_hash": dataset_hash,
            "canonical_session": session,
            "source_type": row.get("source_type", ""),
            "source_id": row.get("source_id", ""),
            "source_sha256": row.get("source_sha256", ""),
            "source_row_number": row.get("source_row_number", ""),
            "detail": detail,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _reset(row: dict[str, str], session: str) -> None:
    row["identity_target_session"] = session
    row["identity_status"] = "UNMATCHED"
    row["normalized_security_id"] = ""
    row["normalized_ticker_on_snapshot_date"] = ""
    row["normalized_issuer_id"] = ""
    row["identity_authority"] = ""
    row["identity_evidence_refs"] = ""
    row["identity_method"] = ""
    row["identity_candidate_count"] = "0"
    row["identity_reason"] = "NOT_RESOLVED"
    row["identity_price_candidate_count"] = "0"
    row["identity_price_match_cents"] = ""
    row["identity_path_support"] = ""
    row["identity_canonical_security_type"] = ""
    row["identity_canonical_issuer_source"] = ""
    row["identity_canonical_identity_source"] = ""
    row["identity_canonical_listing_active"] = ""
    row["identity_canonical_tradeable"] = ""


def _set_resolution(
    row: dict[str, str],
    *,
    status: str,
    method: str,
    records: list[dict[str, str]],
    reason: str,
    dataset_hash: str,
    detail: str,
    price_candidate_count: int,
    price_match: Decimal | None,
    path_support: str = "",
) -> None:
    unique = {record["security_id"]: record for record in records if record.get("security_id")}
    row["identity_status"] = status
    row["identity_method"] = method
    row["identity_candidate_count"] = str(len(unique))
    row["identity_reason"] = reason
    row["identity_price_candidate_count"] = str(price_candidate_count)
    row["identity_price_match_cents"] = "" if price_match is None else format(price_match, "f")
    row["identity_path_support"] = path_support
    row["identity_evidence_refs"] = _evidence(
        method,
        dataset_hash=dataset_hash,
        session=row["identity_target_session"],
        row=row,
        detail=detail,
    )
    if status != "RESOLVED":
        return
    if len(unique) != 1:
        raise RuntimeError("RESOLVED requires exactly one security_id")
    record = next(iter(unique.values()))
    row["normalized_security_id"] = record.get("security_id", "")
    row["normalized_ticker_on_snapshot_date"] = record.get("ticker", "")
    row["normalized_issuer_id"] = record.get("issuer_id", "")
    row["identity_authority"] = method
    row["identity_canonical_security_type"] = record.get("security_type", "")
    row["identity_canonical_issuer_source"] = record.get("issuer_source", "")
    row["identity_canonical_identity_source"] = record.get("identity_source", "")
    row["identity_canonical_listing_active"] = record.get("listing_active", "")
    row["identity_canonical_tradeable"] = record.get("tradeable", "")


def _load_sessions(canonical_root: Path) -> list[str]:
    with (canonical_root / "session-hashes.csv").open("r", encoding="utf-8", newline="") as handle:
        sessions = [row["session"] for row in csv.DictReader(handle)]
    if not sessions or sessions != sorted(sessions) or len(sessions) != len(set(sessions)):
        raise RuntimeError("canonical session axis invalid")
    return sessions


def _target_sessions(sessions: list[str], dates: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for effective in sorted(dates):
        index = bisect.bisect_right(sessions, effective) - 1
        if index < 0:
            raise RuntimeError(f"no canonical session at or before {effective}")
        result[effective] = sessions[index]
    return result


def _load_target_observations(
    canonical_root: Path, target_by_date: dict[str, str]
) -> tuple[
    dict[str, dict[str, dict[str, str]]],
    dict[str, dict[str, list[dict[str, str]]]],
    dict[str, dict[Decimal, list[dict[str, str]]]],
]:
    targets_by_year: dict[int, set[str]] = defaultdict(set)
    for session in target_by_date.values():
        targets_by_year[int(session[:4])].add(session)

    by_sid: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    by_ticker: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    by_price: dict[str, dict[Decimal, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))

    required = {
        "session", "security_id", "ticker", "issuer_id", "issuer_source", "security_type",
        "listing_active", "tradeable", "identity_source", "raw_close", "exchange",
    }
    for year, targets in sorted(targets_by_year.items()):
        path = canonical_root / f"observations-{year}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"missing {path.name}")
        maximum = max(targets)
        found: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required.issubset(set(reader.fieldnames or [])):
                raise RuntimeError(f"canonical columns incomplete in {path.name}")
            for record in reader:
                session = record["session"]
                if session > maximum:
                    break
                if session not in targets:
                    continue
                found.add(session)
                sid = record.get("security_id", "")
                if not sid:
                    continue
                by_sid[session][sid] = record
                tkey = ticker_key(record.get("ticker", ""))
                if tkey:
                    by_ticker[session][tkey].append(record)
                pkey = _cents(record.get("raw_close", ""))
                if pkey is not None:
                    by_price[session][pkey].append(record)
        if found != targets:
            raise RuntimeError(f"canonical target sessions missing: {sorted(targets - found)}")
    return by_sid, by_ticker, by_price


def _augment_blackrock(stage_a: Path, rows: list[dict[str, str]]) -> None:
    cache: dict[str, dict[str, list]] = {}
    keys = ("sedol", "exchange", "countryOfRisk", "unitPrice")
    for row in rows:
        row.setdefault("reported_sedol", "")
        row.setdefault("reported_exchange", "")
        row.setdefault("reported_country_of_risk", "")
        row.setdefault("reported_unit_price", "")
        if row.get("source_type") != "blackrock_product_data_v2":
            shares = _number(row.get("reported_shares", ""))
            market = _number(row.get("reported_market_value", ""))
            if shares and market and shares > 0 and market > 0:
                row["reported_unit_price"] = format(market / shares, "f")
            continue
        source_id = row.get("source_id", "")
        if source_id not in cache:
            path = stage_a / "raw" / source_id
            payload = json.loads(path.read_text(encoding="utf-8"))
            cache[source_id] = {key: _dp(payload, key) for key in keys}
        values = cache[source_id]
        index = int(row["source_row_number"]) - 1
        mapping = {
            "reported_sedol": "sedol",
            "reported_exchange": "exchange",
            "reported_country_of_risk": "countryOfRisk",
            "reported_unit_price": "unitPrice",
        }
        for field, key in mapping.items():
            value = values[key][index]
            row[field] = "" if value in (None, "-") else str(value).strip()


def _price_records(
    row: dict[str, str], by_price: dict[str, dict[Decimal, list[dict[str, str]]]]
) -> tuple[Decimal | None, list[dict[str, str]]]:
    price = _cents(row.get("reported_unit_price", ""))
    if price is None:
        return None, []
    records = by_price.get(row["identity_target_session"], {}).get(price, [])
    unique = {record["security_id"]: record for record in records}
    return price, list(unique.values())


def _identifier_keys(row: dict[str, str]) -> list[str]:
    result = []
    for field, prefix in (
        ("reported_isin", "ISIN"),
        ("reported_cusip", "CUSIP"),
        ("reported_sedol", "SEDOL"),
    ):
        value = security_key(row.get(field, ""))
        if value:
            result.append(f"{prefix}:{value}")
    return result


def close_identity_v2(stage_a: Path, canonical_root: Path, output: Path) -> dict:
    verify_sha256s(stage_a)
    stage_summary = json.loads((stage_a / "summary.json").read_text(encoding="utf-8"))
    if stage_summary.get("status") != "PASS":
        raise RuntimeError("Stage A is not PASS")
    fields, rows = read_csv(stage_a / "parsed_holdings.csv.gz")
    if len(rows) != int(stage_summary.get("parsed_equity_rows", -1)):
        raise RuntimeError("Stage A row count changed")
    if len({_source_row_id(row) for row in rows}) != len(rows):
        raise RuntimeError("duplicate source row identity")
    _augment_blackrock(stage_a, rows)

    manifest_path = canonical_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_hash = str(manifest.get("dataset_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", dataset_hash):
        raise RuntimeError("canonical dataset hash invalid")

    dates = {row["holdings_effective_date"] for row in rows}
    target_by_date = _target_sessions(_load_sessions(canonical_root), dates)
    by_sid, by_ticker, by_price = _load_target_observations(canonical_root, target_by_date)

    for row in rows:
        _reset(row, target_by_date[row["holdings_effective_date"]])

    price_cache: dict[int, tuple[Decimal | None, list[dict[str, str]]]] = {}
    for index, row in enumerate(rows):
        price, records = _price_records(row, by_price)
        price_cache[index] = (price, records)
        row["identity_price_candidate_count"] = str(len(records))
        row["identity_price_match_cents"] = "" if price is None else format(price, "f")

    direct = 0
    retroactive_ticker_mismatches = 0
    for index, row in enumerate(rows):
        if row.get("source_type") != "blackrock_product_data_v2":
            continue
        price, price_records = price_cache[index]
        if price is None:
            row["identity_reason"] = "NO_HISTORICAL_UNIT_PRICE"
            continue
        ticker_records = by_ticker.get(row["identity_target_session"], {}).get(
            ticker_key(row.get("reported_ticker", "")), []
        )
        price_sids = {record["security_id"] for record in price_records}
        matches = {
            record["security_id"]: record
            for record in ticker_records
            if record.get("security_id") in price_sids
        }
        if len(matches) == 1:
            _set_resolution(
                row,
                status="RESOLVED",
                method="CANONICAL_HISTORICAL_TICKER_PLUS_UNIT_PRICE",
                records=list(matches.values()),
                reason="",
                dataset_hash=dataset_hash,
                detail=f"ticker={row.get('reported_ticker','')};unit_price={price}",
                price_candidate_count=len(price_records),
                price_match=price,
                path_support="DIRECT",
            )
            direct += 1
        elif len(matches) > 1:
            _set_resolution(
                row,
                status="AMBIGUOUS",
                method="CANONICAL_HISTORICAL_TICKER_PLUS_UNIT_PRICE",
                records=list(matches.values()),
                reason="MULTIPLE_SECURITY_IDS_MATCH_TICKER_AND_PRICE",
                dataset_hash=dataset_hash,
                detail=f"ticker={row.get('reported_ticker','')};unit_price={price}",
                price_candidate_count=len(price_records),
                price_match=price,
            )
        else:
            if ticker_records:
                retroactive_ticker_mismatches += 1
                row["identity_reason"] = "REPORTED_TICKER_PRESENT_BUT_PRICE_DISAGREES"
            else:
                row["identity_reason"] = "REPORTED_TICKER_ABSENT_ON_HISTORICAL_SESSION"

    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.get("source_type") != "blackrock_product_data_v2":
            continue
        for key in _identifier_keys(row):
            groups[key].append(index)

    group_support: dict[str, dict[str, int]] = {}
    group_direct: dict[str, set[str]] = {}
    for key, indexes in groups.items():
        counts: Counter[str] = Counter()
        direct_sids: set[str] = set()
        for index in indexes:
            _, records = price_cache[index]
            counts.update({record["security_id"] for record in records})
            row = rows[index]
            if row.get("identity_status") == "RESOLVED" and row.get("normalized_security_id"):
                direct_sids.add(row["normalized_security_id"])
        qualified = {
            sid: count
            for sid, count in counts.items()
            if count >= 3 or (count >= 2 and sid in direct_sids)
        }
        group_support[key] = qualified
        group_direct[key] = direct_sids

    path_resolved = 0
    path_ambiguous = 0
    for index, row in enumerate(rows):
        if row.get("source_type") != "blackrock_product_data_v2" or row.get("identity_status") == "RESOLVED":
            continue
        price, price_records = price_cache[index]
        if price is None:
            continue
        price_by_sid = {record["security_id"]: record for record in price_records}
        support: dict[str, dict[str, object]] = {}
        for key in _identifier_keys(row):
            for sid, count in group_support.get(key, {}).items():
                if sid not in price_by_sid:
                    continue
                entry = support.setdefault(sid, {"max": 0, "sum": 0, "keys": [], "direct": False})
                entry["max"] = max(int(entry["max"]), count)
                entry["sum"] = int(entry["sum"]) + count
                entry["keys"].append(key)
                if sid in group_direct.get(key, set()):
                    entry["direct"] = True
        if not support:
            row["identity_reason"] = "NO_REPEATED_IDENTIFIER_PRICE_PATH"
            continue
        ranked = sorted(
            support.items(),
            key=lambda item: (
                1 if item[1]["direct"] else 0,
                int(item[1]["max"]),
                int(item[1]["sum"]),
                item[0],
            ),
            reverse=True,
        )
        winner_sid, winner = ranked[0]
        winner_score = (1 if winner["direct"] else 0, int(winner["max"]), int(winner["sum"]))
        tied = [
            sid
            for sid, detail in ranked
            if (1 if detail["direct"] else 0, int(detail["max"]), int(detail["sum"])) == winner_score
        ]
        support_text = json.dumps(support, sort_keys=True, separators=(",", ":"))
        if len(tied) == 1:
            _set_resolution(
                row,
                status="RESOLVED",
                method="BLACKROCK_IDENTIFIER_PLUS_HISTORICAL_PRICE_PATH",
                records=[price_by_sid[winner_sid]],
                reason="",
                dataset_hash=dataset_hash,
                detail=f"unit_price={price};identifier_path={','.join(winner['keys'])}",
                price_candidate_count=len(price_records),
                price_match=price,
                path_support=support_text,
            )
            path_resolved += 1
        else:
            _set_resolution(
                row,
                status="AMBIGUOUS",
                method="BLACKROCK_IDENTIFIER_PLUS_HISTORICAL_PRICE_PATH",
                records=[price_by_sid[sid] for sid in tied],
                reason="TIED_IDENTIFIER_PRICE_PATH",
                dataset_hash=dataset_hash,
                detail=f"unit_price={price}",
                price_candidate_count=len(price_records),
                price_match=price,
                path_support=support_text,
            )
            path_ambiguous += 1

    # Build issuer-name continuity only from price-certified BlackRock identities.
    name_exact: dict[str, set[str]] = defaultdict(set)
    name_broad: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2" or row.get("identity_status") != "RESOLVED":
            continue
        sid = row.get("normalized_security_id", "")
        exact = _name_key(row.get("reported_issuer_name", ""), drop_class=False)
        broad = _name_key(row.get("reported_issuer_name", ""), drop_class=True)
        if exact:
            name_exact[exact].add(sid)
        if broad:
            name_broad[broad].add(sid)

    sec_exact = 0
    sec_broad = 0
    sec_ambiguous = 0
    for index, row in enumerate(rows):
        if row.get("source_type") != "sec_n-q":
            continue
        price, price_records = price_cache[index]
        if price is None:
            row["identity_reason"] = "SEC_IMPLIED_PRICE_UNAVAILABLE"
            continue
        price_by_sid = {record["security_id"]: record for record in price_records}
        attempts = (
            ("SEC_NORMALIZED_NAME_PLUS_IMPLIED_PRICE", _name_key(row.get("reported_issuer_name", ""), drop_class=False), name_exact),
            ("SEC_BROAD_NAME_PLUS_IMPLIED_PRICE", _name_key(row.get("reported_issuer_name", ""), drop_class=True), name_broad),
        )
        matched = False
        for method, key, index_map in attempts:
            if not key:
                continue
            sids = sorted(index_map.get(key, set()) & set(price_by_sid))
            if len(sids) == 1:
                _set_resolution(
                    row,
                    status="RESOLVED",
                    method=method,
                    records=[price_by_sid[sids[0]]],
                    reason="",
                    dataset_hash=dataset_hash,
                    detail=f"name={key};implied_price={price}",
                    price_candidate_count=len(price_records),
                    price_match=price,
                    path_support=f"NAME:{key}",
                )
                if method == "SEC_NORMALIZED_NAME_PLUS_IMPLIED_PRICE":
                    sec_exact += 1
                else:
                    sec_broad += 1
                matched = True
                break
            if len(sids) > 1:
                _set_resolution(
                    row,
                    status="AMBIGUOUS",
                    method=method,
                    records=[price_by_sid[sid] for sid in sids],
                    reason="MULTIPLE_NAME_AND_PRICE_MATCHES",
                    dataset_hash=dataset_hash,
                    detail=f"name={key};implied_price={price}",
                    price_candidate_count=len(price_records),
                    price_match=price,
                )
                sec_ambiguous += 1
                matched = True
                break
        if not matched:
            row["identity_reason"] = "NO_PRICE_CERTIFIED_NAME_CONTINUITY"
            row["identity_method"] = "SEC_NAME_PLUS_IMPLIED_PRICE"

    # Any resolved row must match the source price on the exact historical target session.
    price_validation_failures = 0
    for index, row in enumerate(rows):
        if row.get("identity_status") != "RESOLVED":
            continue
        price, records = price_cache[index]
        sid = row.get("normalized_security_id", "")
        if price is None or sid not in {record["security_id"] for record in records}:
            price_validation_failures += 1
            row["identity_status"] = "CONFLICT"
            row["identity_reason"] = "RESOLVED_IDENTITY_FAILED_HISTORICAL_PRICE_VALIDATION"
            row["normalized_security_id"] = ""
            row["normalized_ticker_on_snapshot_date"] = ""
            row["normalized_issuer_id"] = ""
            row["identity_authority"] = ""

    counts = Counter(row.get("identity_status", "") for row in rows)
    if set(counts) - set(STATUSES):
        raise RuntimeError(f"unknown status: {sorted(set(counts)-set(STATUSES))}")

    assignments: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    snapshot_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        snap = (row.get("fund", ""), row.get("holdings_effective_date", ""))
        snapshot_counts[snap][row["identity_status"]] += 1
        if row["identity_status"] == "RESOLVED" and row.get("normalized_security_id"):
            assignments[(snap[0], snap[1], row["normalized_security_id"])].append(_source_row_id(row))
    duplicates = [
        {"fund": key[0], "holdings_effective_date": key[1], "security_id": key[2], "source_rows": source_rows}
        for key, source_rows in sorted(assignments.items()) if len(source_rows) > 1
    ]

    output.mkdir(parents=True, exist_ok=True)
    out_fields = list(fields)
    for field in EXTRA_FIELDS:
        if field not in out_fields:
            out_fields.append(field)
    ledger_path = output / "identity_ledger_v2.csv.gz"
    worklist_path = output / "identity_unresolved_worklist_v2.csv.gz"
    write_csv_gz(ledger_path, out_fields, rows)
    write_csv_gz(worklist_path, out_fields, [row for row in rows if row["identity_status"] != "RESOLVED"])

    snapshot_rows = []
    for (fund, effective), snap_counts in sorted(snapshot_counts.items()):
        snapshot_rows.append({
            "fund": fund,
            "holdings_effective_date": effective,
            "identity_target_session": target_by_date[effective],
            "rows": str(sum(snap_counts.values())),
            **{status.lower(): str(snap_counts.get(status, 0)) for status in STATUSES},
        })
    write_csv_gz(
        output / "identity_snapshot_summary_v2.csv.gz",
        ["fund", "holdings_effective_date", "identity_target_session", "rows", "resolved", "ambiguous", "unmatched", "conflict"],
        snapshot_rows,
    )

    blackrock_rows = [row for row in rows if row.get("source_type") == "blackrock_product_data_v2"]
    sec_rows = [row for row in rows if row.get("source_type") == "sec_n-q"]
    summary = {
        "schema": SCHEMA,
        "stage": "IDENTITY_CLOSURE_PRICE_PATH_PASS_2",
        "status": "PASS" if sum(counts.values()) == len(rows) and price_validation_failures == 0 else "FAIL",
        "corpus_id": "r3000-proxy-pit-2006-2026-v1",
        "mode": "HISTORICAL_STATE_PROXY",
        "source_rows": len(rows),
        "fund_snapshots": len(snapshot_counts),
        "resolution_counts": {status: counts.get(status, 0) for status in STATUSES},
        "resolved_fraction": counts.get("RESOLVED", 0) / len(rows),
        "blackrock_rows": len(blackrock_rows),
        "sec_rows": len(sec_rows),
        "methods": {
            "historical_ticker_plus_unit_price": direct,
            "identifier_plus_historical_price_path": path_resolved,
            "identifier_price_path_ambiguous": path_ambiguous,
            "sec_normalized_name_plus_implied_price": sec_exact,
            "sec_broad_name_plus_implied_price": sec_broad,
            "sec_name_price_ambiguous": sec_ambiguous,
        },
        "reported_ticker_price_mismatches": retroactive_ticker_mismatches,
        "price_validation_failures": price_validation_failures,
        "duplicate_security_assignments_within_fund_snapshot": len(duplicates),
        "duplicate_assignment_examples": duplicates[:50],
        "future_session_violations": sum(1 for row in rows if row["identity_target_session"] > row["holdings_effective_date"]),
        "stage_a_parsed_holdings_sha256": sha256_file(stage_a / "parsed_holdings.csv.gz"),
        "stage_a_summary_sha256": sha256_file(stage_a / "summary.json"),
        "canonical_dataset_hash": dataset_hash,
        "canonical_manifest_sha256": sha256_file(manifest_path),
        "identity_ledger_sha256": sha256_file(ledger_path),
        "unresolved_worklist_sha256": sha256_file(worklist_path),
        "acceptance_state": (
            "IDENTITY_CLOSED" if counts.get("RESOLVED", 0) == len(rows) and not duplicates else "OPEN_IDENTITY_WORKLIST"
        ),
        "historical_state_semantics": "Later archival identifier continuity may be used only to reconstruct historical state; every promoted identity must independently match the historical source unit price on the target session.",
        "information_available_semantics": "NOT_CERTIFIED_BY_THIS_STAGE",
        "caveat": CAVEAT,
    }
    summary_path = output / "identity_summary_v2.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(members)),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(close_identity_v2(args.stage_a, args.canonical, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
