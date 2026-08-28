"""Strict research-only overlay for primary-source-adjudicated split ratios."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SCHEMA = "backtester.causal-split-overrides/1"
ADJUDICATED_DISPOSITION = "research_primary_source_adjudicated"
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


def load_frozen_split_overrides(
    data_path: Path,
    checksum_path: Path,
    *,
    authority,
    sessions,
    resolve_identity,
) -> tuple[str, dict[tuple[str, str], dict]]:
    """Validate exact adjudications against the unchanged vendor authority.

    The original ACTIONS value is deliberately retained in ``authority``.  The
    adjudication wrapper records that vendor value and the independent SEP
    witness, then substitutes the legal multiplier only for the exact frozen
    event.  This keeps the disagreement visible in evidence.
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
    out: dict[tuple[str, str], dict] = {}
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
        if key in out:
            raise FrozenSplitOverrideError(f"duplicate split override for {ticker} {session}")
        vendor = authority.get(key)
        if vendor is None or not math.isclose(float(vendor), expected_vendor, rel_tol=0, abs_tol=1e-12):
            raise FrozenSplitOverrideError(
                f"split override vendor witness changed for {ticker} {session}: {vendor!r} != {expected_vendor}")
        sid = resolve_identity(ticker, session)
        if sid is None:
            raise FrozenSplitOverrideError(f"split override identity unresolved for {ticker} {session}")
        out[key] = {
            "ticker": ticker,
            "effective_session": session,
            "security_id": str(sid),
            "known_by": known_by,
            "multiplier": multiplier,
            "expected_vendor_stated": expected_vendor,
            "expected_sep_derived": expected_derived,
            "reference": reference,
            "sources": list(sources),
        }
    return observed, out


def install_primary_split_adjudication(split_module, overrides: dict[tuple[str, str], dict]):
    """Install a bounded wrapper around frozen-main SplitStreamReconciler.decide.

    Every ordinary event still executes the exact production resolver.  For a
    frozen override key, the production result must expose the exact expected
    vendor value and SEP-derived witness.  Only then is the legal multiplier
    returned with a distinct research disposition.  Any corpus drift fails.
    """
    real_decide = split_module.SplitStreamReconciler.decide
    SplitDecision = split_module.SplitDecision

    def adjudicated_decide(self, key, **kwargs):
        decision = real_decide(self, key, **kwargs)
        row = overrides.get((str(key[0]), str(key[1])))
        if row is None:
            return decision
        stated = decision.stated
        derived = decision.derived
        if stated is None or not math.isclose(
                float(stated), float(row["expected_vendor_stated"]),
                rel_tol=0, abs_tol=1e-12):
            raise FrozenSplitOverrideError(
                f"runtime vendor split witness changed for {key}: {stated!r}")
        if derived is None or not math.isclose(
                float(derived), float(row["expected_sep_derived"]),
                rel_tol=1e-9, abs_tol=1e-12):
            raise FrozenSplitOverrideError(
                f"runtime SEP split witness changed for {key}: {derived!r}")
        return SplitDecision(
            ratio=float(row["multiplier"]),
            disposition=ADJUDICATED_DISPOSITION,
            stated=float(stated),
            derived=float(derived),
            prior_key=decision.prior_key,
            prior_disposition=decision.prior_disposition,
        )

    split_module.SplitStreamReconciler.decide = adjudicated_decide
    return real_decide
