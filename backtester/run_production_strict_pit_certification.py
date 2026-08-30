#!/usr/bin/env python3
"""Strict-PIT production LD-RC certification wrapper.

Runs the exact pinned production strategy through the corrected historical warm-up
and cash model while replacing D's current-TICKERS metadata authority with causal
price-tape/SEC authorities. The legacy A side is mechanically retained by the
underlying harness but is not certification evidence here.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, timedelta
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
_anchor_issuer_stats = {
    "anchors": 0,
    "sec_cik": 0,
    "unknown_singleton": 0,
}


def _norm_int(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError, OverflowError):
        return text


class _StrictIssuerAuthority:
    """One causal issuer authority shared by anchors and D session metadata.

    The A/D harness constructs feed anchors before the D publication is rewritten.
    Strict PIT therefore cannot rely on ``SecurityMeta.issuer_key()`` at that
    boundary: those metadata objects intentionally contain neither present-day
    relatedtickers nor permaticker. The historical rule is the same at every
    seam: latest SEC CIK filed strictly before the simulated session, with a
    security-singleton fallback while CIK is unknown.
    """

    def __init__(self, path: Path):
        frame = pd.read_csv(path, compression="gzip", low_memory=False)
        required = {"filing_date", "ticker", "issuer_cik"}
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"SEC CIK evidence missing columns: {sorted(missing)}")
        self.dates: dict[str, list[str]] = {}
        self.values: dict[str, list[str]] = {}
        frame = frame.sort_values(["ticker", "filing_date"], kind="mergesort")
        for ticker, group in frame.groupby("ticker", sort=False):
            ds: list[str] = []
            vs: list[str] = []
            for row in group.itertuples(index=False):
                filed = str(row.filing_date)[:10]
                cik = _norm_int(row.issuer_cik)
                if filed and cik is not None:
                    ds.append(filed)
                    vs.append(cik)
            if ds:
                self.dates[str(ticker)] = ds
                self.values[str(ticker)] = vs

    def strict_prior_cik(self, ticker: str, session: str) -> str | None:
        ticker = str(ticker)
        dates = self.dates.get(ticker, ())
        i = bisect_left(dates, str(session)) - 1
        return self.values[ticker][i] if i >= 0 else None

    def issuer(self, security_id: str, ticker: str, session: str) -> tuple[str, str]:
        cik = self.strict_prior_cik(str(ticker), str(session))
        if cik is None:
            return (
                f"SEC_UNKNOWN:{security_id}",
                "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON",
            )
        return f"SEC_CIK:{cik}", "SEC_CIK_STRICT_PRIOR"

    def first_evidence(self) -> tuple[str, str, str] | None:
        candidates = []
        for ticker, dates in self.dates.items():
            if dates:
                candidates.append((dates[0], ticker, self.values[ticker][0]))
        return min(candidates) if candidates else None


_issuer_authority = _StrictIssuerAuthority(CIK_PATH)


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
    if len(meta) < int(_identity_audit.get("tickers", 0)):
        raise RuntimeError("strict PIT identity map has fewer security IDs than observed tickers")
    print(
        f"[STRICT PIT] causal identities={len(meta):,} tickers={_identity_audit['tickers']:,} "
        f"cik_episode_boundaries={_identity_audit['cik_change_episode_boundaries']:,}",
        flush=True,
    )
    return meta, sectors, resolver, canonical


runner.load_current_metadata = _strict_load_metadata


def _strict_build_anchor_map(
    state,
    bars,
    meta,
    prior_split_factor,
    seen_count,
    main,
):
    """Build restart/pre-chain anchors from the strict causal issuer authority.

    This mirrors the frozen harness's split-anchor logic exactly. The only
    semantic substitution is issuer authority: current Sharadar relatedtickers /
    permaticker are unavailable by design, so the issuer is strict-prior SEC CIK
    or the contractually approved security singleton.
    """
    existing = set((state.feed.get("series") or {}).keys())
    anchors = {}
    FeedAnchor = main["FeedAnchor"]
    for bar in bars:
        sid = str(bar.security_id)
        if sid in existing:
            continue
        m = meta.get(sid)
        if m is None:
            raise RuntimeError(f"bar {sid} has no causal SecurityMeta")
        seen = int(seen_count.get(sid, 0))
        if seen > 0 or m.first_session != bar.session:
            issuer_id, source = _issuer_authority.issuer(
                sid, str(bar.ticker), str(bar.session)
            )
            if not issuer_id:
                raise RuntimeError(f"strict PIT issuer authority returned no issuer for {sid}")
            _anchor_issuer_stats["anchors"] += 1
            if source == "SEC_CIK_STRICT_PRIOR":
                _anchor_issuer_stats["sec_cik"] += 1
            else:
                _anchor_issuer_stats["unknown_singleton"] += 1
            anchors[sid] = FeedAnchor(
                security_id=sid,
                ticker=bar.ticker,
                issuer_id=issuer_id,
                prior_split_factor=float(prior_split_factor.get(sid, 1.0)),
            )
    return anchors


# The harness resolves this global before ``production.advance_state``. Patching
# only ``prod._pit_meta_map`` is too late for returning/pre-chain series.
runner.build_anchor_map = _strict_build_anchor_map


def preflight_strict_boundaries(session: str) -> dict:
    """Exercise the exact pre-chain issuer failure shape without a long replay."""

    @dataclass(frozen=True)
    class _Anchor:
        security_id: str
        ticker: str
        issuer_id: str
        prior_split_factor: float

    @dataclass(frozen=True)
    class _Bar:
        security_id: str
        ticker: str
        session: str

    class _Meta:
        first_session = "1900-01-01"

        def issuer_key(self):
            raise AssertionError("legacy SecurityMeta.issuer_key() reached strict anchor preflight")

    class _State:
        feed = {"series": {}}

    # Reproduce the real failure shape at warm-up start: a pre-chain security
    # whose static current-TICKERS issuer fields have intentionally been removed.
    synthetic_sid = "STRICT-PREFLIGHT-SID"
    synthetic_ticker = "STRICT-PREFLIGHT-UNKNOWN"
    anchors = _strict_build_anchor_map(
        _State(),
        [_Bar(synthetic_sid, synthetic_ticker, str(session))],
        {synthetic_sid: _Meta()},
        {synthetic_sid: 1.25},
        {synthetic_sid: 1},
        {"FeedAnchor": _Anchor},
    )
    anchor = anchors.get(synthetic_sid)
    if anchor is None:
        raise RuntimeError("strict anchor preflight did not create the pre-chain anchor")
    if anchor.issuer_id != f"SEC_UNKNOWN:{synthetic_sid}":
        raise RuntimeError(
            f"strict unknown-issuer anchor mismatch: {anchor.issuer_id!r}"
        )
    if abs(float(anchor.prior_split_factor) - 1.25) > 1e-15:
        raise RuntimeError("strict anchor preflight changed the split-factor basis")

    # The CIK corpus itself begins after the 2006-01-03 warm-up boundary. That is
    # a valid state under the contract: issuer is a singleton until evidence
    # becomes causally available. Verify strict-prior semantics at the corpus's
    # first real filing boundary instead of demanding evidence before it exists.
    first = _issuer_authority.first_evidence()
    if first is None:
        raise RuntimeError("SEC issuer authority contains no usable CIK evidence")
    filed, known_ticker, known_cik = first
    same_day = _issuer_authority.strict_prior_cik(known_ticker, filed)
    if same_day is not None:
        raise RuntimeError(
            f"strict-prior CIK leaked same-day evidence for {known_ticker} on {filed}"
        )
    probe_session = (date.fromisoformat(filed) + timedelta(days=1)).isoformat()
    known_issuer, known_source = _issuer_authority.issuer(
        "STRICT-PREFLIGHT-KNOWN", known_ticker, probe_session
    )
    if known_issuer != f"SEC_CIK:{known_cik}" or known_source != "SEC_CIK_STRICT_PRIOR":
        raise RuntimeError("strict known-issuer preflight disagrees with SEC CIK authority")

    # Keep runtime evidence counters free of synthetic preflight observations.
    for key in _anchor_issuer_stats:
        _anchor_issuer_stats[key] = 0
    result = {
        "session": str(session),
        "unknown_fallback": anchor.issuer_id,
        "first_cik_filing": filed,
        "same_day_cik": same_day,
        "known_probe_session": probe_session,
        "known_example_ticker": known_ticker,
        "known_example_issuer": known_issuer,
        "legacy_issuer_key_reached": False,
        "split_anchor_preserved": True,
    }
    print("[PREFLIGHT PASS] strict pre-chain issuer/anchor boundary " + json.dumps(result, sort_keys=True), flush=True)
    return result


_real_pit_meta_map = prod._pit_meta_map


def _strict_pit_meta_map(pub):
    global _security_authority
    if _security_authority is None:
        _security_authority = SecurityTypeAuthority(
            POSITIVE_TYPE, MANUAL_AUDIT, pub.sectors.model
        )
    result = {}
    for sid, meta in pub.meta.items():
        issuer_id, source = _issuer_authority.issuer(
            str(sid), str(meta.ticker), str(pub.session)
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
    audit["feed_anchor_issuer_authority"] = {
        "authority": "strict-prior SEC CIK; unknown issuer is causal security singleton",
        **{key: int(value) for key, value in _anchor_issuer_stats.items()},
    }
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
