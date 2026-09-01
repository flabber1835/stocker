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
import hashlib
import math
import os
from pathlib import Path
import sys

import pandas as pd

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

# The canonical loader constructs exact production feed/terminal types. Bind
# those imports to the pinned checkout before importing the loader; the runner
# performs the same path/commit verification again before replay.
if "--main-root" in sys.argv:
    _main_index = sys.argv.index("--main-root")
    if _main_index + 1 < len(sys.argv):
        sys.path.insert(0, str(Path(sys.argv[_main_index + 1]).resolve()))

from backtester.strict_pit_metadata import (  # noqa: E402
    SecurityTypeAuthority,
    authority_audit,
    build_causal_metadata,
)
from backtester.canonical_pit_dataset import CanonicalPITDataset  # noqa: E402
from backtester.causal_terminal_terms import (  # noqa: E402
    load_frozen_terminal_terms,
)
import backtester.run_ldrc_corrected_warmup_cash as corrected  # noqa: E402
import sentinel.core.production as strategy_production  # noqa: E402
from stock_strategy_shared.wealth_core.feed import SecurityMeta  # noqa: E402
from stock_strategy_shared.wealth_core.terminal import (  # noqa: E402
    TerminalKind,
    TerminalTerms,
)

runner = corrected.runner
prod = corrected.prod
base = corrected.base
LAB_ROOT = corrected.LAB_ROOT
MEASUREMENT_START = corrected.MEASUREMENT_START

CIK_PATH = LAB_ROOT / "research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz"
POSITIVE_TYPE = LAB_ROOT / "PIT input data/SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
MANUAL_AUDIT = LAB_ROOT / "PIT input data/SEC_SECURITY_TYPE_MANUAL_ADMISSION_AUDIT.csv"
TERMINAL_CORRECTIONS = LAB_ROOT / "backtester/data/causal-terminal-terms-v1.json"
TERMINAL_CORRECTIONS_SHA256 = LAB_ROOT / "backtester/data/causal-terminal-terms-v1.SHA256"
CANONICAL_PATH = os.environ.get("CANONICAL_PIT_DATASET")
_canonical = (
    CanonicalPITDataset(
        Path(CANONICAL_PATH),
        expected_start=os.environ.get("CERTIFICATION_WARMUP_START", str(runner.CHAIN_START)),
        expected_end=os.environ.get(
            "CANONICAL_PIT_EXPECTED_END",
            os.environ.get("CERTIFICATION_END_SESSION", str(runner.END_SESSION)),
        ),
    )
    if CANONICAL_PATH else None
)
prod._production_dataset_hash = (
    _canonical.dataset_hash if _canonical is not None else None
)

_identity_audit: dict = (
    dict(_canonical.manifest.get("identity_audit") or {})
    if _canonical is not None else {}
)
_security_authority: SecurityTypeAuthority | None = None
_quarter_ends: set[str] = set()
_anchor_issuer_stats = {
    "anchors": 0,
    "sec_cik": 0,
    "unknown_singleton": 0,
}
_terminal_correction_audit: dict = {}


_canonical_terminal_terms = CanonicalPITDataset.terminal_terms


