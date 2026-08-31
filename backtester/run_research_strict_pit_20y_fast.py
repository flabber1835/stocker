#!/usr/bin/env python3
"""Accelerated strict-PIT retained-research replay using a compiled PIT tape.

Economic state transitions remain sequential.  Canonical observation parsing,
rolling feature construction, and security-type classification are supplied by a
one-time compiled artifact whose source dataset hash must match the canonical PIT
package consumed by the replay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from backtester.compiled_pit_research import CompiledPITResearchTape
import backtester.run_research_strict_pit_20y as base


strict = base.strict
corrected = base.corrected
old = base.old
_slow_transform = corrected.transformed_source


def _replace_once(text: str, old_text: str, new_text: str, label: str) -> str:
    count = text.count(old_text)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old_text, new_text, 1)


def _fast_transform(mode: str, output: Path) -> str:
    if mode != "fullpit":
        raise RuntimeError("compiled PIT research replay supports fullpit mode only")
    if not os.environ.get("COMPILED_PIT_RESEARCH_DATASET"):
        raise RuntimeError("COMPILED_PIT_RESEARCH_DATASET is required")

    text = _slow_transform(mode, output)
    text = _replace_once(
        text,
        "from backtester.canonical_pit_dataset import CanonicalPITDataset",
        "from backtester.canonical_pit_dataset import CanonicalPITDataset\n"
        "from backtester.compiled_pit_research import CompiledPITResearchTape",
        "compiled tape import",
    )
    text = _replace_once(
        text,
        "global _CANONICAL, _PIT_EPISODES, _PIT_IDENTITY_AUDIT, _SID_TO_TID",
        "global _CANONICAL, _FAST_TAPE, _PIT_EPISODES, _PIT_IDENTITY_AUDIT, _SID_TO_TID",
        "compiled tape global",
    )
    text = _replace_once(
        text,
        "    rows=[]; _PIT_EPISODES=defaultdict(list)",
        "    _FAST_TAPE=CompiledPITResearchTape(\n"
        "        Path(os.environ['COMPILED_PIT_RESEARCH_DATASET']),\n"
        "        expected_dataset_hash=_CANONICAL.dataset_hash)\n"
        "    rows=[]; _PIT_EPISODES=defaultdict(list)",
        "compiled tape initialization",
    )

    allocation_start = text.index("    L=130\n", text.index("def run():"))
    allocation_end = text.index("    opraw=np.full", allocation_start)
    text = text[:allocation_start] + text[allocation_end:]
    text = _replace_once(
        text,
        "opraw=np.full(n,np.nan); opsig=np.full(n,np.nan); clsig=np.full(n,np.nan); clraw=np.full(n,np.nan); volume=np.full(n,np.nan); rawdividend=np.zeros(n); canonicalsplit=np.ones(n)",
        "opraw=np.full(n,np.nan); opsig=np.full(n,np.nan); clsig=np.full(n,np.nan); clraw=np.full(n,np.nan); volume=np.full(n,np.nan); rawdividend=np.zeros(n); canonicalsplit=np.ones(n); r63fast=np.full(n,np.nan)",
        "fast held-return state",
    )
    text = _replace_once(
        text,
        "for a in (opraw,opsig,clsig,clraw,volume,mom,recent,score,adv): a[touched]=np.nan",
        "for a in (opraw,opsig,clsig,clraw,volume,mom,recent,score,adv,r63fast): a[touched]=np.nan",
        "fast daily reset",
    )

    prelude_start = text.index(
        "        t0=time.time(); d=_CANONICAL.research_observations(y)",
        text.index("for y in range(2006,END.year+1):"),
    )
    loop_line = "        for date,g in d.groupby('date',sort=True):"
    prelude_end = text.index(loop_line, prelude_start)
    prelude = (
        "        t0=time.time(); d=_FAST_TAPE.year(y,end=str(END.date()))\n"
        "        _quarter_last=set(d.quarter_last)\n"
    )
    text = text[:prelude_start] + prelude + text[prelude_end:]

    feature_start = text.index("            rawop=np.divide(oo*cu,c", text.index(loop_line))
    feature_end = text.index("            dt64=np.datetime64", feature_start)
    direct_features = """            rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))
            dv=g.day_dv.to_numpy(float,copy=False)
            rr=g.recent.to_numpy(float,copy=False); mm=g.mom.to_numpy(float,copy=False)
            _r63=g.r63.to_numpy(float,copy=False); sc=g.score.to_numpy(float,copy=False)
            av=g.adv.to_numpy(float,copy=False); fvol=g.fvol.to_numpy(float,copy=False)
            _fast_continuous=g.continuous.to_numpy(bool,copy=False)
            opraw[tids]=rawop; opsig[tids]=oo; clsig[tids]=c; clraw[tids]=cu; volume[tids]=vol
            rawdividend[tids]=g.dividend_per_share.to_numpy(float,copy=False); canonicalsplit[tids]=g.split_ratio.to_numpy(float,copy=False)
            mom[tids]=mm; recent[tids]=rr; score[tids]=sc; adv[tids]=av; r63fast[tids]=_r63
