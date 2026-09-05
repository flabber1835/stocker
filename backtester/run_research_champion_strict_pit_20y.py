#!/usr/bin/env python3
"""Formal PIT-certified 20-year replay entrypoint for Research Champion v1.

The Research Champion is the stability-selected Strategy 9 + E3 center:
REC=8, R20=-8.5%, V=11%, DD=-10%, SPY divergence floor=0,
full-recovery r40 floor=0, FAST damaged=88%, healthy damaged ceiling=63%.

Composition order is deliberate:
1. build the Champion mechanics on the retained research source;
2. promote E3 Candidate A into the authoritative research/control path;
3. apply the repository's existing strict-PIT + canonical-data transform;
4. apply the existing 20-year financial-grade transform.

This preserves the official certification contract while ensuring the path called
``research_nav`` is the Champion, not the historical A/B control.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys

import pandas as pd

# Import the strict layer first. It captures the original retained transform and
# installs strict.old.transformed_source = strict._strict_transform.
from backtester import run_research_strict_pit_certification as strict

# Preserve the pre-strict transforms before the 20-year wrapper is imported.
_PRE_STRICT_CORRECTED_TRANSFORM = strict.corrected.transformed_source
_PRE_STRICT_RETAINED_TRANSFORM = strict._original_transform

from backtester import run_strategy9_e3_stability_point as stability  # noqa: E402

PROFILE = "strategy9-e3-research-champion-v1"
CENTER = SimpleNamespace(
    ldrc_rec=8,
    ldrc_v=0.11,
    ldrc_dd=-0.10,
    ldrc_r20=-0.085,
    div_spy_floor=0.0,
    full_r40_floor=0.0,
    fast_damaged=0.880,
    healthy_damaged=0.630,
)
CONFIG = {
    "profile": PROFILE,
    "ldrc_rec": CENTER.ldrc_rec,
    "ldrc_v": CENTER.ldrc_v,
    "ldrc_dd": CENTER.ldrc_dd,
    "ldrc_r20": CENTER.ldrc_r20,
    "div_spy_floor": CENTER.div_spy_floor,
    "full_r40_floor": CENTER.full_r40_floor,
    "fast_damaged": CENTER.fast_damaged,
    "healthy_damaged": CENTER.healthy_damaged,
}
PROFILE_SHA256 = hashlib.sha256(
    json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def _champion_pre_strict(mode: str, output: Path) -> str:
    """Build Champion mechanics from the retained pre-strict research source."""
    if mode != "fullpit":
        return _PRE_STRICT_RETAINED_TRANSFORM(mode, output)

    prior_old = strict.old.transformed_source
    prior_corrected = strict.corrected.transformed_source
    # The stability transforms were written against the retained research source.
    # Temporarily expose that source only while generating the Champion text.
    strict.old.transformed_source = _PRE_STRICT_RETAINED_TRANSFORM
    strict.corrected.transformed_source = _PRE_STRICT_CORRECTED_TRANSFORM
    try:
        text = stability.build_source(output, CENTER)
    finally:
        strict.old.transformed_source = prior_old
        strict.corrected.transformed_source = prior_corrected

    # The canonical strict transform expects a PIT-model seam. Experiment 2
    # deliberately removed that legacy metadata model; restore only the marker
    # so the canonical transform can replace the authority block. The singleton
    # issuer semantics are re-applied after canonicalization below.
    text = strict.old.replace_once(
        text,
        "    def sector_key(tid, ds):\n",
        "    pit_model=None\n    def sector_key(tid, ds):\n",
        "Research Champion canonical authority marker",
    )

    # Candidate A is the selected Champion. Promote it into the authoritative
    # control/research economics before strict-PIT/canonical transforms run.
    text = strict.old.replace_once(
        text,
        "pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d",
        "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d",
        "Research Champion authoritative allocation promotion",
    )
    text = strict.old.replace_once(
        text,
        "'control_reason':ctl_reason,'A_reason':a_reason,'B_reason':b_reason",
        "'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason",
        "Research Champion authoritative reason promotion",
    )
    return text


# Strict-PIT must consume the Champion source, not the historical retained control.
strict._original_transform = _champion_pre_strict

# Importing the 20-year wrapper now captures corrected.transformed_source with
# strict._strict_transform already pointing at _champion_pre_strict.
from backtester import run_research_strict_pit_20y as strict20  # noqa: E402

_STRICT20_TRANSFORM = strict20.corrected.transformed_source


def _champion_strict20_transform(mode: str, output: Path) -> str:
    text = _STRICT20_TRANSFORM(mode, output)
    if os.environ.get("CANONICAL_PIT_DATASET"):
        # Canonicalization restores PIT issuer/sector functions for the ordinary
        # retained strategy. Research Champion deliberately treats every security
        # as its own issuer and uses residual-correlation peers for contagion.
        canonical_authority = """    def _metadata(tid,ds): return _CANONICAL.metadata_for(str(sid[int(tid)]),str(ds)[:10])
    def sector_key(tid,ds):
        row=_metadata(tid,ds); return f'UNKNOWN:{sid[int(tid)]}' if row is None else str(row['ff12'])
    def issuer_key(tid,ds):
        row=_metadata(tid,ds); return f'SEC_UNKNOWN:{sid[int(tid)]}' if row is None else str(row['issuer_id'])
"""
        champion_authority = """    def _metadata(tid,ds): return _CANONICAL.metadata_for(str(sid[int(tid)]),str(ds)[:10])
    def sector_key(tid,ds):
        return f'SID:{sid[int(tid)]}'
    def issuer_key(tid,ds):
        return f'SID:{sid[int(tid)]}'
