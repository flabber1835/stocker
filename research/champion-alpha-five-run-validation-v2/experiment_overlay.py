#!/usr/bin/env python3
"""Frozen source overlays for the five corrected Champion alpha experiments.

The input must be the exact corrected one-session production-equivalent generated
source.  Every transformation is exact-count guarded and fail-closed.
"""
from __future__ import annotations

import ast

ARMS = (
    "FRESH_REPLACEMENT",
    "MULTI_REFILL",
    "EARLY_WEAK_REVIEW",
    "STAGED_RECOVERY",
    "COMBINED",
)


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def _fresh_replacement(text: str) -> str:
    text = _replace_exact(
        text, "s.ready_day=gday+COOLDOWN", "s.ready_day=gday", 3,
        "fresh-replacement ordinary/terminal slot release",
    )
    text = _replace_exact(
        text, "_slot.ready_day=gday+COOLDOWN", "_slot.ready_day=gday", 1,
        "fresh-replacement carried-terminal slot release",
    )
    return text


def _multi_refill(text: str) -> str:
    return _replace_exact(
        text,
        "budget=len(ready) if not book.initialized else 1",
        "budget=len(ready)",
        1,
        "multi-refill initialized admission budget",
    )


_OLD_REVIEW = """                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:\n                    s.pending_sell=True; s.sell_reason='stop'\n                elif age>=REVIEW_AGE and not s.reviewed and finite(px):\n                    qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)\n                    underwater=finite(s.entry_sig) and float(px)<s.entry_sig\n                    if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'\n                    else: s.reviewed=True\n"""

_NEW_REVIEW = """                if finite(px) and finite(s.peak) and s.peak>0 and float(px)<=s.peak*STOP_RET:\n                    s.pending_sell=True; s.sell_reason='stop'\n                else:\n                    if age>=59 and not s.early_reviewed and finite(px):\n                        qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)\n                        underwater=finite(s.entry_sig) and float(px)<s.entry_sig\n                        if underwater and not qualifies: s.pending_sell=True; s.sell_reason='early_review'\n                        else: s.early_reviewed=True\n                    if (not s.pending_sell) and age>=REVIEW_AGE and not s.reviewed and finite(px):\n                        qualifies=bool(inpool[s.tid] and finite(recent[s.tid]) and recent[s.tid]>=0)\n                        underwater=finite(s.entry_sig) and float(px)<s.entry_sig\n                        if underwater and not qualifies: s.pending_sell=True; s.sell_reason='review'\n                        else: s.reviewed=True\n"""


def _early_weak_review(text: str) -> str:
    text = _replace_exact(
        text,
        "entry_day:int=-1; reviewed:bool=False",
        "entry_day:int=-1; early_reviewed:bool=False; reviewed:bool=False",
        1,
        "early-review slot state",
    )
    before = text.count("s.entry_day=-1; s.reviewed=False;")
    if before != 3:
        raise RuntimeError(f"early-review s reset seam changed: expected 3, got {before}")
    text = text.replace(
        "s.entry_day=-1; s.reviewed=False;",
        "s.entry_day=-1; s.early_reviewed=False; s.reviewed=False;",
    )
    text = _replace_exact(
        text,
        "_slot.entry_day=-1; _slot.reviewed=False;",
        "_slot.entry_day=-1; _slot.early_reviewed=False; _slot.reviewed=False;",
        1,
        "early-review carried-terminal reset",
    )
    text = _replace_exact(
        text,
        "s.entry_day=gday; s.reviewed=False;",
        "s.entry_day=gday; s.early_reviewed=False; s.reviewed=False;",
        1,
        "early-review entry reset",
    )
    text = _replace_exact(text, _OLD_REVIEW, _NEW_REVIEW, 1, "early-review decision block")
    return text


_RECOVERY_CLASS = '''

class AlphaStagedRecovery:
    """Causal participation probe for baseline zero-allocation episodes."""
    def __init__(self):
        self.episode=False; self.reference=None; self.zero_sessions=0; self.qualifying_streak=0
        self.stage_25_sessions=0; self.stage_55_sessions=0; self.episode_resets=0

    def step(self, baseline_desired, spy_close, spy20, wc_r5, fast_signal):
        if baseline_desired>1e-12:
            if self.episode: self.episode_resets+=1
            self.episode=False; self.reference=None; self.zero_sessions=0; self.qualifying_streak=0
            return float(baseline_desired), 'BASELINE_POSITIVE'
        if not self.episode:
            if not finite(spy_close):
                raise RuntimeError('staged recovery missing causal SPY close at episode start')
            self.episode=True; self.reference=float(spy_close); self.zero_sessions=1; self.qualifying_streak=0
        else:
            self.zero_sessions+=1
        qualifying=(finite(spy_close) and float(spy_close)>float(self.reference)
                    and finite(spy20) and spy20>0
                    and finite(wc_r5) and wc_r5>0
                    and not bool(fast_signal))
        self.qualifying_streak=self.qualifying_streak+1 if qualifying else 0
        if self.zero_sessions>=10 and self.qualifying_streak>=10:
            self.stage_55_sessions+=1
            return 0.55, 'STAGED_RECOVERY_55'
        if self.zero_sessions>=10 and self.qualifying_streak>=5:
            self.stage_25_sessions+=1
            return 0.25, 'STAGED_RECOVERY_25'
        return 0.0, 'STAGED_RECOVERY_ZERO'
'''


