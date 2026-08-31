#!/usr/bin/env python3
"""Annual-prefix retained-research entrypoint over the full immutable PIT package.

The checkpointed causal-certification path also repairs the retained research
signal implementation to the adjudicated Wealth Core fixed-forward contract:
raw close multiplied only by split ratios effective through the current session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

os.environ.setdefault("CANONICAL_PIT_EXPECTED_END", "2026-07-31")

import backtester.run_research_strict_pit_20y_terminal_grace as terminal  # noqa: E402

base = terminal.base
_original = base.corrected.transformed_source


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def _fixed_forward_signal_source(text: str) -> str:
    """Align retained research signal/ranking arithmetic with causal production.

    Independent 80-digit adjudication (run 33414296781) proved that production,
    not the stored current-vintage Sharadar adjusted close, matches the normative
    fixed-forward historical signal contract on the first disputed session.
    """
    if text.count("_CANONICAL.research_observations(y)") != 1:
        raise RuntimeError(
            "fixed-forward research repair requires exactly one canonical observation loader"
        )

    text = _replace_once(
        text, "close_ring=np.full((L,n),np.nan,np.float32)",
        "close_ring=np.full((L,n),np.nan,np.float64)",
        "fixed-forward close history precision")
    text = _replace_once(
        text, "r126=np.zeros((126,n),np.float32)",
        "r126=np.zeros((126,n),np.float64)",
        "formation-return precision")
    text = _replace_once(
        text, "r21=np.zeros((21,n),np.float32)",
        "r21=np.zeros((21,n),np.float64)",
        "recent-return precision")
    text = _replace_once(
        text, "dvbuf=np.zeros((20,n),np.float32)",
        "dvbuf=np.zeros((20,n),np.float64)",
        "liquidity precision")

    factor_anchor = (
        "last_factor=np.full(n,np.nan); touched=np.empty(0,np.int32); "
        "gday=-1; first_eligible=None"
    )
    text = _replace_once(
        text, factor_anchor,
        "last_factor=np.full(n,np.nan); fixed_forward_factor=np.ones(n,np.float64); "
        "touched=np.empty(0,np.int32); gday=-1; first_eligible=None",
        "fixed-forward factor state")

    source_row = (
        "c=g.close.to_numpy(float,copy=False); cu=g.closeunadj.to_numpy(float,copy=False); "
        "oo=g.open.to_numpy(float,copy=False); vol=g.volume.to_numpy(float,copy=False)"
    )
    fixed_row = """cu=g.closeunadj.to_numpy(float,copy=False); _split_today=g.split_ratio.to_numpy(float,copy=False)
            if np.any(~np.isfinite(_split_today)) or np.any(_split_today<=0): raise RuntimeError(f'invalid canonical split ratio on {ds}')
            fixed_forward_factor[tids]*=_split_today
            c=cu*fixed_forward_factor[tids]
            rawop=g.canonical_raw_open.to_numpy(float,copy=False)
            oo=rawop*fixed_forward_factor[tids]
            vol=g.raw_compatible_volume.to_numpy(float,copy=False)"""
    text = _replace_once(
        text, source_row, fixed_row, "fixed-forward signal construction")
    text = _replace_once(
        text,
        "rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))",
        "# rawop remains canonical raw/as-traded open; oo is the fixed-forward signal open.",
        "raw-open preservation")
    text = _replace_once(
        text, "dv=np.nan_to_num(c*vol,nan=0.,posinf=0.,neginf=0.)",
        "dv=np.nan_to_num(cu*vol,nan=0.,posinf=0.,neginf=0.)",
        "raw liquidity domain")
    text = _replace_once(
        text, "close_ring[gday%L,tids]=c.astype(np.float32)",
        "close_ring[gday%L,tids]=c",
        "binary64 close-ring write")

    pool_anchor = "nk=min(len(et),max(25,int(math.ceil(len(et)*TOP)))); pool=rawall[:nk]"
    pool_replacement = pool_anchor + """
                for _tid0 in pool:
                    _tid=int(_tid0)
                    _seg=[float(close_ring[(gday-_lag)%L,_tid]) for _lag in range(126,20,-1)]
                    if len(_seg)!=106 or any((not finite(_v)) or _v<=0 for _v in _seg):
                        score[_tid]=np.nan; continue
                    _rets=[math.log(_cur/_prev) for _prev,_cur in zip(_seg,_seg[1:])]
                    _mean=sum(_rets)/len(_rets)
                    _var=sum((_r-_mean)**2 for _r in _rets)/(len(_rets)-1)
                    if (not finite(_var)) or _var<=0:
                        score[_tid]=np.nan; continue
                    _vol=math.sqrt(_var)*math.sqrt(252.0)
                    _m=float(mom[_tid])
                    score[_tid]=(math.log1p(_m)/_vol if finite(_m) and _m>-1 and finite(_vol) and _vol>0 else np.nan)"""
    text = _replace_once(
        text, pool_anchor, pool_replacement,
        "scalar durable-score ordering arithmetic")

    summary_anchor = "'canonical_pit_dataset_hash':_CANONICAL.dataset_hash,"
    text = _replace_once(
        text, summary_anchor,
        summary_anchor
        + "\n        'research_signal_contract':'fixed_forward_raw_close_times_causal_split_factor',"
        + "\n        'research_signal_precision':'binary64_with_scalar_durable_score',",
        "research signal provenance")

    forbidden = (
        "close_ring=np.full((L,n),np.nan,np.float32)",
        "c=g.close.to_numpy(float,copy=False)",
        "dv=np.nan_to_num(c*vol",
        "close_ring[gday%L,tids]=c.astype(np.float32)",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(
                f"fixed-forward research signal defect survived transform: {needle}"
            )
    return text


def _full_package_prefix_source(mode, output):
    text = _original(mode, output)
    old = "expected_end=os.environ.get('CERTIFICATION_END_SESSION'))"
    new = (
        "expected_end=os.environ.get('CANONICAL_PIT_EXPECTED_END', "
        "os.environ.get('CERTIFICATION_END_SESSION')))"
    )
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"canonical research package-end seam: expected one match, found {count}"
        )
    text = text.replace(old, new, 1)
    text = _fixed_forward_signal_source(text)

    diagnostic_session = os.environ.get(
        "CERTIFICATION_RANKING_DIAGNOSTIC_SESSION", ""
    ).strip()
    if diagnostic_session:
        needle = "ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]"
        if text.count(needle) != 1:
            raise RuntimeError(
                "research ranking diagnostic seam: expected one durable-ranking expression"
            )
        injected = needle + "\n" + (
            "                if ds==" + repr(diagnostic_session) + ":\n"
            "                    _diag_payload={'session':ds,'eligible_universe':int(len(et)),"
            "'leadership_ids':[str(sid[int(x)]) for x in pool],"
            "'ranking':[{'security_id':str(sid[int(x)]),'ticker':str(tick[int(x)]),"
            "'momentum':float(mom[int(x)]),'recent':float(recent[int(x)]),"
            "'score':float(score[int(x)])} for x in durable]}\n"
            "                    print('[RANKING DIAGNOSTIC] role=research '+"
            "json.dumps(_diag_payload,sort_keys=True,separators=(',',':')),flush=True)"
        )
        text = text.replace(needle, injected, 1)
    return text


base.corrected.transformed_source = _full_package_prefix_source

if __name__ == "__main__":
    raise SystemExit(base.main())
