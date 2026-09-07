#!/usr/bin/env python3
"""Frozen Median-5 overlays for eight causal adversarial experiments."""
from __future__ import annotations

import ast

ARMS = (
    "M5_ENTRY_DELAY_1",
    "M5_ENTRY_DELAY_2",
    "M5_EXIT_DELAY_1",
    "M5_COST_25BPS_RT",
    "M5_COST_50BPS_RT",
    "M5_LIQ_ADV40M",
    "M5_LIQ_ADV80M",
    "M5_LIQ_DAYDV10M",
)


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


def _exit_delay(text: str) -> str:
    text = _replace_exact(
        text, "pending_sell:bool=False; sell_reason:str=''",
        "pending_sell:bool=False; pending_exit_signal_day:int=-1; sell_reason:str=''",
        1, "dedicated ordinary-exit timestamp",
    )
    for owner, count in (("s", 4), ("_slot", 1)):
        old = f"{owner}.pending_sell=False; {owner}.sell_reason=''"
        new = f"{owner}.pending_sell=False; {owner}.pending_exit_signal_day=-1; {owner}.sell_reason=''"
        text = _replace_exact(text, old, new, count, f"{owner} exit-state resets")
    for reason in ("stop", "review"):
        old = f"s.pending_sell=True; s.sell_reason='{reason}'"
        new = "s.pending_exit_signal_day=gday if not s.pending_sell else s.pending_exit_signal_day; " + old
        text = _replace_exact(text, old, new, 1, f"latched {reason} timestamp")
    text = _replace_exact(
        text, "if not(s.held() and s.pending_sell): continue",
        "if not(s.held() and s.pending_sell): continue\n"
        "                if not (0 <= s.pending_exit_signal_day < gday):\n"
        "                    raise RuntimeError('invalid latched ordinary-exit timestamp')\n"
        "                if gday < s.pending_exit_signal_day+2: continue",
        1, "t+2 ordinary-exit gate",
    )
    text = _replace_exact(text, "def run():\n", "def run():\n    _exit_delay_events=[]\n", 1, "exit witness initialization")
    text = _replace_exact(
        text, "book.cash+=s.qty*float(px)*(1-COST); sells+=1",
        "book.cash+=s.qty*float(px)*(1-COST); sells+=1\n"
        "                    _exit_delay_events.append({'security_id':str(sid[s.tid]),'ticker':str(tick[s.tid]),"
        "'signal_session_index':s.pending_exit_signal_day,'execution_session_index':gday,"
        "'execution_session':ds,'reason':s.sell_reason})",
        1, "executed ordinary-exit witness",
    )
    text = _replace_exact(
        text, "out.to_csv(OUT/'daily.csv',index=False)",
        "out.to_csv(OUT/'daily.csv',index=False)\n"
        "    pd.DataFrame(_exit_delay_events).to_csv(OUT/'exit-delay-events.csv',index=False)",
        1, "ordinary-exit witness export",
    )
    return text


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(arm)
    out = _median5(text)

    if arm == "M5_ENTRY_DELAY_1":
        out = _replace_exact(out,
            "if not(s.reserved() and not s.held()): continue",
            "if not(s.reserved() and not s.held()) or gday < s.pending_signal_day+2: continue",
            1, "Median-5 entry delay +1")
    elif arm == "M5_ENTRY_DELAY_2":
        out = _replace_exact(out,
            "if not(s.reserved() and not s.held()): continue",
            "if not(s.reserved() and not s.held()) or gday < s.pending_signal_day+3: continue",
            1, "Median-5 entry delay +2")
    elif arm == "M5_EXIT_DELAY_1":
        out = _exit_delay(out)
    elif arm == "M5_COST_25BPS_RT":
        out = _replace_exact(out, "COST = 0.001", "COST = 0.00125", 1, "Median-5 25bps RT")
    elif arm == "M5_COST_50BPS_RT":
        out = _replace_exact(out, "COST = 0.001", "COST = 0.0025", 1, "Median-5 50bps RT")
    elif arm == "M5_LIQ_ADV40M":
        out = _replace_exact(out, "MIN_ADV20 = 20_000_000.0", "MIN_ADV20 = 40_000_000.0", 1, "Median-5 ADV40M")
    elif arm == "M5_LIQ_ADV80M":
        out = _replace_exact(out, "MIN_ADV20 = 20_000_000.0", "MIN_ADV20 = 80_000_000.0", 1, "Median-5 ADV80M")
    elif arm == "M5_LIQ_DAYDV10M":
        out = _replace_exact(out, "MIN_DAY_DV = 5_000_000.0", "MIN_DAY_DV = 10_000_000.0", 1, "Median-5 DAYDV10M")
    else:
        raise AssertionError(arm)

    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if "N_SLOTS = 20" not in variant or "ENTRY_W = 0.05" not in variant:
        raise RuntimeError("Median-5 Caesar-20 accounting changed")
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("one-session dividend scheduling lost")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    for invariant in (
        "from backtester import champion_final_security_truth as _bestclass",
        "COOLDOWN = 21", "REVIEW_AGE = 119", "STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1",
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

    expected_cost = {
        "M5_COST_25BPS_RT":"0.00125",
        "M5_COST_50BPS_RT":"0.0025",
    }.get(arm,"0.001")
    if f"COST = {expected_cost}" not in variant:
        raise RuntimeError("cost stress mismatch")
    expected_adv = {
        "M5_LIQ_ADV40M":"40_000_000.0",
        "M5_LIQ_ADV80M":"80_000_000.0",
    }.get(arm,"20_000_000.0")
    if f"MIN_ADV20 = {expected_adv}" not in variant:
        raise RuntimeError("ADV stress mismatch")
    expected_day = "10_000_000.0" if arm == "M5_LIQ_DAYDV10M" else "5_000_000.0"
    if f"MIN_DAY_DV = {expected_day}" not in variant:
        raise RuntimeError("same-day DV stress mismatch")
    if arm == "M5_ENTRY_DELAY_1" and "gday < s.pending_signal_day+2" not in variant:
        raise RuntimeError("entry +1 gate missing")
    if arm == "M5_ENTRY_DELAY_2" and "gday < s.pending_signal_day+3" not in variant:
        raise RuntimeError("entry +2 gate missing")
    if arm == "M5_EXIT_DELAY_1":
        for marker in ("pending_exit_signal_day:int=-1", "if gday < s.pending_exit_signal_day+2: continue", "_exit_delay_events.append("):
            if marker not in variant:
                raise RuntimeError(f"exit-delay contract missing: {marker}")
    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    return {
        "M5_ENTRY_DELAY_1":["median5","entry_execution_delayed_one_additional_session"],
        "M5_ENTRY_DELAY_2":["median5","entry_execution_delayed_two_additional_sessions"],
        "M5_EXIT_DELAY_1":["median5","ordinary_stop_review_exit_delayed_one_additional_session"],
        "M5_COST_25BPS_RT":["median5","25bps_round_trip_cost"],
        "M5_COST_50BPS_RT":["median5","50bps_round_trip_cost"],
        "M5_LIQ_ADV40M":["median5","adv20_floor_40m"],
        "M5_LIQ_ADV80M":["median5","adv20_floor_80m"],
        "M5_LIQ_DAYDV10M":["median5","same_day_dollar_volume_floor_10m"],
    }[arm]
