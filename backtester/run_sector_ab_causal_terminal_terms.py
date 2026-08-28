#!/usr/bin/env python3
"""Research-side launcher that supplies frozen exact terminal settlement terms.

The strategy implementation remains the exact pinned ``main`` checkout used by
the base A/B runner.  This launcher changes only the historical input stream by
replacing incomplete Sharadar terminal terms with separately frozen, causal,
source-backed terms for the same economic events.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Sequence


def _option_path(flag: str, default: str) -> Path:
    args = sys.argv[1:]
    for index, value in enumerate(args):
        if value == flag and index + 1 < len(args):
            return Path(args[index + 1])
        prefix = flag + "="
        if value.startswith(prefix):
            return Path(value[len(prefix):])
    return Path(default)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


LAB_ROOT = _option_path("--lab-root", os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
MAIN_ROOT = _option_path("--main-root", os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
OUTPUT = _option_path("--output", "backtester-results/sector-ab").resolve()

sys.path.insert(0, str(LAB_ROOT))
sys.path.insert(0, str(MAIN_ROOT / "shared"))
sys.path.insert(0, str(MAIN_ROOT))

from backtester.causal_terminal_terms import (  # noqa: E402
    SCHEMA as TERMINAL_TERMS_SCHEMA,
    load_frozen_terminal_terms,
    merge_terminal_events,
)
from stock_strategy_shared.wealth_core.feed import SecurityMeta  # noqa: E402
from stock_strategy_shared.wealth_core.terminal import (  # noqa: E402
    TerminalKind,
    TerminalTerms,
)

BASE_RUNNER = LAB_ROOT / "backtester" / "experiments" / "2026-08-27-sector-abc" / "run.py"
spec = importlib.util.spec_from_file_location("sector_ab_base_runner", BASE_RUNNER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base A/B runner from {BASE_RUNNER}")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

TERMS_PATH = LAB_ROOT / "backtester" / "data" / "causal-terminal-terms-v1.json"
TERMS_CHECKSUM_PATH = LAB_ROOT / "backtester" / "data" / "causal-terminal-terms-v1.SHA256"

_session_axis: Sequence[str] | None = None
_exact_by_session: dict[str, tuple[object, ...]] | None = None
_terms_digest: str | None = None

_real_build_sfp_levels = runner.build_sfp_levels
_real_build_terminal_events = runner.build_terminal_events


def _capture_session_axis(*args, **kwargs):
    global _session_axis
    result = _real_build_sfp_levels(*args, **kwargs)
    _session_axis = tuple(result[0])
    return result


def _minimal_meta(payload: dict) -> dict[str, SecurityMeta]:
    out: dict[str, SecurityMeta] = {}
    for record in payload.get("records") or []:
        sid = str(record["security_id"])
        out[sid] = SecurityMeta(
            security_id=sid, ticker=str(record["ticker"]),
            permaticker=sid, related_tickers=())
        delivered_sid = record.get("delivered_security_id")
        delivered_ticker = record.get("delivered_ticker")
        if delivered_sid and delivered_ticker:
            delivered_sid = str(delivered_sid)
            out[delivered_sid] = SecurityMeta(
                security_id=delivered_sid, ticker=str(delivered_ticker),
                permaticker=delivered_sid, related_tickers=())
    return out


def _load_exact_terms(resolver) -> dict[str, tuple[object, ...]]:
    global _exact_by_session, _terms_digest
    if _exact_by_session is not None:
        return _exact_by_session
    if _session_axis is None:
        raise RuntimeError("replay session axis was not established before terminal loading")

    payload = json.loads(TERMS_PATH.read_text(encoding="utf-8"))
    phase1 = runner.load_phase1_manifest(LAB_ROOT / "PIT input data" / "MANIFEST.csv")
    for record in payload.get("records") or []:
        witness = record.get("price_witness")
        if not witness:
            continue
        witness_session = str(witness["session"])
        expected_source_hash = runner.source_hash_for_year(
            phase1, int(witness_session[:4]))
        if str(witness.get("source_sep_sha256")) != expected_source_hash:
            raise RuntimeError(
                f"terminal price witness for {record.get('security_id')} is not "
                f"bound to the frozen SEP source")

    _exact_by_session, _terms_digest = load_frozen_terminal_terms(
        TERMS_PATH, TERMS_CHECKSUM_PATH,
        sessions=_session_axis,
        resolve_identity=resolver.resolve,
        meta=_minimal_meta(payload),
        TerminalTerms=TerminalTerms,
        TerminalKind=TerminalKind,
    )
    print(
        f"[RUN] frozen causal terminal terms sha256={_terms_digest}",
        flush=True)
    return _exact_by_session


def _terminal_events_with_exact_terms(
    session: str, rows, priced_tickers, resolver, main,
):
    vendor_events = _real_build_terminal_events(
        session, rows, priced_tickers, resolver, main)
    exact = _load_exact_terms(resolver).get(str(session), ())
    return merge_terminal_events(str(session), vendor_events, exact)


runner.build_sfp_levels = _capture_session_axis
runner.build_terminal_events = _terminal_events_with_exact_terms

# Bounded verification may stop at the original failing session while using the
# same chronological runner and terminal-input seam.  The full Actions replay
# leaves this environment variable unset.
_bounded_end = os.environ.get("BACKTESTER_CAUSAL_END_SESSION")
if _bounded_end:
    runner.END_SESSION = str(_bounded_end)
    runner.MEASUREMENT_WINDOWS = {}


def _postprocess_provenance() -> None:
    if _terms_digest is None or _exact_by_session is None:
        raise RuntimeError("causal terminal terms were never loaded by the replay")
    summary_path = OUTPUT / "summary.json"
    manifest_path = OUTPUT / "manifest.json"
    sums_path = OUTPUT / "SHA256SUMS.txt"
    daily_path = OUTPUT / "daily.csv.gz"
    metrics_path = OUTPUT / "metrics.csv"
    for path in (summary_path, manifest_path, daily_path, metrics_path):
        if not path.exists():
            raise RuntimeError(f"expected replay output is missing: {path}")

    events = []
    for session in sorted(_exact_by_session):
        for terms in _exact_by_session[session]:
            events.append({
                "session": str(terms.session),
                "security_id": str(terms.security_id),
                "kind": terms.kind.value,
            })

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["causal_terminal_terms"] = {
        "schema": TERMINAL_TERMS_SCHEMA,
        "sha256": _terms_digest,
        "events": events,
        "production_type": "stock_strategy_shared.wealth_core.terminal.TerminalTerms",
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inputs = manifest.setdefault("input_files", {})
    for path in (TERMS_PATH, TERMS_CHECKSUM_PATH):
        inputs[str(path.relative_to(LAB_ROOT))] = {
            "sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest["input_files"] = dict(sorted(inputs.items()))
    for path in (daily_path, metrics_path, summary_path):
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": _sha256(path), "bytes": path.stat().st_size}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8")


def main() -> int:
    rc = int(runner.main())
    if rc != 0:
        return rc
    _postprocess_provenance()
    print("[PASS] causal terminal terms are included in replay provenance", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