def _terminal_terms_with_authenticated_corrections(self):
    """Replace only incomplete canonical terminal rows with frozen exact terms."""
    canonical = {
        str(session): list(rows)
        for session, rows in _canonical_terminal_terms(self).items()
    }
    meta, _sectors, resolver, _tickers = self.base_metadata(SecurityMeta)

    def delivered_issuer(security_id: str, _ticker: str, session: str):
        row = self.metadata_for(str(security_id), str(session))
        if row is None:
            return None, None
        return row.get("issuer_id") or None, row.get("issuer_source") or None

    corrections, correction_hash = load_frozen_terminal_terms(
        TERMINAL_CORRECTIONS,
        TERMINAL_CORRECTIONS_SHA256,
        sessions=self.sessions,
        resolve_identity=resolver.resolve,
        meta=meta,
        TerminalTerms=TerminalTerms,
        TerminalKind=TerminalKind,
        identity_binding="resolved",
        delivered_issuer_resolver=delivered_issuer,
    )
    applied = []
    for session, candidates in sorted(corrections.items()):
        rows = canonical.get(str(session), [])
        by_security = {
            str(term.security_id): index for index, term in enumerate(rows)
        }
        for replacement in candidates:
            sid = str(replacement.security_id)
            index = by_security.get(sid)
            if index is None:
                continue
            complete, reason = rows[index].completeness(1)
            if complete:
                continue
            replacement_complete, replacement_reason = replacement.completeness(1)
            if not replacement_complete:
                raise RuntimeError(
                    f"terminal correction remains incomplete for {sid} {session}: "
                    f"{replacement_reason}"
                )
            original = rows[index]
            rows[index] = replacement
            applied.append({
                "session": str(session),
                "security_id": sid,
                "ticker": "PHRM",
                "original_kind": str(original.kind.value),
                "original_incomplete_reason": str(reason),
                "corrected_kind": str(replacement.kind.value),
                "reference": str(replacement.reference),
            })
        canonical[str(session)] = rows
    expected = [{
        "session": "2008-03-07",
        "security_id": "705177744622024105",
        "original_kind": "CASH_MERGER",
        "original_incomplete_reason": "MISSING_CASH_PER_SHARE",
        "corrected_kind": "CASH_PLUS_STOCK",
    }]
    observed = [
        {key: row[key] for key in expected[0]}
        for row in applied
    ]
    if observed != expected:
        raise RuntimeError(
            "authenticated terminal correction set changed: "
            + json.dumps(observed, sort_keys=True)
        )
    _terminal_correction_audit.clear()
    _terminal_correction_audit.update({
        "schema": "backtester.production-terminal-corrections/1",
        "source_sha256": correction_hash,
        "applied": applied,
    })
    print(
        "[TERMINAL CORRECTION] role=Production applied="
        f"{len(applied)} source_sha256={correction_hash}",
        flush=True,
    )
    return {
        session: tuple(sorted(rows, key=lambda term: str(term.security_id)))
        for session, rows in sorted(canonical.items())
    }


if _canonical is not None:
    CanonicalPITDataset.terminal_terms = _terminal_terms_with_authenticated_corrections


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


_issuer_authority = None if _canonical is not None else _StrictIssuerAuthority(CIK_PATH)


def _strict_load_metadata(_tickers_path, main):
    global _identity_audit
    if _canonical is not None:
        result = _canonical.base_metadata(main["SecurityMeta"])
        _identity_audit = dict(_canonical.manifest.get("identity_audit") or {})
        print(
            f"[STRICT PIT] canonical identities={len(result[0]):,} "
            f"dataset_hash={_canonical.dataset_hash}",
            flush=True,
        )
        return result
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
            if _canonical is not None:
                row = _canonical.metadata_for(sid, str(bar.session))
                issuer_id = (
                    f"SEC_UNKNOWN:{sid}" if row is None else str(row["issuer_id"])
                )
                source = (
                    "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON"
                    if row is None else str(row["issuer_source"])
                )
            else:
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
    if _canonical is not None:
        for key in _anchor_issuer_stats:
            _anchor_issuer_stats[key] = 0
        result = {
            "session": str(session),
            "canonical_dataset_hash": _canonical.dataset_hash,
            "legacy_issuer_key_reached": False,
            "split_anchor_preserved": True,
        }
        print(
            "[PREFLIGHT PASS] canonical PIT dataset boundary "
            + json.dumps(result, sort_keys=True), flush=True,
        )
        return result
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
    if _canonical is not None:
        result = {}
        for sid, meta in pub.meta.items():
            row = _canonical.metadata_for(str(sid), str(pub.session))
            classification = None if row is None else row["security_type"]
            category = (
                "SEC Common Stock" if classification == "common" else
                "SEC Non-Common" if classification == "non_common" else None
            )
            issuer_id = (
                f"SEC_UNKNOWN:{sid}" if row is None else str(row["issuer_id"])
            )
            issuer_source = (
                "SEC_STRICT_PRIOR_UNKNOWN_SINGLETON"
                if row is None else str(row["issuer_source"])
            )
            result[str(sid)] = prod._PitSecurityMeta(
                security_id=str(sid), ticker=str(meta.ticker), category=category,
                permaticker=None, related_tickers=(),
                first_session=meta.first_session, last_session=None,
                exchange=None, exchange_authoritative=False,
                pit_issuer_id=issuer_id, pit_issuer_source=issuer_source,
            )
        return result
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

