#!/usr/bin/env python3
"""Strict-PIT production certification on the agreed 20-year window."""
from __future__ import annotations

import builtins
import json
import math
import os
from pathlib import Path
import sys

# This file is executed as a script by the parallel orchestrator.  Python then
# puts ``.../backtester`` on sys.path, not the repository root, so importing the
# ``backtester`` package must not depend on an inherited PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

import backtester.run_production_strict_pit_certification as strict
from backtester import causal_split_overrides as split_overrides

WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
FULL_END_SESSION = "2026-07-31"
END_SESSION = os.environ.get("CERTIFICATION_END_SESSION", FULL_END_SESSION)

strict.corrected.WARMUP_START = WARMUP_START
strict.corrected.MEASUREMENT_START = MEASUREMENT_START
strict.corrected.runner.CHAIN_START = WARMUP_START
strict.corrected.runner.END_SESSION = END_SESSION
strict.corrected.runner.EXPERIMENT_ID = "2026-08-30-strict-pit-20y-production"
strict.runner.CHAIN_START = WARMUP_START
strict.runner.END_SESSION = END_SESSION
strict.MEASUREMENT_START = MEASUREMENT_START


def _corrected_contract_print(*args, **kwargs):
    if args and args[0] == (
        "[RUN] corrected production replay: 1997 full-machine warm-up + causal historical cash"
    ):
        args = (
            f"[RUN] corrected production replay: warmup={WARMUP_START} "
            f"measurement={MEASUREMENT_START} + causal historical cash",
            *args[1:],
        )
    return builtins.print(*args, **kwargs)


strict.corrected.print = _corrected_contract_print
_original_measurement_factor_builder = strict.corrected._original_sfp_builder


def _measurement_anchored_factor_builder(path):
    saved = strict.runner.CHAIN_START
    strict.runner.CHAIN_START = MEASUREMENT_START
    try:
        return _original_measurement_factor_builder(path)
    finally:
        strict.runner.CHAIN_START = saved


strict.corrected._original_sfp_builder = _measurement_anchored_factor_builder
_original_terminal_loader = strict.base.load_frozen_terminal_terms


def _causal_identity_terminal_loader(*args, **kwargs):
    kwargs["identity_binding"] = "resolved"
    return _original_terminal_loader(*args, **kwargs)


strict.base.load_frozen_terminal_terms = _causal_identity_terminal_loader
if strict.base.BOUNDARY_SESSION < WARMUP_START:
    strict.base.BOUNDARY_SESSION = "9999-12-31"
if END_SESSION != FULL_END_SESSION:
    strict.runner.MEASUREMENT_WINDOWS = {1: MEASUREMENT_START}


def _active_split_adjudications() -> dict[tuple[str, str], dict]:
    data_path = ROOT / "backtester" / "data" / "causal-split-overrides-v1.json"
    checksum_path = ROOT / "backtester" / "data" / "causal-split-overrides-v1.SHA256"
    expected = split_overrides._expected_digest(checksum_path, data_path)
    observed = split_overrides.sha256_file(data_path)
    if observed != expected:
        raise split_overrides.FrozenSplitOverrideError(
            f"split override checksum mismatch: {observed} != {expected}"
        )
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if payload.get("schema") != split_overrides.SCHEMA:
        raise split_overrides.FrozenSplitOverrideError("unexpected split override schema")
    records = list(payload.get("records") or [])
    sidecars, _witnesses = split_overrides._load_sidecar_records(data_path)
    records.extend(sidecars)
    active: dict[tuple[str, str], dict] = {}
    for raw in records:
        ticker = str(raw.get("ticker") or "").strip()
        session = str(raw.get("effective_session") or "").strip()
        if not ticker or not session or session < WARMUP_START or session > END_SESSION:
            continue
        known_by = str(raw.get("known_by") or "").strip()
        sources = raw.get("sources")
        if not known_by or known_by > session:
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} uses future-known evidence"
            )
        if (not isinstance(sources, list) or not sources
                or any(not isinstance(x, str) or not x.startswith("https://") for x in sources)):
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} lacks auditable HTTPS sources"
            )
        try:
            multiplier = float(raw["multiplier"])
            expected_vendor = float(raw["expected_vendor_stated"])
            expected_derived = float(raw["expected_sep_derived"])
        except (KeyError, TypeError, ValueError) as exc:
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} has invalid numeric fields"
            ) from exc
        if any(not math.isfinite(x) or x <= 0 for x in (multiplier, expected_vendor, expected_derived)):
            raise split_overrides.FrozenSplitOverrideError(
                f"split override {ticker} has non-positive/non-finite economics"
            )
        key = (ticker, session)
        if key in active:
            raise split_overrides.FrozenSplitOverrideError(
                f"duplicate split override for {ticker} {session}"
            )
        active[key] = dict(raw)
    return active


def _install_split_adjudications() -> None:
    active = _active_split_adjudications()
    if not active:
        print("[SPLIT ADJUDICATION] active=0", flush=True)
        return
    import stock_strategy_shared.split_reconciliation as canonical_split
    split_overrides.install_primary_split_adjudication(canonical_split, active)
    print(
        "[SPLIT ADJUDICATION] active=" + str(len(active)) + " keys="
        + ",".join(f"{t}:{s}" for t, s in sorted(active)),
        flush=True,
    )


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        print(
            f"[SELFTEST PASS] production 20y entrypoint root={ROOT} "
            f"backtester_import={Path(strict.__file__).resolve()}",
            flush=True,
        )
        return 0
    print(
        f"[CONTRACT] role=production warmup={WARMUP_START} "
        f"measurement={MEASUREMENT_START} end={END_SESSION}",
        flush=True,
    )
    _install_split_adjudications()
    return int(strict.main())


if __name__ == "__main__":
    raise SystemExit(main())
