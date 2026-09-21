"""Registered controller-input probes, with no historical data or optimizer."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform

import numpy as np

from sentinel.controller.champion_frozen import CandidateA, Native


@dataclass(frozen=True)
class Input:
    nav: float
    damage: float
    green: float
    spy20: float
    volacc: float


def scenarios():
    """Prespecified shape families; numbers are probes, not market estimates."""
    healthy = Input(100., .2, .6, .02, 0.)
    warm = [healthy] * 60
    # Saturation predates both the delta window and the confirmation memory.
    damaged_warm = warm[:-10] + [Input(100., .9, .1, .02, 0.)] * 10
    stress = Input(88., 1., 0., -.04, .2)
    return {
        "abrupt_shock": warm + [stress] * 40,
        "already_damaged": damaged_warm + [stress] * 40,
        "market_confirmation_late": warm + [Input(88., 1., 0., -.04, -.2)] * 6 + [stress] * 34,
        # Renewed price loss keeps the current short-return gate true, so this
        # case isolates expiry rather than passing because another gate fails.
        "market_confirmation_expired": warm + [Input(88., 1., 0., -.04, -.2)] * 10 + [Input(82.,1.,0.,-.04,.2)] * 30,
        "gradual_decline": warm + [Input(100.-.5*(i+1), .9, .1, -.04, 0.) for i in range(40)] + [Input(80.,.9,.1,-.04,0.)]*40,
        "deep_plateau": damaged_warm + [Input(80., 1., 0., -.04, 0.)] * 60,
        "four_session_correction": damaged_warm + [stress] * 4 + [healthy] * 36,
        "eight_session_correction": damaged_warm + [stress] * 8 + [healthy] * 32,
        "healthy": warm + [healthy] * 40,
    }


def observations(path):
    peak = 0.
    for i, p in enumerate(path):
        peak = max(peak, p.nav)
        def ret(n):
            return p.nav / path[i-n].nav - 1 if i >= n else None
        yield (p.nav/peak-1, ret(5), ret(10), ret(20), ret(40),
               p.damage, p.green, p.damage-path[i-5].damage if i >= 5 else None,
               p.spy20, p.volacc, 0, p.nav)


def entry_probes(obs):
    """Eligibility only: no portfolio, recovery, execution or P&L alternative."""
    history, streak, rows = [], 0, []
    for ob in obs:
        dd, r5, r10, _, _, damage, green, delta, spy, vol, _, _ = ob
        short = (r5 is not None and r5 <= -.05) or (r10 is not None and r10 <= -.08)
        confirm = spy <= -.01 or (r10 is not None and r10 <= -.1)
        level = dd <= -.1 and damage >= .88 and green <= .2 and confirm
        acceleration = delta is not None and delta >= .3
        volatility = vol >= .04
        history = (history + [(acceleration, volatility)])[-5:]
        streak = streak + 1 if level else 0
        rows.append({
            "drop_damage_acceleration": bool(level and short and volatility),
            "five_session_confirmation_memory": bool(level and short and
                any(x[0] for x in history) and any(x[1] for x in history)),
            "persistent_impairment_addition": streak >= 5,
        })
    return rows


def run_paths():
    results = {}
    for name, path in scenarios().items():
        obs = list(observations(path))
        probes = entry_probes(obs)
        native, restart = Native(), Native()
        records = []
        for i, ob in enumerate(obs):
            output = native.step(ob)
            restored_output = restart.step(ob)
            assert restored_output == output and restart.snapshot() == native.snapshot()
            restart = Native.from_snapshot(json.loads(json.dumps(restart.snapshot())))
            if i < 60:
                continue
            target, fast, slow = output
            records.append({"session": i-60, "nav": path[i].nav,
                "drawdown": ob[0], "damage": ob[5], "damage_delta5": ob[7],
                "volacc": ob[9], "native_target": target, "fast": fast, "slow": slow,
                "base_duration": native.base_dur, "base_anchor": native.base_anchor,
                **probes[i]})
        def first(key, value=True):
            return next((r["session"] for r in records if r[key] == value), None)
        results[name] = {"first_native_defense_close": first("native_target", 0.),
            "first_fast_signal": first("fast"), "first_slow_signal": first("slow"),
            "alternative_first_eligibility_close": {key:first(key) for key in probes[0]},
            "trace": records}
    return results


def saturation_grid():
    rows=[]
    for n in (5,10,20):
        for prior_count in range(n+1):
            prior=prior_count/n
            delta=1-prior
            ob=(-.12,-.08,-.12,-.08,-.10,1.,0.,delta,-.04,.2,0,88.)
            target,fast,slow=Native().step(ob)
            rows.append({"held":n,"prior_damaged":prior_count,
                "max_attainable_delta":delta,"fast":fast,"target":target})
    return rows


def recovery_probes():
    results={}
    for name,core,recent20,recent40 in [
        ("weak_core_strong_leadership",-.10,.02,.02),
        ("strong_core_weak_leadership",.10,-.02,-.05),
    ]:
        candidate=CandidateA()
        uninterrupted=CandidateA()
        candidate.step(0.,1.,-.2,-.02,-.05,-.04,core)
        uninterrupted.step(0.,1.,-.2,-.02,-.05,-.04,core)
        rows=[]
        for i in range(1,11):
            target,reason=candidate.step(1.,1.,-.2,recent20,recent40,-.04,core)
            assert (target,reason)==uninterrupted.step(1.,1.,-.2,recent20,recent40,-.04,core)
            assert candidate.snapshot()==uninterrupted.snapshot()
            restored=CandidateA.from_snapshot(json.loads(json.dumps(candidate.snapshot())))
            assert restored.snapshot()==candidate.snapshot()
            candidate=restored
            rows.append({"native_full_session":i,"target":target,"reason":reason})
        results[name]={"core_r20":core,"leadership_r20":recent20,
            "leadership_r40":recent40,"trace":rows}
    return results


def build_report():
    from .holdings import capital_probe, turnover_probe
    root=Path(__file__).resolve().parents[2]
    files=["sentinel/controller/champion_frozen.py",
           "sentinel/controller/median5_breadth.py", "sentinel/breadth/classifier.py",
           "sentinel/core/kernel.py", "shared/stock_strategy_shared/wealth_core/median5.py",
           "shared/stock_strategy_shared/wealth_core/v5.py",
           "shared/stock_strategy_shared/wealth_core/adapter.py",
           "shared/stock_strategy_shared/wealth_core/engine.py",
           "shared/stock_strategy_shared/wealth_core/state.py",
           "research/impedance/study.py", "research/impedance/holdings.py",
           "research/impedance/test_study.py", "research/impedance/mutations.py"]
    return {"schema":"sentinel.impedance-diagnostics/1",
        "base":"da7b64a9429c9c73fb7efac90c8d4a5decb39e13",
        "scope":"Synthetic component/interface diagnostics; no strategy promotion or historical performance claim.",
        "runtime":{"python":platform.python_version(),"numpy":np.__version__},
        "hash_convention":"UTF-8 source text with universal-newline normalization; not a complete dependency lock",
        "source_sha256":{p:hashlib.sha256((root/p).read_text(encoding='utf-8').encode()).hexdigest() for p in files},
        "paths":run_paths(),"saturation":saturation_grid(),
        "capital":capital_probe(),"turnover":turnover_probe(),"recovery":recovery_probes()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    report=build_report()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({name:{k:v for k,v in r.items() if k!='trace'} for name,r in report['paths'].items()},indent=2))
    print(json.dumps({k:report[k] for k in ['capital','turnover']},indent=2))


if __name__=="__main__":
    main()
