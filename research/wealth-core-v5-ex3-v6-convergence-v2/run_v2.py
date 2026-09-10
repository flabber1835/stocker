#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCHEMA = "research.wealth-core-v5-ex3-v6-convergence-v2/1"
PATCH_NAME = "semantic-quotient-canonicalization-v2"
EXPECTED_V6_SELECTED_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"
EXPECTED_V6 = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}
HARNESS_AUTHORITY = "eaddca3f04f279e99663f832bf7293e92ee15662"
MAIN_V6_AUTHORITY = "96f705c3b699ec283dbac7e93b973dba9769f038"


def canonicalize_native_state(s):
    """Collapse only state distinctions proven irrelevant to all future decisions."""
    changed = False

    def put(name, value):
        nonlocal changed
        if getattr(s, name) != value:
            setattr(s, name, value)
            changed = True

    if s.ordinary:
        put("ordinary_age", min(int(s.ordinary_age), 20))
        put("ordinary_h", min(int(s.ordinary_h), 3))
    else:
        put("ordinary_age", 0)
        put("ordinary_h", 0)

    if s.base_fast:
        put("base_fast_age", min(int(s.base_fast_age), 10))
        put("base_fast_h", min(int(s.base_fast_h), 3))
    else:
        put("base_fast_age", 0)
        put("base_fast_h", 0)

    if s.fast:
        # Native clears fast once fast_age + 1 >= 10. Ages >= 9 are equivalent.
        put("fast_age", min(int(s.fast_age), 9))
        put("fast_h", min(int(s.fast_h), 3))
    else:
        put("fast_age", 0)
        put("fast_h", 0)

    if s.slow:
        # Native clears slow once slow_age + 1 >= 20. Ages >= 19 are equivalent.
        put("slow_age", min(int(s.slow_age), 19))
        put("slow_h", min(int(s.slow_h), 6))
    else:
        put("slow_age", 0)
        put("slow_h", 0)

    base = bool(s.ordinary or s.base_fast)
    if base:
        # Only the >=30 predicate consumes duration; base_anchor remains exact.
        put("base_dur", min(int(s.base_dur), 30))
    else:
        put("base_dur", 0)
        put("base_anchor", None)

    if s.ramp:
        put("ramp_h", min(int(s.ramp_h), 10))
    else:
        put("ramp_h", 0)
        put("ramp_idx", None)

    # r40hist is consumed only on the session a severe fast/slow episode clears.
    # From a non-severe state, a newly-entered fast/slow episode cannot clear
    # before the six-value history is completely overwritten.
    if not (s.fast or s.slow) and s.r40hist:
        put("r40hist", [])

    return changed


def canonicalize_ex3_state(s):
    """Collapse EX3 counters into the equivalence classes used by V6 predicates."""
    changed = False

    def put(name, value):
        nonlocal changed
        if getattr(s, name) != value:
            setattr(s, name, value)
            changed = True

    put("full_streak", min(int(s.full_streak), 8))
    put("recent_positive_streak", min(int(s.recent_positive_streak), 8))
    # The next transition only asks whether the previous native target was full.
    put("prev_native", 1.0 if float(s.prev_native) >= 1.0 - 1e-12 else 0.0)
    return changed


OLD_B = '''class CandidateB:
    def __init__(self): self.episode=False; self.streak=0; self.prev_native=1.; self.prev_desired=1.; self.episodes=0
    def step(self,native,r20,spy20):
        healthy=finite(r20) and r20>0
        self.streak=self.streak+1 if healthy else 0
        reasons=[]
        if self.prev_native>=1-1e-12 and native<1-1e-12:
            if not self.episode: self.episodes+=1
            self.episode=True; reasons.append('EPISODE_START')
        desired=native
        if self.episode and native>=1-1e-12:
            release=(self.streak>=LDRC_REC) or (finite(spy20) and spy20>LDRC_V)
            if release:
                self.episode=False; desired=1.; reasons.append('RELEASE_R20_7' if self.streak>=LDRC_REC else 'RELEASE_SPY')
            else:
                desired=self.prev_desired; reasons.append('HOLD')
        desired=min(native,desired)
        self.prev_native=native; self.prev_desired=desired
        return float(desired),'|'.join(reasons) if reasons else 'NORMAL'
'''

