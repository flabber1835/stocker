#!/usr/bin/env python3
"""Backtester-only research signal repair for strict-PIT equivalence.

The retained research replay historically consumed the canonical package's stored
Sharadar ``SEP.close`` directly.  The production Wealth Core feed instead owns a
fixed-forward causal signal basis:

    signal_close(t) = raw_close(t) * product(split_ratio <= t)

The distinction is economically active because vendor historical adjustment
rounding/rebasing can reorder close candidates near ties.  Independent 80-digit
adjudication on 2006-08-08 proved production matches the fixed-forward contract
exactly and retained research does not.

This source-to-source overlay changes only the strict-PIT retained research
implementation.  It preserves raw/as-traded marking/execution/liquidity domains,
uses float64 signal history, and recomputes durable-score volatility over the
leadership pool with the same scalar arithmetic specified by production.
"""
from __future__ import annotations


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def install(text: str) -> str:
    if text.count("_CANONICAL.research_observations(y)") != 1:
        raise RuntimeError(
            "fixed-forward research repair requires exactly one canonical-PIT observation loader"
        )

    # A float32 ring was sufficient for exploratory research but is not a safe
    # implementation of an exact ordering contract.  Leadership endpoints and
    # the formation path must retain the same binary64 input values production
    # receives from the canonical package.
    text = _replace_once(
        text,
        "close_ring=np.full((L,n),np.nan,np.float32)",
        "close_ring=np.full((L,n),np.nan,np.float64)",
        "fixed-forward close history precision",
    )
    text = _replace_once(
        text,
        "r126=np.zeros((126,n),np.float32)",
        "r126=np.zeros((126,n),np.float64)",
        "formation-return precision",
    )
    text = _replace_once(
        text,
        "r21=np.zeros((21,n),np.float32)",
        "r21=np.zeros((21,n),np.float64)",
        "recent-return precision",
    )
    text = _replace_once(
        text,
        "dvbuf=np.zeros((20,n),np.float32)",
        "dvbuf=np.zeros((20,n),np.float64)",
        "liquidity precision",
    )

    factor_anchor = (
        "last_factor=np.full(n,np.nan); touched=np.empty(0,np.int32); "
        "gday=-1; first_eligible=None"
    )
    text = _replace_once(
        text,
        factor_anchor,
        "last_factor=np.full(n,np.nan); fixed_forward_factor=np.ones(n,np.float64); "
        "touched=np.empty(0,np.int32); gday=-1; first_eligible=None",
        "fixed-forward cumulative split-factor state",
    )

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
        text, source_row, fixed_row, "canonical fixed-forward signal construction"
    )
    text = _replace_once(
        text,
        "rawop=np.divide(oo*cu,c,out=np.full_like(oo,np.nan),where=np.isfinite(oo)&np.isfinite(cu)&np.isfinite(c)&(c>0))",
        "# rawop is the canonical raw/as-traded open; oo is its fixed-forward signal-domain equivalent.",
        "raw-open domain preservation",
    )

    # Liquidity is raw close x raw-compatible volume in production.  Once the
    # research signal has an independent fixed-forward scale it must not be used
    # as the liquidity price.
    text = _replace_once(
        text,
        "dv=np.nan_to_num(c*vol,nan=0.,posinf=0.,neginf=0.)",
        "dv=np.nan_to_num(cu*vol,nan=0.,posinf=0.,neginf=0.)",
        "raw liquidity price domain",
    )
    text = _replace_once(
        text,
        "close_ring[gday%L,tids]=c.astype(np.float32)",
        "close_ring[gday%L,tids]=c",
        "fixed-forward close-ring write",
    )

    # The rolling vectorized variance is retained as a cheap eligibility
    # precheck, but the economically active durable ordering is recomputed for
    # the leadership pool using the exact scalar formula from the strategy
    # contract: 105 log returns, Python left-to-right sums, sample variance and
    # sqrt(252).  This keeps research implementation-independent while removing
    # a numeric ordering discrepancy that the exact hash gate correctly caught.
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
        text, pool_anchor, pool_replacement, "exact durable-score ordering arithmetic"
    )

    summary_anchor = "'canonical_pit_dataset_hash':_CANONICAL.dataset_hash,"
    text = _replace_once(
        text,
        summary_anchor,
        summary_anchor
        + "\n        'research_signal_contract':'fixed_forward_raw_close_times_causal_split_factor',"
        + "\n        'research_signal_precision':'binary64_with_scalar_durable_score',",
        "research signal provenance",
    )

    forbidden = (
        "close_ring=np.full((L,n),np.nan,np.float32)",
        "c=g.close.to_numpy(float,copy=False)",
        "dv=np.nan_to_num(c*vol",
        "close_ring[gday%L,tids]=c.astype(np.float32)",
    )
    for needle in forbidden:
        if needle in text:
            raise RuntimeError(
                f"fixed-forward research signal defect survived overlay: {needle}"
            )
    required = (
        "fixed_forward_factor[tids]*=_split_today",
        "c=cu*fixed_forward_factor[tids]",
        "oo=rawop*fixed_forward_factor[tids]",
        "_rets=[math.log(_cur/_prev)",
        "research_signal_contract",
    )
    for needle in required:
        if needle not in text:
            raise RuntimeError(
                f"fixed-forward research repair missing required seam: {needle}"
            )
    return text