_real_plan_session = strategy_production.plan_session
strategy_production._certification_strategy_boundary = {}


def _plan_session_with_boundary_evidence(*args, **kwargs):
    plan = _real_plan_session(*args, **kwargs)
    def ranking_key(row):
        score = float(row.score) if row.score is not None else float("nan")
        return (
            0 if math.isfinite(score) else 1,
            -score if math.isfinite(score) else 0.0,
            str(row.security_id),
            str(row.ticker),
        )
    ranked = sorted(
        (row for row in plan.leadership_candidates if row.in_top_decile),
        key=ranking_key,
    )
    rank_ids = [str(row.security_id) for row in ranked]
    state_after = plan.state_after or {}
    positions = sorted(
        str(row.get("security_id"))
        for row in (state_after.get("episodes") or {}).values()
        if row.get("security_id")
    )
    blob = json.dumps(rank_ids, separators=(",", ":"))
    strategy_production._certification_strategy_boundary[str(plan.session)] = {
        "eligible_universe": int(plan.eligible_universe_count),
        "ranking_sha256": hashlib.sha256(blob.encode()).hexdigest(),
        "ranking_count": len(rank_ids),
        "selected_positions": positions,
        "selected_positions_sha256": hashlib.sha256(
            json.dumps(positions, separators=(",", ":")).encode()
        ).hexdigest(),
        "intents": [intent.to_dict() for intent in plan.intents],
    }
    return plan


strategy_production.plan_session = _plan_session_with_boundary_evidence

_real_build_levels = runner.build_sfp_levels


def _build_levels_with_quarters(*args, **kwargs):
    if _canonical is None:
        result = _real_build_levels(*args, **kwargs)
    else:
        spy_level, spy_return = _canonical.benchmark()
        result = (
            list(_canonical.sessions), spy_level, spy_return,
            _canonical.cash_factors(),
        )
    sessions = [str(x) for x in result[0]]
    _quarter_ends.clear()
    _quarter_ends.update(prod._calendar_checkpoint_sessions(
        sessions,
        MEASUREMENT_START,
        str(runner.END_SESSION),
    ))
    # The corrected wrapper's historical comparison checkpoints expose legacy
    # account labels. Strict Production reporting owns this output instead.
    prod._year_end_sessions.clear()
    return result


runner.build_sfp_levels = _build_levels_with_quarters

if _canonical is not None:
    runner.PITFF12 = lambda *_args, **_kwargs: _canonical

    def _canonical_actions(_path, _sessions, _main):
        return [], {}, {"dividends": {}, "terminal": {}}

    runner.load_actions = _canonical_actions

_real_step = runner.OverlayAccount.step


def _step_with_certification_checkpoint(self, *args, **kwargs):
    is_production = str(self.name) == "B"
    before_progress = (
        int(getattr(base, "_progress_sessions", -1)) if is_production else None
    )
    if is_production and before_progress < 0:
        raise RuntimeError("Production progress owner is unavailable before account step")
    nav = _real_step(self, *args, **kwargs)
    session = str(base._current_session or "")
    if is_production:
        progress_sessions = int(getattr(base, "_progress_sessions", -1))
        if progress_sessions != before_progress + 1:
            raise RuntimeError(
                "Production progress owner must advance exactly once per canonical session: "
                f"before={before_progress} after={progress_sessions} session={session}"
            )
    if is_production and session in _quarter_ends and session >= MEASUREMENT_START:
        cagr = prod._measurement_cagr(float(self.nav), MEASUREMENT_START, session)
        print(
            f"[PROGRESS] role=Production session={session} "
            f"sessions={progress_sessions} "
            f"measurement_start={MEASUREMENT_START} "
            f"multiple={float(self.nav):.12f} cumulative_cagr={cagr:.10%}",
            flush=True,
        )
    return nav


runner.OverlayAccount.step = _step_with_certification_checkpoint