"""
    text = text[:feature_start] + direct_features + text[feature_end:]
    text = _replace_once(
        text,
        "dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64); continuous=c126[tids]>=126",
        "dt64=np.datetime64(date.date()); listed=(firstdate[tids]<=dt64); continuous=_fast_continuous",
        "compiled continuity",
    )

    coverage_start = text.index("            _base_elig=listed&continuous")
    coverage_end_needle = "            elig=_sec_ok&_base_elig"
    coverage_end = text.index(coverage_end_needle, coverage_start) + len(coverage_end_needle)
    vectorized_coverage = """            _base_elig=listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)
            _stype=g.security_type_code.to_numpy(np.int8,copy=False); _sec_ok=(_stype==1)
            _auto=int(np.count_nonzero(_base_elig&(_stype==1))); _noncommon=int(np.count_nonzero(_base_elig&(_stype==0))); _unknown=int(np.count_nonzero(_base_elig&(_stype<0)))
            _known=_auto+_noncommon; _nbase=_known+_unknown
            _SEC_COUNTS['auto_common']+=_auto; _SEC_COUNTS['manual_non_common']+=_noncommon; _SEC_COUNTS['unknown_ineligible']+=_unknown
            _UNKNOWN_DETAIL['by_security_type']['unknown_ineligible']+=_unknown
            if _unknown:
                _mon=ds[:7]; _UNKNOWN_DETAIL['by_month'][_mon]=_UNKNOWN_DETAIL['by_month'].get(_mon,0)+_unknown
            if _nbase:
                _CANDIDATE_COVERAGE['base_candidates']+=_nbase; _CANDIDATE_COVERAGE['known_classifications']+=_known; _CANDIDATE_COVERAGE['unknown_classifications']+=_unknown; _CANDIDATE_COVERAGE['sessions']+=1
                _yf=_CANDIDATE_COVERAGE['by_year'].setdefault(ds[:4],{'base_candidates':0,'known_classifications':0,'unknown_classifications':0,'sessions':0,'sessions_with_unknown':0})
                _yf['base_candidates']+=_nbase; _yf['known_classifications']+=_known; _yf['unknown_classifications']+=_unknown; _yf['sessions']+=1
                if _unknown:
                    _CANDIDATE_COVERAGE['sessions_with_unknown']+=1; _yf['sessions_with_unknown']+=1
                    if _CANDIDATE_COVERAGE['first_unknown_session'] is None: _CANDIDATE_COVERAGE['first_unknown_session']=ds
                _frac=_known/_nbase
                if _frac<_CANDIDATE_COVERAGE['worst_known_fraction']:
                    _CANDIDATE_COVERAGE['worst_known_fraction']=_frac; _CANDIDATE_COVERAGE['worst_session']=ds
            elig=_sec_ok&_base_elig"""
    text = text[:coverage_start] + vectorized_coverage + text[coverage_end:]

    text = _replace_once(
        text,
        "                lag63=close_ring[(gday-63)%L,tid] if gday>=63 else np.nan\n"
        "                r63v=float(px/lag63-1) if finite(px) and finite(lag63) and lag63>0 else None",
        "                r63v=float(r63fast[tid]) if finite(r63fast[tid]) else None",
        "compiled held 63-session return",
    )

    forbidden = (
        "_CANONICAL.research_observations(y)",
        "close_ring[(gday-21)",
        "r126[k]",
        "dvbuf[kd]",
        "common_key(int(t)",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(f"compiled PIT fast transform retained slow seam: {needle}")
    return text


corrected.transformed_source = _fast_transform


class _CanonicalReceipt:
    """Lightweight parent-process receipt; the child already hash-validates the dataset."""

    def __init__(self, root: Path):
        self.root = Path(root)
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.dataset_hash = str(manifest["dataset_hash"])


def _sha256(path: Path) -> str:
    return old.sha256(path)


def _finalize_fast(output: Path) -> None:
    tape_root = Path(os.environ["COMPILED_PIT_RESEARCH_DATASET"])
    manifest = json.loads((tape_root / "manifest.json").read_text(encoding="utf-8"))
    summary_path = output / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    canonical_hash = str(summary.get("canonical_pit_dataset_hash") or "")
    if canonical_hash != str(manifest.get("source_dataset_hash")):
        raise RuntimeError("fast research summary and compiled tape source hashes differ")
    summary["accelerated_research"] = True
    summary["compiled_pit_research"] = {
        "schema": manifest["schema"],
        "tape_hash": manifest["tape_hash"],
        "source_dataset_hash": manifest["source_dataset_hash"],
        "compiler_sha256": manifest["compiler_sha256"],
        "feature_spec_hash": manifest["feature_spec_hash"],
        "economic_state_transitions": "sequential retained research implementation",
        "candidate_unknown_detail": "aggregate fast-path diagnostics; economics use canonical security_type_code",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files = [
        output / "daily.csv.gz",
        output / "metrics.csv",
        summary_path,
        output / "metadata_authority_audit.json",
        output / "canonical_input_session_hashes.csv",
    ]
    files = [path for path in files if path.exists()]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    print(
        f"[FAST PIT PASS] source_dataset_hash={manifest['source_dataset_hash']} "
        f"tape_hash={manifest['tape_hash']}",
        flush=True,
    )


def _consume_custom_args() -> None:
    args = sys.argv
    if "--compiled-tape" in args:
        index = args.index("--compiled-tape")
        try:
            value = args[index + 1]
        except IndexError as exc:
            raise RuntimeError("--compiled-tape requires a path") from exc
        os.environ["COMPILED_PIT_RESEARCH_DATASET"] = value
        del args[index:index + 2]
    if "--end-session" in args:
        index = args.index("--end-session")
        try:
            value = str(args[index + 1])
        except IndexError as exc:
            raise RuntimeError("--end-session requires YYYY-MM-DD") from exc
        base.END_SESSION = value
        old.END = value
        old.WINDOWS = {key: (base.MEASUREMENT_START, None) for key in ("5", "10", "15", "20")}
        del args[index:index + 2]


def main() -> int:
    _consume_custom_args()
    if "--self-test-imports" in sys.argv[1:]:
        if not os.environ.get("COMPILED_PIT_RESEARCH_DATASET"):
            print("[SELFTEST PASS] compiled PIT fast research imports", flush=True)
            return 0
    if not os.environ.get("COMPILED_PIT_RESEARCH_DATASET"):
        raise RuntimeError("compiled PIT fast replay requires --compiled-tape or COMPILED_PIT_RESEARCH_DATASET")
    print(
        f"[RUN] accelerated strict-PIT research warmup={base.WARMUP_START} "
        f"measurement={base.MEASUREMENT_START} end={base.END_SESSION}",
        flush=True,
    )
    rc = int(corrected.main())
    if rc != 0:
        return rc
    args = sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError) as exc:
        raise RuntimeError("fast strict research wrapper requires --output") from exc

    original = strict.CanonicalPITDataset
    strict.CanonicalPITDataset = _CanonicalReceipt
    try:
        strict._write_authority_audit(output)
    finally:
        strict.CanonicalPITDataset = original
    _finalize_fast(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
