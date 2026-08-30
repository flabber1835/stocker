#!/usr/bin/env python3
"""Strict-PIT retained-research certification on the agreed 20-year window.

Adds candidate/session security-type coverage evidence so the 2006 boundary can
be validated before the expensive full replay is accepted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

# This file is executed directly by the parallel orchestrator.  Bootstrap the
# repository root locally so package imports do not depend on PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["CERTIFICATION_STRICT_PIT"] = "1"

import backtester.run_research_strict_pit_certification as strict

corrected = strict.corrected
old = strict.old
WARMUP_START = "2006-01-03"
MEASUREMENT_START = "2006-07-31"
FULL_END_SESSION = "2026-07-31"
END_SESSION = os.environ.get("CERTIFICATION_END_SESSION", FULL_END_SESSION)

corrected.WARMUP_START = WARMUP_START
corrected.MEASUREMENT_START = MEASUREMENT_START
old.END = END_SESSION
if END_SESSION != FULL_END_SESSION:
    old.WINDOWS = {
        key: (MEASUREMENT_START, None) for key in ("5", "10", "15", "20")
    }

_base_transform = corrected.transformed_source


def _replace_once(text: str, old_text: str, new_text: str, label: str) -> str:
    count = text.count(old_text)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old_text, new_text, 1)


def _twenty_year_transform(mode: str, output: Path) -> str:
    text = _base_transform(mode, output)
    if os.environ.get("CANONICAL_PIT_DATASET"):
        cash_start = text.index("def bil_factors(bil,date,prevdate):")
        cash_end = text.index("\ndef nearest_split_authority", cash_start)
        canonical_cash = """def bil_factors(bil,date,prevdate):
    if prevdate is None: return 0.,0.,1.
    if date not in bil.index: raise RuntimeError(f'canonical cash factor missing for {date}')
    gap=float(bil.loc[date,'gap_factor']); intra=float(bil.loc[date,'intraday_factor'])
    if min(gap,intra)<=0: raise RuntimeError(f'invalid canonical cash factor for {date}')
    return gap-1.0,intra-1.0,gap*intra
"""
        text = text[:cash_start] + canonical_cash + text[cash_end + 1:]
    text = _replace_once(
        text,
        "START = pd.Timestamp('1998-01-02')",
        f"START = pd.Timestamp('{MEASUREMENT_START}')",
        "20-year measurement start",
    )
    text = _replace_once(
        text,
        "END = pd.Timestamp('2026-07-31')",
        f"END = pd.Timestamp('{END_SESSION}')",
        "certification end",
    )
    text = _replace_once(
        text,
        "    for y in range(1997,END.year+1):",
        "    for y in range(2006,END.year+1):",
        "20-year warm-up year",
    )

    counts_needle = "_SEC_COUNTS={'auto_common':0,'manual_common':0,'manual_non_common':0,'unknown_ineligible':0}"
    counts_replacement = counts_needle + "\n    _CANDIDATE_COVERAGE={'base_candidates':0,'known_classifications':0,'unknown_classifications':0,'sessions':0,'sessions_with_unknown':0,'worst_known_fraction':1.0,'worst_session':None,'first_unknown_session':None,'by_year':{}}\n    _UNKNOWN_DETAIL={'by_ticker':{},'by_month':{},'by_cik_availability':{},'by_sec_evidence_availability':{},'by_security_type':{'unknown_ineligible':0}}"
    text = _replace_once(text, counts_needle, counts_replacement, "candidate coverage counters")

    old_elig = "elig=np.asarray([common_key(int(t),ds) for t in tids],dtype=bool)&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    new_elig = """_base_elig=listed&continuous&np.isfinite(mm)&np.isfinite(rr)&np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)
            _sec_ok=np.zeros(len(tids),dtype=bool); _known=0; _unknown=0
            for _j in np.flatnonzero(_base_elig):
                _tid=int(tids[int(_j)]); _tk=str(tick[_tid]).upper(); _u0=_SEC_COUNTS['unknown_ineligible']; _sec_ok[int(_j)]=common_key(_tid,ds)
                if _SEC_COUNTS['unknown_ineligible']>_u0:
                    _unknown+=1; _UNKNOWN_DETAIL['by_security_type']['unknown_ineligible']+=1
                    _cik=pit_model._strict_prior(pit_model.cik_dates.get(_tk,()),pit_model.cik_values.get(_tk,()),ds)
                    _cik_key='available' if _cik is not None else 'missing'
                    _UNKNOWN_DETAIL['by_cik_availability'][_cik_key]=_UNKNOWN_DETAIL['by_cik_availability'].get(_cik_key,0)+1
                    _q=_sec_by.get(_tk)
                    if _q is None or not len(_q[_q.filed<ds]): _ev='no_strict_prior_positive_evidence'
                    elif _cik is None: _ev='strict_prior_positive_evidence_cik_missing'
                    else:
                        _qp=_q[_q.filed<ds]; _qm=_qp[_qp.cik.map(lambda x: str(int(float(x))) if pd.notna(x) else '')==str(_cik)]
                        _ev='strict_prior_positive_evidence_cik_mismatch' if not len(_qm) else 'unexpected_matching_positive_evidence'
                    _UNKNOWN_DETAIL['by_sec_evidence_availability'][_ev]=_UNKNOWN_DETAIL['by_sec_evidence_availability'].get(_ev,0)+1
                    _mon=ds[:7]; _UNKNOWN_DETAIL['by_month'][_mon]=_UNKNOWN_DETAIL['by_month'].get(_mon,0)+1
                    _td=_UNKNOWN_DETAIL['by_ticker'].setdefault(_tk,{'observations':0,'first_session':ds,'last_session':ds,'cik_available':0,'cik_missing':0,'evidence':{}})
                    _td['observations']+=1; _td['last_session']=ds; _td['cik_available' if _cik is not None else 'cik_missing']+=1; _td['evidence'][_ev]=_td['evidence'].get(_ev,0)+1
                else: _known+=1
            _nbase=_known+_unknown
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
    text = _replace_once(text, old_elig, new_elig, "candidate/session security-type coverage")

    summary_needle = "'strict_security_type_counts':_SEC_COUNTS,"
    text = _replace_once(
        text,
        summary_needle,
        summary_needle + "\n        'strict_candidate_security_type_coverage':_CANDIDATE_COVERAGE,\n        'strict_candidate_security_type_unknown_breakdown':_UNKNOWN_DETAIL,",
        "candidate coverage evidence",
    )
    if os.environ.get("CANONICAL_PIT_DATASET"):
        text = strict._canonical_unknown_diagnostics(text)
    return text