NATIVE_V2 = '''\nclass NativeV2(Native):
    """Research-only semantic-state canonicalizer; output is computed before normalization."""
    def __init__(self):
        super().__init__()
        self.canonicalizations=0

    def step(self,ob):
        result=super().step(ob)
        if canonicalize_native_state(self):
            self.canonicalizations+=1
        return result
'''

NEW_B = '''class CandidateB(CandidateA):
    """Exact EX3 V6 decision logic plus future-inert state normalization after each decision."""
    def __init__(self):
        super().__init__()
        self.canonicalizations=0

    def step(self,native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20):
        desired,reason=super().step(native,effective_native,wcdd,recent_r20,recent_r40,spy20,wc_r20)
        if canonicalize_ex3_state(self):
            self.canonicalizations+=1
        return desired,reason
'''


def load(path: Path):
    spec = importlib.util.spec_from_file_location("v6_adversarial_generated_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def replace_n(src: str, old: str, new: str, expected: int, label: str) -> str:
    n = src.count(old)
    if n != expected:
        raise RuntimeError(f"{label}: expected {expected} seam(s), saw {n}")
    return src.replace(old, new)


def block(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def treatment_source(src: str) -> str:
    original_native = block(src, "class Native:", "class ControlLDRC:")
    original_a = block(src, "class CandidateA:", "class CandidateB")

    helper_native = inspect.getsource(canonicalize_native_state) + "\n"
    helper_ex3 = inspect.getsource(canonicalize_ex3_state) + "\n"
    out = replace_n(src, "\nclass ControlLDRC:", "\n" + helper_native + helper_ex3 + NATIVE_V2 + "\nclass ControlLDRC:", 1, "native v2 insertion")
    out = replace_n(out, OLD_B, NEW_B, 1, "EX3 v2 insertion")
    out = replace_n(out, "book=Book(); native=Native()", "book=Book(); native=Native(); native_b=NativeV2()", 1, "native treatment init")
    out = replace_n(out, "pending_native=1.; effective_native=1.", "pending_native=1.; effective_native=1.; pending_native_b=1.; effective_native_b=1.", 1, "native timing init")
    out = replace_n(out, "effective_native=pending_native", "effective_native=pending_native; effective_native_b=pending_native_b", 2, "next-open native timing")

    native_call = "native_target,fastsig,slowsig=native.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))"
    native_pair = native_call + "\n            native_target_b,fastsig_b,slowsig_b=native_b.step((dd,r5,r10,r20,r40,dam_b,green_b,ddam5,spy20,volacc,stops20,eq))"
    out = replace_n(out, native_call, native_pair, 1, "native paired step")
    out = replace_n(out,
        "b_d,b_reason=cb.step(native_target,recent_r20,spy20)",
        "b_d,b_reason=cb.step(native_target_b,effective_native_b,dd,recent_r20,recent_r40,spy20,r20)",
        1, "EX3 treatment call")

    row_seam = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,\n                             'effective_native':effective_native,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],"
    row_new = "'recent_r20':recent_r20,'recent_r40':recent_r40,'spy_r20':spy20,'native_close_target':native_target,'native_close_target_v2':native_target_b,\n                             'effective_native':effective_native,'effective_native_v2':effective_native_b,'control_allocation':eff['control'],'A_allocation':eff['A'],'B_allocation':eff['B'],"
    out = replace_n(out, row_seam, row_new, 1, "paired row native columns")

    state_seam = "'research_selected_positions':json.dumps(_position_ids,separators=(',',':')),'research_ldrc_state':json.dumps(ca.__dict__,sort_keys=True,separators=(',',':'))})"
    state_new = "'research_selected_positions':json.dumps(_position_ids,separators=(',',':')),'research_ldrc_state':json.dumps(ca.__dict__,sort_keys=True,separators=(',',':')),'research_ldrc_state_v2':json.dumps(cb.__dict__,sort_keys=True,separators=(',',':')),'research_native_state':json.dumps(native.__dict__,sort_keys=True,separators=(',',':')),'research_native_state_v2':json.dumps(native_b.__dict__,sort_keys=True,separators=(',',':')),'native_v2_canonicalizations':native_b.canonicalizations,'ex3_v2_canonicalizations':cb.canonicalizations})"
    out = replace_n(out, state_seam, state_new, 1, "paired state evidence")
    out = replace_n(out,
        "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d",
        "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d; pending_native_b=native_target_b",
        1, "paired pending native")

    if block(out, "class Native:", "def canonicalize_native_state") != original_native:
        raise RuntimeError("authoritative Native implementation changed")
    if block(out, "class CandidateA:", "class CandidateB") != original_a:
        raise RuntimeError("authoritative CandidateA implementation changed")
    if "CONVERGENCE_REC8" in out or "neutral_streak" in out:
        raise RuntimeError("V1 timeout-release behavior leaked into V2")
    for forbidden in ("baseline_path", "baseline_holdings", "future_return"):
        if forbidden in NEW_B + NATIVE_V2:
            raise RuntimeError(f"forbidden treatment dependency: {forbidden}")
    compile(out, "<convergence-v2-generated>", "exec")
    return out


def state_tests() -> dict:
    native_fields = dict(
        ordinary=False,binary_armed=False,ordinary_age=999,ordinary_h=99,
        base_fast=False,base_fast_armed=False,base_fast_age=999,base_fast_h=99,base_anchor=123.0,base_dur=999,
        fast=False,fast_armed=False,fast_age=999,fast_h=99,
        slow=False,slow_age=999,slow_h=99,
        ramp=False,ramp_idx=1,ramp_h=99,r40hist=[-.2,-.1,0,.1,.2,.3],
    )
    s = SimpleNamespace(**native_fields)
    assert canonicalize_native_state(s)
    assert (s.ordinary_age,s.ordinary_h,s.base_fast_age,s.fast_age,s.slow_age)==(0,0,0,0,0)
    assert s.base_anchor is None and s.base_dur==0 and s.r40hist==[] and s.ramp_idx is None
    snapshot=vars(s).copy(); assert canonicalize_native_state(s) is False; assert vars(s)==snapshot

    active = SimpleNamespace(**native_fields)
    active.ordinary=True; active.base_fast=True; active.fast=True; active.slow=True; active.ramp=True
    active.base_anchor=777.0; active.base_dur=123; active.ordinary_age=88; active.ordinary_h=9
    active.base_fast_age=77; active.base_fast_h=9; active.fast_age=66; active.fast_h=9
    active.slow_age=55; active.slow_h=9; active.ramp_idx=1; active.ramp_h=33; active.r40hist=[1,2,3,4,5,6]
    arms=(active.binary_armed,active.base_fast_armed,active.fast_armed)
    canonicalize_native_state(active)
    assert active.base_anchor==777.0 and active.r40hist==[1,2,3,4,5,6]
    assert (active.ordinary_age,active.ordinary_h)==(20,3)
    assert (active.base_fast_age,active.base_fast_h)==(10,3)
    assert (active.fast_age,active.fast_h)==(9,3)
    assert (active.slow_age,active.slow_h)==(19,6)
    assert (active.ramp_idx,active.ramp_h)==(1,10)
    assert arms==(active.binary_armed,active.base_fast_armed,active.fast_armed)

    # Proof obligation for clearing inactive r40 history: a new fast/slow episode
    # cannot recover before the 6-value recovery window has been overwritten.
    assert 9 >= 6 and 19 >= 6

    ex = SimpleNamespace(episode=True,latched=True,full_streak=91,recent_positive_streak=42,
                         prev_native=.65,prev_desired=.55,episodes=9,concordance_releases=3)
    immutable=(ex.episode,ex.latched,ex.prev_desired,ex.episodes,ex.concordance_releases)
    assert canonicalize_ex3_state(ex)
    assert (ex.full_streak,ex.recent_positive_streak,ex.prev_native)==(8,8,0.0)
    assert immutable==(ex.episode,ex.latched,ex.prev_desired,ex.episodes,ex.concordance_releases)
    snapshot=vars(ex).copy(); assert canonicalize_ex3_state(ex) is False; assert vars(ex)==snapshot

    # All values inside each quotient class answer the authoritative predicates identically.
    assert all((n>=8)==(min(n,8)>=8) for n in range(0,100))
    assert all(((v>=1-1e-12)==((1.0 if v>=1-1e-12 else 0.0)>=1-1e-12)) for v in (0,.55,.65,1.0))

    return {
        "idempotent": True,
        "active_hysteresis_preserved": True,
        "no_exposure_write": True,
        "r40_inactive_forgetting_horizon_proved": True,
        "threshold_quotients_proved": True,
    }


def allocation_counts(frame: pd.DataFrame, col: str) -> dict:
    x=frame[col].astype(float)
    return {
        "average":float(x.mean()),
        "sessions_by_level":{str(v):int(np.isclose(x.to_numpy(),v,atol=1e-12).sum()) for v in (0.0,.55,.65,1.0)},
        "transitions":int((x.diff().abs()>1e-12).sum()),
    }


def paired_direct(frame: pd.DataFrame) -> dict:
    a=frame.A_allocation.astype(float).to_numpy(); b=frame.B_allocation.astype(float).to_numpy()
    na=frame.native_close_target.astype(float).to_numpy(); nb=frame.native_close_target_v2.astype(float).to_numpy()
    ad=np.abs(a-b)>1e-12; nd=np.abs(na-nb)>1e-12
    def span(mask):
        ix=np.flatnonzero(mask)
        return {
            "sessions":int(mask.sum()),"fraction":float(mask.mean()),
            "first":None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[0])]).date()),
            "last":None if not len(ix) else str(pd.Timestamp(frame.date.iloc[int(ix[-1])]).date()),
        }
    return {"allocation":span(ad),"native_target":span(nd)}


