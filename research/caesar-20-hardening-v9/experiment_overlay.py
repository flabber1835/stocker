#!/usr/bin/env python3
"""Architecture-preserving Caesar 20 admission hardening experiments.

All arms preserve the frozen 20-slot/5%-entry accounting model and change only
how today's canonical durable top-three ordering is converted into the admission
scan order.  All inputs are available at the current decision close.
"""
from __future__ import annotations

import ast

ARMS = (
    "CONSENSUS_MEDIAN_3",
    "CONSENSUS_MEDIAN_5",
    "GAP2_CONSENSUS_3",
    "GAP5_CONSENSUS_3",
    "TOP3_VOTE_3",
    "TOP3_PERSISTENCE_3",
)


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def _caesar20(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 20", 1, "Caesar 20 capacity")
    text = _replace_exact(text, "ENTRY_W = 0.04", "ENTRY_W = 0.05", 1, "Caesar 20 entry weight")
    return text


def _helper_for(arm: str) -> str:
    common = '''\n    def _hard_rank(_tid,_order):\n        try: return _order.index(int(_tid))\n        except ValueError: return len(_order)+1000\n\n    def _median_top3(_durable,_hist,_lookback):\n        _arr=[int(x) for x in _durable]\n        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)\n        _top=_arr[:3]; _hs=_hist[-int(_lookback):]\n        def _key(_tid):\n            _vals=[_hard_rank(_tid,_o) for _o in _hs]\n            return (float(np.median(_vals)),_arr.index(_tid))\n        _front=sorted(_top,key=_key)\n        return np.asarray(_front+_arr[3:],dtype=np.int32)\n'''
    if arm == "CONSENSUS_MEDIAN_3":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        return _median_top3(_durable,_hist,3)\n'''
    elif arm == "CONSENSUS_MEDIAN_5":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        return _median_top3(_durable,_hist,5)\n'''
    elif arm == "GAP2_CONSENSUS_3":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        _arr=[int(x) for x in _durable]\n        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)\n        _a=float(_score[_arr[0]]); _b=float(_score[_arr[1]])\n        _gap=(_a-_b)/max(abs(_a),1e-12) if np.isfinite(_a) and np.isfinite(_b) else float('inf')\n        return np.asarray(_arr,dtype=np.int32) if _gap>=0.02 else _median_top3(_durable,_hist,3)\n'''
    elif arm == "GAP5_CONSENSUS_3":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        _arr=[int(x) for x in _durable]\n        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)\n        _a=float(_score[_arr[0]]); _b=float(_score[_arr[1]])\n        _gap=(_a-_b)/max(abs(_a),1e-12) if np.isfinite(_a) and np.isfinite(_b) else float('inf')\n        return np.asarray(_arr,dtype=np.int32) if _gap>=0.05 else _median_top3(_durable,_hist,3)\n'''
    elif arm == "TOP3_VOTE_3":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        _arr=[int(x) for x in _durable]\n        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)\n        _top=_arr[:3]; _hs=_hist[-3:]\n        def _key(_tid):\n            _wins=sum(1 for _o in _hs if len(_o) and int(_o[0])==int(_tid))\n            _med=float(np.median([_hard_rank(_tid,_o) for _o in _hs]))\n            return (-_wins,_med,_arr.index(_tid))\n        _front=sorted(_top,key=_key)\n        return np.asarray(_front+_arr[3:],dtype=np.int32)\n'''
    elif arm == "TOP3_PERSISTENCE_3":
        body = '''\n    def _harden_order(_durable,_score,_hist):\n        _arr=[int(x) for x in _durable]\n        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)\n        _top=_arr[:3]; _hs=_hist[-3:]\n        _counts={_tid:sum(1 for _o in _hs if _hard_rank(_tid,_o)<3) for _tid in _top}\n        if _counts.get(_top[0],0)>=2: return np.asarray(_arr,dtype=np.int32)\n        _eligible=[_tid for _tid in _top if _counts.get(_tid,0)>=2]\n        if not _eligible: return np.asarray(_arr,dtype=np.int32)\n        _pick=min(_eligible,key=lambda _tid:_arr.index(_tid))\n        _front=[_pick]+[_tid for _tid in _top if _tid!=_pick]\n        return np.asarray(_front+_arr[3:],dtype=np.int32)\n'''
    else:
        raise ValueError(arm)
    return common + body


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    out = _caesar20(text)

    marker = "    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()"
    out = _replace_exact(out, marker, _helper_for(arm) + "\n" + marker, 1, "hardening helper insertion")

    init = "    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]"
    out = _replace_exact(out, init, init + "\n    _rank_order_hist=[]", 1, "rank history initialization")

    hist_marker = "            inpool=np.zeros(n,bool); inpool[pool]=True"
    hist_code = (
        "            _rank_order_hist.append(tuple(int(x) for x in durable))\n"
        "            if len(_rank_order_hist)>5: del _rank_order_hist[:-5]\n"
        + hist_marker
    )
    out = _replace_exact(out, hist_marker, hist_code, 1, "causal rank-history update")

    out = _replace_exact(
        out,
        "                    for tid0 in durable:",
        "                    for tid0 in _harden_order(durable,score,_rank_order_hist):",
        1,
        "admission-order hardening seam",
    )

    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError(arm)
    if "N_SLOTS = 20" not in variant or "ENTRY_W = 0.05" not in variant:
        raise RuntimeError("Caesar 20 definition changed")
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("one-session dividend scheduling lost")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    for invariant in (
        "from backtester import champion_final_security_truth as _bestclass",
        "COOLDOWN = 21",
        "REVIEW_AGE = 119",
        "STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1",
        "COST = 0.001",
        "MIN_ADV20 = 20_000_000.0",
        "MIN_DAY_DV = 5_000_000.0",
    ):
        if invariant not in variant:
            raise RuntimeError(f"certified invariant changed: {invariant}")
    if variant.count("_rank_order_hist.append(tuple(int(x) for x in durable))") != 1:
        raise RuntimeError("rank history update missing")
    if variant.count("for tid0 in _harden_order(durable,score,_rank_order_hist):") != 1:
        raise RuntimeError("hardening admission seam missing")
    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    return {
        "CONSENSUS_MEDIAN_3": ["caesar20", "admission_only", "top3_median_rank_3_sessions"],
        "CONSENSUS_MEDIAN_5": ["caesar20", "admission_only", "top3_median_rank_5_sessions"],
        "GAP2_CONSENSUS_3": ["caesar20", "admission_only", "rank1_kept_if_score_gap_ge_2pct_else_consensus3"],
        "GAP5_CONSENSUS_3": ["caesar20", "admission_only", "rank1_kept_if_score_gap_ge_5pct_else_consensus3"],
        "TOP3_VOTE_3": ["caesar20", "admission_only", "top3_recent_rank1_vote_3_sessions"],
        "TOP3_PERSISTENCE_3": ["caesar20", "admission_only", "rank1_requires_top3_presence_2_of_3_if_alternative_exists"],
    }[arm]