corrected.transformed_source = _twenty_year_transform


def _finalize_coverage(output: Path) -> None:
    summary_path = output / "summary.json"
    audit_path = output / "metadata_authority_audit.json"
    coverage_path = output / "candidate_session_coverage.json"
    unknown_path = output / "candidate_session_unknown_breakdown.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    coverage = summary.get("strict_candidate_security_type_coverage") or {}
    unknown_detail = summary.get("strict_candidate_security_type_unknown_breakdown") or {}
    if not coverage:
        raise RuntimeError("candidate/session coverage evidence was not emitted")
    if not unknown_detail:
        raise RuntimeError("candidate/session unknown breakdown was not emitted")
    total = int(coverage.get("base_candidates", 0))
    known = int(coverage.get("known_classifications", 0))
    unknown = int(coverage.get("unknown_classifications", 0))
    coverage["known_fraction"] = (known / total) if total else 1.0
    coverage["complete"] = unknown == 0
    coverage["warmup_start"] = WARMUP_START
    coverage["measurement_start"] = MEASUREMENT_START
    coverage["end_session"] = END_SESSION
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    unknown_path.write_text(json.dumps(unknown_detail, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary["candidate_session_security_type_coverage"] = coverage
    summary["candidate_session_security_type_unknown_breakdown"] = unknown_detail
    summary["warmup"] = {
        "start": WARMUP_START,
        "measurement_start": MEASUREMENT_START,
        "full_machine_state_carried": True,
        "measured_warmup_sessions": 0,
    }
    summary["max_history_measurement_start"] = MEASUREMENT_START
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["candidate_session_security_type_coverage"] = coverage
    audit["candidate_session_security_type_unknown_breakdown"] = unknown_detail
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = [output / "daily.csv.gz", output / "metrics.csv", summary_path, audit_path, coverage_path, unknown_path]
    session_hash_path = output / "canonical_input_session_hashes.csv"
    if session_hash_path.exists():
        files.append(session_hash_path)
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{old.sha256(path)}  {path.name}\n" for path in files), encoding="utf-8"
    )
    print(
        f"[CANDIDATE COVERAGE] known={known}/{total} "
        f"unknown={unknown} complete={unknown == 0}",
        flush=True,
    )
    print(
        "[CANDIDATE UNKNOWN] " + json.dumps({
            "by_cik_availability": unknown_detail.get("by_cik_availability"),
            "by_sec_evidence_availability": unknown_detail.get("by_sec_evidence_availability"),
            "top_tickers": sorted(
                ((k, int(v.get("observations", 0))) for k, v in (unknown_detail.get("by_ticker") or {}).items()),
                key=lambda x: (-x[1], x[0]),
            )[:20],
        }, sort_keys=True),
        flush=True,
    )


def main() -> int:
    if "--self-test-imports" in sys.argv[1:]:
        print(
            f"[SELFTEST PASS] research 20y entrypoint root={ROOT} "
            f"backtester_import={Path(strict.__file__).resolve()}",
            flush=True,
        )
        return 0
    print(
        f"[CONTRACT] role=research warmup={WARMUP_START} "
        f"measurement={MEASUREMENT_START} end={END_SESSION}",
        flush=True,
    )
    rc = int(strict.main())
    if rc != 0:
        return rc
    args = os.sys.argv[1:]
    try:
        output = Path(args[args.index("--output") + 1])
    except (ValueError, IndexError):
        raise RuntimeError("20-year research wrapper requires --output")
    _finalize_coverage(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
