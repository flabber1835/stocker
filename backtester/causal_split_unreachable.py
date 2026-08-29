"""Frozen research-only proof that selected raw split conflicts are economically unreachable."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA = "backtester.causal-split-unreachable/1"
EXPECTED_MAIN_SHA = "c502d077cae9c494f8b74a41ee8be7f40b25837d"
EXPECTED_PROOF_RULE = {
    "adjusted_price_used": False,
    "category_used": False,
    "contamination_future_sessions": 126,
    "exchange_used": False,
    "min_adv20_dollars": 20_000_000.0,
    "min_signal_dollar_volume": 5_000_000.0,
    "min_unadjusted_price": 1.0,
    "required_contiguous_closes": 127,
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen_unreachable(data_path: Path, checksum_path: Path, *, resolve_identity):
    parts = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(parts) != 2 or parts[1].lstrip("*") != data_path.name:
        raise RuntimeError("invalid unreachable split checksum record")
    observed = sha256_file(data_path)
    if observed != parts[0]:
        raise RuntimeError(f"unreachable split proof checksum mismatch: {observed} != {parts[0]}")
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise RuntimeError("unexpected unreachable split proof schema")
    if payload.get("strategy_main_sha") != EXPECTED_MAIN_SHA:
        raise RuntimeError("unreachable split proof is bound to wrong strategy main")
    if payload.get("proof_rule") != EXPECTED_PROOF_RULE:
        raise RuntimeError("unreachable split proof rule drift")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 50:
        raise RuntimeError(f"unreachable split proof must contain exactly 50 records: {len(records or [])}")
    out = {}
    for row in records:
        key = (str(row["ticker"]), str(row["session"]))
        if key in out:
            raise RuntimeError(f"duplicate unreachable split proof: {key}")
        sid = resolve_identity(*key)
        if sid is None or str(sid) != str(row["security_id"]):
            raise RuntimeError(f"unreachable split identity drift for {key}: {sid} != {row['security_id']}")
        out[key] = dict(row)
    return observed, out
