"""Strict research-only overlay for primary-source-adjudicated split ratios."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SCHEMA = "backtester.causal-split-overrides/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FrozenSplitOverrideError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_digest(checksum_path: Path, data_path: Path) -> str:
    rows = [line.strip() for line in checksum_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise FrozenSplitOverrideError("split override checksum must contain exactly one row")
    parts = rows[0].split()
    if len(parts) != 2:
        raise FrozenSplitOverrideError("malformed split override checksum")
    digest, name = parts
    name = name.lstrip("*")
    if not _SHA256.fullmatch(digest) or name != data_path.name:
        raise FrozenSplitOverrideError("invalid split override checksum target/digest")
    return digest


def apply_frozen_split_overrides(
    data_path: Path,
    checksum_path: Path,
    *,
    authority,
    sessions,
    resolve_identity,
) -> tuple[str, tuple[dict, ...]]:
    """Validate and overlay exact multipliers onto a production SplitAuthority.

    The function requires the frozen vendor authority to contain the exact
    disputed value declared in each research record.  This binds every override
    to the expected underlying corpus and prevents a stale adjudication from
    silently changing a different input population.
    """
    expected = _expected_digest(checksum_path, data_path)
    observed = sha256_file(data_path)
    if observed != expected:
        raise FrozenSplitOverrideError(
            f"split override checksum mismatch: {observed} != {expected}")
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise FrozenSplitOverrideError(f"unexpected split override schema: {payload.get('schema')!r}")
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise FrozenSplitOverrideError("split override dataset is empty")

    session_set = set(map(str, sessions))
    seen = set()
    applied = []
    previous = getattr(authority, "previous_session_candidates", None)
    if previous is None:
        raise FrozenSplitOverrideError("split authority lacks previous-session candidate map")

    for raw in records:
        if not isinstance(raw, dict):
            raise FrozenSplitOverrideError("split override record must be an object")
        ticker = str(raw.get("ticker") or "").strip()
        session = str(raw.get("effective_session") or "").strip()
        known_by = str(raw.get("known_by") or "").strip()
        reference = str(raw.get("reference") or "").strip()
        sources = raw.get("sources")
        if not ticker or not session or not known_by or not reference:
            raise FrozenSplitOverrideError("split override lacks required text fields")
        if session not in session_set:
            raise FrozenSplitOverrideError(f"split override {ticker} {session} is off replay axis")
        if known_by > session:
            raise FrozenSplitOverrideError(f"split override {ticker} uses future-known evidence")
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(x, str) or not x.startswith("https://") for x in sources)):
            raise FrozenSplitOverrideError(f"split override {ticker} lacks auditable HTTPS sources")
        try:
            multiplier = float(raw["multiplier"])
            expected_vendor = float(raw["expected_vendor_stated"])
            expected_derived = float(raw["expected_sep_derived"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FrozenSplitOverrideError(f"split override {ticker} has invalid numeric fields") from exc
        if (not math.isfinite(multiplier) or multiplier <= 0
                or not math.isfinite(expected_vendor) or expected_vendor <= 0
                or not math.isfinite(expected_derived) or expected_derived <= 0):
            raise FrozenSplitOverrideError(f"split override {ticker} has non-positive/non-finite economics")
        key = (ticker, session)
        if key in seen:
            raise FrozenSplitOverrideError(f"duplicate split override for {ticker} {session}")
        seen.add(key)
        vendor = authority.get(key)
        if vendor is None or not math.isclose(float(vendor), expected_vendor, rel_tol=0, abs_tol=1e-12):
            raise FrozenSplitOverrideError(
                f"split override vendor witness changed for {ticker} {session}: {vendor!r} != {expected_vendor}")
        sid = resolve_identity(ticker, session)
        if sid is None:
            raise FrozenSplitOverrideError(f"split override identity unresolved for {ticker} {session}")

        authority[key] = multiplier
        for probe, candidate in list(previous.items()):
            event_key, _value = candidate
            if tuple(event_key) == key:
                previous[probe] = (event_key, multiplier)

        applied.append({
            "ticker": ticker,
            "effective_session": session,
            "security_id": str(sid),
            "known_by": known_by,
            "multiplier": multiplier,
            "expected_vendor_stated": expected_vendor,
            "expected_sep_derived": expected_derived,
            "reference": reference,
            "sources": list(sources),
        })

    return observed, tuple(applied)
