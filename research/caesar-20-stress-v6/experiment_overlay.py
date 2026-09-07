#!/usr/bin/env python3
"""Frozen source overlays for six Caesar 20 causal stress experiments."""
from __future__ import annotations

import ast

ARMS = (
    "ENTRY_DELAY_1",
    "ENTRY_DELAY_2",
    "EXIT_DELAY_1",
    "RANK_TOP3_REVERSE",
    "COST_25BPS_RT",
    "COST_50BPS_RT",
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


def _exit_delay(text: str) -> str:
    """Latch each ordinary exit at its first decision close; fill at t+2 or later."""
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
        new = ("s.pending_exit_signal_day=gday if not s.pending_sell else s.pending_exit_signal_day; " + old)
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
        raise ValueError(f"unsupported arm: {arm}")
    out = _caesar20(text)

    if arm == "ENTRY_DELAY_1":
        out = _replace_exact(
            out,
            "if not(s.reserved() and not s.held()): continue",
            "if not(s.reserved() and not s.held()) or gday < s.pending_signal_day+2: continue",
            1,
            "one-session additional entry delay",
        )
    elif arm == "ENTRY_DELAY_2":
        out = _replace_exact(
            out,
            "if not(s.reserved() and not s.held()): continue",
            "if not(s.reserved() and not s.held()) or gday < s.pending_signal_day+3: continue",
            1,
            "two-session additional entry delay",
        )
    elif arm == "EXIT_DELAY_1":
        out = _exit_delay(out)
    elif arm == "RANK_TOP3_REVERSE":
        out = _replace_exact(
            out,
            "for tid0 in durable:",
            "for tid0 in np.concatenate((durable[:3][::-1],durable[3:])):",
            1,
            "top-three rank perturbation",
        )
    elif arm == "COST_25BPS_RT":
        out = _replace_exact(out, "COST = 0.001", "COST = 0.00125", 1, "25 bps round-trip cost")
    elif arm == "COST_50BPS_RT":
        out = _replace_exact(out, "COST = 0.001", "COST = 0.0025", 1, "50 bps round-trip cost")
    else:
        raise AssertionError(arm)

    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError(arm)
    if "N_SLOTS = 20" not in variant or "ENTRY_W = 0.05" not in variant:
        raise RuntimeError("Caesar 20 definition changed")
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("variant lost exact one-session dividend scheduling")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    for invariant in (
        "from backtester import champion_final_security_truth as _bestclass",
        "COOLDOWN = 21",
        "REVIEW_AGE = 119",
        "STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1",
    ):
        if invariant not in variant:
            raise RuntimeError(f"certified invariant changed: {invariant}")

    expected_cost = {
        "COST_25BPS_RT": "0.00125",
        "COST_50BPS_RT": "0.0025",
    }.get(arm, "0.001")
    if f"COST = {expected_cost}" not in variant:
        raise RuntimeError("transaction-cost arm mismatch")

    if arm == "ENTRY_DELAY_1" and "gday < s.pending_signal_day+2" not in variant:
        raise RuntimeError("entry-delay-1 gate missing")
    if arm == "ENTRY_DELAY_2" and "gday < s.pending_signal_day+3" not in variant:
        raise RuntimeError("entry-delay-2 gate missing")
    if arm == "EXIT_DELAY_1":
        # Entry reservation timestamps are a separate, unchanged field.
        def entry_timestamps(source: str) -> list[str]:
            return [ast.dump(n) for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.Assign) and any(
                        isinstance(t, ast.Attribute) and t.attr == "pending_signal_day"
                        for t in n.targets)]
        if entry_timestamps(variant) != entry_timestamps(base):
            raise RuntimeError("entry reservation timestamp changed")
        for reason in ("stop", "review"):
            latch = ("s.pending_exit_signal_day=gday if not s.pending_sell else s.pending_exit_signal_day; "
                     f"s.pending_sell=True; s.sell_reason='{reason}'")
            if variant.count(latch) != 1:
                raise RuntimeError(f"latched {reason} timestamp missing or duplicated")
        if variant.count("pending_exit_signal_day:int=-1") != 1:
            raise RuntimeError("dedicated exit timestamp field missing or duplicated")
        if variant.count("s.pending_exit_signal_day=-1") != 4 or variant.count("_slot.pending_exit_signal_day=-1") != 1:
            raise RuntimeError("exit timestamp reset coverage changed")
        for marker in ("if not (0 <= s.pending_exit_signal_day < gday):",
                       "if gday < s.pending_exit_signal_day+2: continue",
                       "_exit_delay_events.append(",
                       "to_csv(OUT/'exit-delay-events.csv',index=False)"):
            if variant.count(marker) != 1:
                raise RuntimeError(f"exit-delay gate/witness missing or duplicated: {marker}")
    if arm == "RANK_TOP3_REVERSE":
        if "np.concatenate((durable[:3][::-1],durable[3:]))" not in variant:
            raise RuntimeError("rank perturbation missing")

    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried slot cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    return {
        "ENTRY_DELAY_1": ["caesar20", "entry_execution_delayed_one_additional_session"],
        "ENTRY_DELAY_2": ["caesar20", "entry_execution_delayed_two_additional_sessions"],
        "EXIT_DELAY_1": ["caesar20", "ordinary_stop_and_review_exit_delayed_one_additional_session"],
        "RANK_TOP3_REVERSE": ["caesar20", "causal_daily_top3_rank_order_reversed"],
        "COST_25BPS_RT": ["caesar20", "symmetric_cost_12p5bps_each_side_25bps_round_trip"],
        "COST_50BPS_RT": ["caesar20", "symmetric_cost_25bps_each_side_50bps_round_trip"],
    }[arm]