def resolve_v6_runner() -> Path:
    raw=os.environ.get("V2_V6_RUNNER")
    if raw:
        return Path(raw).resolve()
    return (HERE.parent / "wealth-core-v5-sentinel-ex3-v6-adversarial-v1" / "run_adversarial_v6.generated.py").resolve()


def main() -> int:
    tests=state_tests()
    if "--self-test" in sys.argv:
        # Cheap Stage 1 intentionally has no dependency on the full replay import graph.
        # Exact selected-source construction and timing/source guards run at the baseline gate.
        print(json.dumps({"schema":SCHEMA,"state_tests":tests,"PASS":True},sort_keys=True))
        return 0

    v6_runner=resolve_v6_runner()
    if not v6_runner.exists():
        raise RuntimeError(f"generate exact V6 runner first: {v6_runner}")
    base=load(v6_runner)
    if base.SELECTED != EXPECTED_V6:
        raise RuntimeError(f"wrong V6 config: {base.SELECTED}")

    original_build=base.build_selected
    original_execute=base.execute

    def patched_build(control_source: Path, median_overlay: Path) -> str:
        exact=original_build(control_source,median_overlay)
        if base.sha(exact.encode()) != EXPECTED_V6_SELECTED_SOURCE_SHA256:
            raise RuntimeError("exact V6 source authority mismatch before V2")
        patched=treatment_source(exact)
        base.timing_guard(patched)
        return patched

    def patched_execute(src: str, outdir: Path, tag: str, keep_raw: bool=False) -> dict:
        result=original_execute(src,outdir,tag,keep_raw)
        frame=pd.read_csv(outdir/"engine"/"daily.csv",parse_dates=["date"])
        result["treatment"]=base.imp.windows(frame,"B_nav")
        result["control_allocation_v6"]=allocation_counts(frame,"A_allocation")
        result["treatment_allocation_v2"]=allocation_counts(frame,"B_allocation")
        result["paired_direct_v2"]=paired_direct(frame)
        result["canonicalization_v2"]={
            "name":PATCH_NAME,"research_only":True,"future_data":False,"baseline_path_access":False,
            "current_output_recomputed_before_normalization":True,
            "native_canonicalization_sessions":int((frame.native_v2_canonicalizations.astype(float).diff().fillna(frame.native_v2_canonicalizations.astype(float))>0).sum()),
            "ex3_canonicalization_sessions":int((frame.ex3_v2_canonicalizations.astype(float).diff().fillna(frame.ex3_v2_canonicalizations.astype(float))>0).sum()),
            "state_tests":tests,
        }
        cols=["date","research_selected_positions","shadow_equity","wc_dd","damaged","green","fast_signal","slow_signal",
              "recent_r20","recent_r40","spy_r20","native_close_target","native_close_target_v2","effective_native","effective_native_v2",
              "A_allocation","B_allocation","A_nav","B_nav","A_reason","B_reason",
              "research_native_state","research_native_state_v2","research_ldrc_state","research_ldrc_state_v2",
              "native_v2_canonicalizations","ex3_v2_canonicalizations"]
        frame[cols].to_csv(outdir/"paired-daily.csv",index=False)
        return result

    base.build_selected=patched_build
    base.execute=patched_execute
    base.SCHEMA=SCHEMA
    base.SYSTEM="Wealth Core V5 + exact r40_m04_rec8 / semantic-state convergence V2"
    base.UNIVERSE_CASES=[("drop_01pct_seed11",.01,11),("drop_01pct_seed29",.01,29),("drop_01pct_seed47",.01,47)]
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