"""
        text = strict.old.replace_once(
            text,
            canonical_authority,
            champion_authority,
            "Research Champion independent-security authority",
        )

        # Experiment 2 adds geometry telemetry, so the canonical transform's
        # ordinary row-tail replacement cannot match. Add the same strategy-
        # boundary evidence explicitly, bound to Candidate A state.
        geometry_tail = (
            "'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason,"
            "'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),"
            "'leadership_population':int(nk),'held_count':int(len(held))})"
        )
        canonical_tail = (
            "'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason,"
            "'fast_signal':fastsig,'slow_signal':slowsig,'eligible_count':int(len(et)),"
            "'leadership_population':int(nk),'held_count':int(len(held)),"
            "'research_eligible_universe':int(len(et)),'research_ranking_count':int(len(durable)),"
            "'research_ranking_sha256':_rank_hash,'research_selected_positions_sha256':_position_hash,"
            "'research_selected_positions':json.dumps(_position_ids,separators=(',',':')),"
            "'research_ldrc_state':json.dumps(ca.__dict__,sort_keys=True,separators=(',',':'))})"
        )
        text = strict.old.replace_once(
            text,
            geometry_tail,
            canonical_tail,
            "Research Champion canonical strategy-boundary telemetry",
        )

    required = (
        "LDRC_DD=-0.1; LDRC_R20=-0.085; LDRC_CEIL=.55; LDRC_REC=8; LDRC_V=0.11",
        "'dam':0.88",
        "dam<=0.63",
        "self.recent_positive_streak>=LDRC_REC",
        "and finite(spy20) and spy20>=wc_r20",
        "pend['control']=a_d",
        "gday+15",
        "financial-grade NAV unresolved",
        "unresolved recent-leadership return",
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise RuntimeError(f"Research Champion strict source missing required seams: {missing}")
    return text


strict20.corrected.transformed_source = _champion_strict20_transform


def _seal_champion_identity(output: Path) -> None:
    daily_path = output / "daily.csv.gz"
    summary_path = output / "summary.json"
    audit_path = output / "metadata_authority_audit.json"
    if not daily_path.is_file() or not summary_path.is_file() or not audit_path.is_file():
        raise RuntimeError("Research Champion replay outputs are incomplete")

    daily = pd.read_csv(daily_path, compression="gzip")
    required = {"research_nav", "research_allocation", "A_nav", "A_allocation"}
    missing = required.difference(daily.columns)
    if missing:
        raise RuntimeError(f"Research Champion parity columns missing: {sorted(missing)}")
    nav_gap = (daily["research_nav"].astype(float) - daily["A_nav"].astype(float)).abs().max()
    alloc_gap = (
        daily["research_allocation"].astype(float) - daily["A_allocation"].astype(float)
    ).abs().max()
    if not (float(nav_gap) <= 1e-12 and float(alloc_gap) <= 1e-12):
        raise RuntimeError(
            f"Research Champion promotion parity failed nav_gap={nav_gap} alloc_gap={alloc_gap}"
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    identity = {
        "schema": "backtester.research-champion/1",
        "status": "PASS",
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA256,
        "config": CONFIG,
        "authoritative_output": {
            "nav": "research_nav",
            "allocation": "research_allocation",
            "controller_state": "CandidateA",
            "promoted_from": "A",
            "promotion_nav_max_abs_gap": float(nav_gap),
            "promotion_allocation_max_abs_gap": float(alloc_gap),
        },
        "lineage": {
            "original_e3_head": "3f27834db427e71d9bb8d0b6160c8835b739c906",
            "stability_stage1_run": 33971822256,
            "stability_stage2_run": 33974007040,
            "stability_verdict_head": "256d0f55386ccfdcea58accd12135d263f5c9092",
        },
    }
    (output / "research-champion-identity.json").write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary["research_champion"] = identity
    audit["research_champion"] = {
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA256,
        "authoritative_controller_state": "CandidateA",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [
        output / "daily.csv.gz",
        output / "metrics.csv",
        summary_path,
        audit_path,
        output / "candidate_session_coverage.json",
        output / "candidate_session_unknown_breakdown.json",
        output / "research-champion-identity.json",
    ]
    session_hash = output / "canonical_input_session_hashes.csv"
    if session_hash.exists():
        files.append(session_hash)
    missing_files = [str(p) for p in files if not p.is_file()]
    if missing_files:
        raise RuntimeError(f"Research Champion evidence files missing: {missing_files}")
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{strict20.old.sha256(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
    print(
        f"[RESEARCH_CHAMPION] PASS profile={PROFILE} profile_sha256={PROFILE_SHA256} "
        f"nav_gap={float(nav_gap):.3g} alloc_gap={float(alloc_gap):.3g}",
        flush=True,
    )


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        generated = _champion_strict20_transform(
            "fullpit", Path("/tmp/research-champion-financial-grade-selftest")
        )
        compile(generated, "<research-champion-strict-pit-generated>", "exec")
        print(
            f"[SELFTEST PASS] Research Champion profile={PROFILE} "
            f"profile_sha256={PROFILE_SHA256}",
            flush=True,
        )
        return 0

    print(
        "[CONTRACT] role=research-champion "
        f"profile={PROFILE} profile_sha256={PROFILE_SHA256}",
        flush=True,
    )
    rc = int(strict20.main())
    if rc != 0:
        return rc
    args = sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("Research Champion wrapper requires --output")
    _seal_champion_identity(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
