#!/usr/bin/env python3
"""Frozen Median-5 five-way deterministic security-universe jackknife."""
from __future__ import annotations

import ast

ARMS = tuple(f"M5_JACKKNIFE_BUCKET_{i}" for i in range(5))


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def _median5(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 20", 1, "Caesar 20 capacity")
    text = _replace_exact(text, "ENTRY_W = 0.04", "ENTRY_W = 0.05", 1, "Caesar 20 entry weight")
    helper = '''
    def _hard_rank(_tid,_order):
        try: return _order.index(int(_tid))
        except ValueError: return len(_order)+1000

    def _median_top3(_durable,_hist,_lookback):
        _arr=[int(x) for x in _durable]
        if len(_arr)<2: return np.asarray(_arr,dtype=np.int32)
        _top=_arr[:3]; _hs=_hist[-int(_lookback):]
        def _key(_tid):
            _vals=[_hard_rank(_tid,_o) for _o in _hs]
            return (float(np.median(_vals)),_arr.index(_tid))
        _front=sorted(_top,key=_key)
        return np.asarray(_front+_arr[3:],dtype=np.int32)

    def _harden_order(_durable,_score,_hist):
        return _median_top3(_durable,_hist,5)
'''
    marker = "    ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()"
    text = _replace_exact(text, marker, helper + "\n" + marker, 1, "Median-5 helper insertion")
    init = "    shadow_dates=[]; shadow_eq=[]; damaged_hist=[]; stop_days=[]"
    text = _replace_exact(text, init, init + "\n    _rank_order_hist=[]", 1, "Median-5 history initialization")
    hist_marker = "            inpool=np.zeros(n,bool); inpool[pool]=True"
    hist_code = (
        "            _rank_order_hist.append(tuple(int(x) for x in durable))\n"
        "            if len(_rank_order_hist)>5: del _rank_order_hist[:-5]\n"
        + hist_marker
    )
    text = _replace_exact(text, hist_marker, hist_code, 1, "Median-5 causal rank-history update")
    text = _replace_exact(
        text,
        "                    for tid0 in durable:",
        "                    for tid0 in _harden_order(durable,score,_rank_order_hist):",
        1,
        "Median-5 admission seam",
    )
    return text


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(arm)
    out = _median5(text)
    bucket = int(arm.rsplit("_", 1)[1])
    old = "if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue"
    new = old.replace(": continue", f" or int(sid[int(tid)])%5=={bucket}: continue")
    out = _replace_exact(out, old, new, 1, f"Median-5 deterministic security jackknife bucket {bucket}")
    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    bucket = int(arm.rsplit("_", 1)[1])
    if "N_SLOTS = 20" not in variant or "ENTRY_W = 0.05" not in variant:
        raise RuntimeError("Median-5 accounting changed")
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
    for marker in (
        "_rank_order_hist.append(tuple(int(x) for x in durable))",
        "for tid0 in _harden_order(durable,score,_rank_order_hist):",
        "return _median_top3(_durable,_hist,5)",
    ):
        if variant.count(marker) != 1:
            raise RuntimeError(f"Median-5 seam missing/duplicated: {marker}")
    token = f"int(sid[int(tid)])%5=={bucket}"
    if variant.count(token) != 1:
        raise RuntimeError(f"jackknife token mismatch for {arm}")
    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    bucket = arm.rsplit("_", 1)[1]
    return ["median5", f"deterministic_security_id_mod5_exclusion_bucket_{bucket}", "20pct_security_jackknife"]