def _rewrite_bundle_with_audit() -> None:
    if (_canonical is None and _security_authority is None) or not _identity_audit:
        raise RuntimeError("strict PIT metadata authorities were not exercised")
    security_type_audit = (
        dict(_canonical.manifest.get("security_type_audit") or {})
        if _canonical is not None else _security_authority.audit()
    )
    output = base.OUTPUT
    audit = authority_audit(
        identity=_identity_audit,
        security_type=security_type_audit,
    )
    audit["role"] = "Production"
    if _canonical is not None:
        if not _terminal_correction_audit:
            raise RuntimeError("Production terminal correction was not exercised")
        audit["terminal_term_corrections"] = dict(_terminal_correction_audit)
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
    summary["canonical_pit_dataset_hash"] = (
        _canonical.dataset_hash if _canonical is not None else None
    )
    summary["metadata_authority_audit"] = audit
    summary["pit_authority"]["residual_non_pit_fields"] = []
    summary["pit_authority"]["residual_note"] = None
    summary["comparison_contract"]["Production"] = (
        "strict causal PIT Production: historical price-tape identity/listing, strict-prior SEC CIK/SIC/FF12, "
        "strict-prior SEC/EDGAR security type, PIT actions, causal terminal terms, and causal cash"
    )
    summary["comparison_contract"].pop("D", None)
    summary.pop("calendar_year_cagr_checkpoints", None)
    summary.pop("calendar_year_cagr_definition", None)
    summary["cumulative_production_cagr_checkpoints"] = sorted(_quarter_ends)
    summary["cumulative_production_cagr_definition"] = (
        f"Production NAV reset to 1.0 after {MEASUREMENT_START} is processed, "
        "then annualized through each displayed checkpoint by elapsed calendar days"
    )
    if any(
        key in summary
        for key in ("calendar_year_cagr_checkpoints", "calendar_year_cagr_definition")
    ):
        raise RuntimeError("legacy CAGR reporting fields survived Production finalization")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    session_hash_path = None
    if _canonical is not None:
        session_hash_path = output / "canonical_input_session_hashes.csv"
        session_hash_path.write_text(
            (_canonical.root / "session-hashes.csv").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["strict_pit_metadata"] = True
    manifest["current_SHARADAR_TICKERS_economically_active_fields"] = []
    manifest["public_variants"] = ["Production", "SPY"]
    manifest["internal_account_labels_exposed"] = False
    public_outputs = [
        output / "daily.csv.gz", output / "metrics.csv", summary_path, audit_path
    ]
    if session_hash_path is not None:
        public_outputs.append(session_hash_path)
    for path in public_outputs:
        manifest.setdefault("outputs", {})[path.name] = {
            "sha256": base._sha256(path), "bytes": path.stat().st_size,
        }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path, manifest_path, audit_path]
    if session_hash_path is not None:
        files.append(session_hash_path)
    sums_path.write_text(
        "".join(f"{base._sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )

    if audit["current_SHARADAR_TICKERS_economically_active_fields"]:
        raise RuntimeError("Production retained current SHARADAR_TICKERS authority")


def _initialize_reporting_checkpoints() -> None:
    """Populate live CAGR checkpoints even when canonical loading bypasses SFP."""
    prod._production_measurement_start = MEASUREMENT_START
    prod._year_end_sessions.clear()
    if _canonical is None:
        return
    _quarter_ends.clear()
    _quarter_ends.update(prod._calendar_checkpoint_sessions(
        _canonical.sessions,
        MEASUREMENT_START,
        str(runner.END_SESSION),
    ))
    if not _quarter_ends:
        raise RuntimeError("canonical Production session axis has no reporting checkpoints")
    print(
        f"[RUN] Production cumulative CAGR checkpoints={len(_quarter_ends)} "
        f"measurement_start={MEASUREMENT_START} end={runner.END_SESSION}",
        flush=True,
    )


def main() -> int:
    print("[RUN] strict-PIT Production certification", flush=True)
    _initialize_reporting_checkpoints()
    rc = int(corrected.main())
    if rc != 0:
        return rc
    _rewrite_bundle_with_audit()
    print("[PASS] strict-PIT Production certification bundle complete", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
