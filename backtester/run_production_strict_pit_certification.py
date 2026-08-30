#!/usr/bin/env python3
"""Strict-PIT production LD-RC certification wrapper.

Runs the exact pinned production strategy through the corrected 1997 warm-up and
historical cash model while replacing D's current-TICKERS metadata authority with
causal price-tape/SEC authorities.  The legacy A side is mechanically retained by
the underlying harness but is not certification evidence here.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import sys

import pandas as pd

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

from backtester.strict_pit_metadata import (  # noqa: E402
    SecurityTypeAuthority,
    authority_audit,
    build_causal_metadata,
)
import backtester.run_ldrc_corrected_warmup_cash as corrected  # noqa: E402

runner = corrected.runner
prod = corrected.prod
base = corrected.base
LAB_ROOT = corrected.LAB_ROOT
MEASUREMENT_START = corrected.MEASUREMENT_START

CIK_PATH = LAB_ROOT / "research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz"
POSITIVE_TYPE = LAB_ROOT / "PIT input data/SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
MANUAL_AUDIT = LAB_ROOT / "PIT input data/SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv"

_identity_audit: dict = {}
_security_authority: SecurityTypeAuthority | None = None
_quarter_ends: set[str] = set()


def _strict_load_metadata(_tickers_path, main):
    global _identity_audit
    result = build_causal_metadata(
        sharadar_root=LAB_ROOT / "sharadar",
        cik_path=CIK_PATH,
        SecurityMeta=main["SecurityMeta"],
        start_year=1997,
        end_year=int(str(runner.END_SESSION)[:4]),
    )
    meta, sectors, resolver, canonical, _identity_audit = result
    print(
        f"[STRICT PIT] causal identities={len(meta):,} tickers={_identity_audit['tickers']:,} "
        f"cik_episode_boundaries={_identity_audit['cik_change_episode_boundaries']:,}",
        flush=True,
    )
    return meta, sectors, resolver, canonical


runner.load_current_metadata = _strict_load_metadata

_real_pit_meta_map = prod._pit_meta_map


def _strict_pit_meta_map(pub):
    global _security_authority
    if _security_authority is None:
        _security_authority = SecurityTypeAuthority(
            POSITIVE_TYPE, MANUAL_AUDIT, pub.sectors.model
        )
    result = {}
    for sid, meta in pub.meta.items():
        issuer_id, source = prod._strict_prior_cik(
            pub.sectors, str(sid), meta, str(pub.session)
        )
        prod._pit_metadata_observations += 1
        if source == "SEC_CIK_STRICT_PRIOR":
            prod._pit_sec_cik_observations += 1
        result[str(sid)] = prod._PitSecurityMeta(
            security_id=str(sid),
            ticker=str(meta.ticker),
            category=_security_authority.category(str(meta.ticker), str(pub.session)),
            permaticker=None,
            related_tickers=(),
            first_session=meta.first_session,
            last_session=None,
            exchange=None,
            exchange_authoritative=False,
            pit_issuer_id=issuer_id,
            pit_issuer_source=source,
        )
    return result


prod._pit_meta_map = _strict_pit_meta_map

_real_build_levels = runner.build_sfp_levels


def _build_levels_with_quarters(*args, **kwargs):
    result = _real_build_levels(*args, **kwargs)
    sessions = [str(x) for x in result[0]]
    _quarter_ends.clear()
    for i, session in enumerate(sessions):
        if session < MEASUREMENT_START:
            continue
        current_q = (int(session[:4]), (int(session[5:7]) - 1) // 3)
        if i + 1 == len(sessions):
            _quarter_ends.add(session)
        else:
            nxt = sessions[i + 1]
            next_q = (int(nxt[:4]), (int(nxt[5:7]) - 1) // 3)
            if next_q != current_q:
                _quarter_ends.add(session)
    return result


runner.build_sfp_levels = _build_levels_with_quarters

_real_step = runner.OverlayAccount.step


def _step_with_certification_checkpoint(self, *args, **kwargs):
    nav = _real_step(self, *args, **kwargs)
    session = str(base._current_session or "")
    if str(self.name) == "B" and session in _quarter_ends and session >= MEASUREMENT_START:
        elapsed = (date.fromisoformat(session) - date.fromisoformat(MEASUREMENT_START)).days / 365.2425
        cagr = 0.0 if elapsed <= 0 else float(self.nav) ** (1.0 / elapsed) - 1.0
        print(
            f"[CERT_CAGR] role=production date={session} cagr={cagr:.12f}",
            flush=True,
        )
    return nav


runner.OverlayAccount.step = _step_with_certification_checkpoint


def _rewrite_bundle_with_audit() -> None:
    if _security_authority is None or not _identity_audit:
        raise RuntimeError("strict PIT metadata authorities were not exercised")
    output = base.OUTPUT
    audit = authority_audit(
        identity=_identity_audit,
        security_type=_security_authority.audit(),
    )
    audit["role"] = "production"
    audit_path = output / "metadata_authority_audit.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    sums_path = output / "SHA256SUMS.txt"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["strict_pit_metadata"] = True
    summary["metadata_authority_audit"] = audit
    summary["pit_authority"]["residual_non_pit_fields"] = []
    summary["pit_authority"]["residual_note"] = None
    summary["comparison_contract"]["D"] = (
        "strict-D causal PIT: historical price-tape identity/listing, strict-prior SEC CIK/SIC/FF12, "
        "strict-prior SEC/EDGAR security type, PIT actions, causal terminal terms, and causal cash"
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["strict_pit_metadata"] = True
    manifest["current_SHARADAR_TICKERS_economically_active_fields"] = []
    for path in (summary_path, audit_path):
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": base._sha256(path), "bytes": path.stat().st_size,
        }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path, manifest_path, audit_path]
    sums_path.write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    # Mechanical hard fail: the strict audit must prove no current-TICKERS field
    # is economically active on D.
    if audit["current_SHARADAR_TICKERS_economically_active_fields"]:
        raise RuntimeError("strict D retained current SHARADAR_TICKERS authority")


def main() -> int:
    print("[RUN] strict-PIT production certification", flush=True)
    rc = int(corrected.main())
    if rc != 0:
        return rc
    _rewrite_bundle_with_audit()
    print("[PASS] strict-PIT production certification bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