def _staged_recovery(text: str) -> str:
    text = _replace_exact(
        text, "\nclass CandidateB:", _RECOVERY_CLASS + "\nclass CandidateB:", 1,
        "staged-recovery class insertion",
    )
    text = _replace_exact(
        text,
        "ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB()",
        "ctl=ControlLDRC(); ca=CandidateA(); cb=CandidateB(); alpha_recovery=AlphaStagedRecovery()",
        1,
        "staged-recovery state initialization",
    )
    text = _replace_exact(
        text,
        """            a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)\n            b_d,b_reason=cb.step(native_target,recent_r20,spy20)\n""",
        """            a_d,a_reason=ca.step(native_target,effective_native,dd,recent_r20,recent_r40,spy20,r20)\n            _spy_close=float(spy.loc[date,'closeadj']) if date in spy.index and finite(spy.loc[date,'closeadj']) else None\n            alpha_a_d,alpha_a_reason=alpha_recovery.step(a_d,_spy_close,spy20,r5,fastsig)\n            b_d,b_reason=cb.step(native_target,recent_r20,spy20)\n""",
        1,
        "staged-recovery causal step",
    )
    text = _replace_exact(
        text,
        "'control_reason':a_reason,'A_reason':a_reason,'B_reason':b_reason",
        "'control_reason':a_reason,'A_reason':alpha_a_reason,'B_reason':b_reason",
        1,
        "staged-recovery reason evidence",
    )
    text = _replace_exact(
        text,
        "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d",
        "pending_native=native_target; pend['control']=a_d; pend['A']=alpha_a_d; pend['B']=b_d",
        1,
        "staged-recovery A target",
    )
    text = _replace_exact(
        text,
        "'candidate_A_episodes':ca.episodes,'candidate_A_concordance_releases':ca.concordance_releases,'candidate_B_episodes':cb.episodes,'correlation_peer_stats':PEER_STATS,",
        "'candidate_A_episodes':ca.episodes,'candidate_A_concordance_releases':ca.concordance_releases,'candidate_B_episodes':cb.episodes,'alpha_recovery_state':alpha_recovery.__dict__,'correlation_peer_stats':PEER_STATS,",
        1,
        "staged-recovery summary evidence",
    )
    return text


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    out = text
    if arm in ("FRESH_REPLACEMENT", "COMBINED"):
        out = _fresh_replacement(out)
    if arm in ("MULTI_REFILL", "COMBINED"):
        out = _multi_refill(out)
    if arm in ("EARLY_WEAK_REVIEW", "COMBINED"):
        out = _early_weak_review(out)
    if arm in ("STAGED_RECOVERY", "COMBINED"):
        out = _staged_recovery(out)
    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError(arm)
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("variant lost exact one-session dividend scheduling")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    if "from backtester import champion_final_security_truth as _bestclass" not in variant:
        raise RuntimeError("factual classifier changed")
    if "COOLDOWN = 21" not in variant or "REVIEW_AGE = 119" not in variant:
        raise RuntimeError("certified constants unexpectedly changed")

    fresh = arm in ("FRESH_REPLACEMENT", "COMBINED")
    multi = arm in ("MULTI_REFILL", "COMBINED")
    early = arm in ("EARLY_WEAK_REVIEW", "COMBINED")
    recovery = arm in ("STAGED_RECOVERY", "COMBINED")

    if fresh:
        if "ready_day=gday+COOLDOWN" in variant:
            raise RuntimeError("slot cooldown remains in fresh-replacement arm")
        if variant.count("sec_ready[") < base.count("sec_ready["):
            raise RuntimeError("security-specific cooldown was removed")
    else:
        if variant.count("ready_day=gday+COOLDOWN") != base.count("ready_day=gday+COOLDOWN"):
            raise RuntimeError("slot cooldown changed in an unauthorized arm")

    has_budget = "budget=len(ready) if not book.initialized else 1" in variant
    if multi == has_budget:
        raise RuntimeError("initialized admission-budget arm mismatch")

    if early:
        if "early_reviewed:bool=False" not in variant or "sell_reason='early_review'" not in variant:
            raise RuntimeError("early-review state/decision missing")
        if "age>=REVIEW_AGE" not in variant:
            raise RuntimeError("original review boundary was removed")
    elif "early_reviewed" in variant:
        raise RuntimeError("early-review state leaked into another arm")

    if recovery:
        for marker in ("class AlphaStagedRecovery", "STAGED_RECOVERY_25", "STAGED_RECOVERY_55"):
            if marker not in variant:
                raise RuntimeError(f"staged-recovery marker missing: {marker}")
        if "pend['control']=a_d; pend['A']=alpha_a_d" not in variant:
            raise RuntimeError("staged recovery did not preserve baseline control allocation")
    elif "AlphaStagedRecovery" in variant:
        raise RuntimeError("staged-recovery state leaked into another arm")


def arm_dimensions(arm: str) -> list[str]:
    out = []
    if arm in ("FRESH_REPLACEMENT", "COMBINED"):
        out.append("slot_reuse_delay_21_to_0_security_cooldown_unchanged")
    if arm in ("MULTI_REFILL", "COMBINED"):
        out.append("initialized_admission_budget_1_to_all_ready_slots")
    if arm in ("EARLY_WEAK_REVIEW", "COMBINED"):
        out.append("additional_age_59_weak_review_original_age_119_preserved")
    if arm in ("STAGED_RECOVERY", "COMBINED"):
        out.append("causal_zero_episode_staged_25_55_recovery_overlay")
    return out
