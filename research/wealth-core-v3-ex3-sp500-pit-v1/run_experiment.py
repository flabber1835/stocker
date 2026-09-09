#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
V3_DIR = HERE.parent / "median5-open-sizing-10bp-ex3-v1"
sys.path.insert(0, str(V3_DIR))

spec = importlib.util.spec_from_file_location("wealth_core_v3_base", V3_DIR / "run_experiment.py")
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load frozen Wealth Core V3 experiment harness")
base = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = base
spec.loader.exec_module(base)

_ORIGINAL_V3 = base.apply_open_time_whole_share_10bp
EXPECTED_MEMBERSHIP_DATASET_HASH = "1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source seam, found {count}")
    return text.replace(old, new, 1)


def _apply_sp500_pit_gate(text: str) -> str:
    marker = "MODE = os.environ.get('RESEARCH_REPLAY_MODE', 'nonpit')\nPIT_MODE = MODE == 'fullpit'"
    injected = marker + r'''
_SP500_ELIGIBILITY_PATH=Path(os.environ['SP500_BEST_EFFORT_ELIGIBILITY'])
_sp500_frame=pd.read_csv(_SP500_ELIGIBILITY_PATH,compression='gzip',dtype=str)
_sp500_frame['date']=_sp500_frame['date'].astype(str)
_sp500_frame['resolved_ticker']=_sp500_frame['resolved_ticker'].astype(str)
_sp500_frame['security_id']=_sp500_frame['security_id'].astype(str)
_SP500_BY_DATE={}
for _ds,_g in _sp500_frame.groupby('date',sort=False):
    _pairs={}
    for _r in _g.itertuples(index=False):
        _tk=str(_r.resolved_ticker); _sid=str(_r.security_id)
        _prior=_pairs.get(_tk)
        if _prior is not None and _prior != _sid:
            raise RuntimeError(f'conflicting S&P security IDs for {_tk} on {_ds}: {_prior} vs {_sid}')
        _pairs[_tk]=_sid
    _SP500_BY_DATE[str(_ds)]=_pairs
_SP500_ALL_TICKERS=set(_sp500_frame['resolved_ticker'].astype(str))
_SP500_SEEN_SID={}

def sp500_security_id(ticker_value,ds):
    _tk=str(ticker_value)
    _sid=_SP500_BY_DATE.get(str(ds),{}).get(_tk)
    if _sid is not None:
        _SP500_SEEN_SID[_tk]=_sid
        return _sid
    _sid=_SP500_SEEN_SID.get(_tk)
    return _sid if _sid is not None else f'TICKER:{_tk}'
'''
    text = _replace_once(text, marker, injected, "S&P universe load")

    old_init = (
        "    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n"
        "    pit_model=None"
    )
    new_init = (
        "    tick,tmap,sid,common,sector,exchange,firstdate,lastdate,issuer=load_meta(); n=len(tick)\n"
        "    _missing_sp500=sorted(_SP500_ALL_TICKERS-set(map(str,tick)))\n"
        "    if _missing_sp500: raise RuntimeError(f'S&P mapped tickers absent from canonical replay index: {_missing_sp500[:20]}')\n"
        "    pit_model=None"
    )
    text = _replace_once(text, old_init, new_init, "S&P ticker-index witness")

    old_elig = (
        "elig=common[tids]&listed&continuous&np.isfinite(mm)&np.isfinite(rr)&"
        "np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&"
        "np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    )
    new_elig = (
        "_sp500_today=_SP500_BY_DATE.get(ds,{})\n"
        "            _sp500_ok=np.array([str(tick[int(_i)]) in _sp500_today for _i in tids],dtype=bool)\n"
        "            elig=_sp500_ok&continuous&np.isfinite(mm)&np.isfinite(rr)&"
        "np.isfinite(cu)&(cu>=MIN_PRICE)&np.isfinite(av)&(av>=MIN_ADV20)&"
        "np.isfinite(dv)&(dv>=MIN_DAY_DV)&np.isfinite(sc)&(fvol>0)"
    )
    text = _replace_once(text, old_elig, new_elig, "dated S&P eligibility gate")

    text = _replace_once(
        text,
        "sid_et=sid[et]; ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]",
        "sid_et=np.array([sp500_security_id(tick[int(_i)],ds) for _i in et],dtype=object); ordm=np.lexsort((sid_et,-mom[et])); rawall=et[ordm]",
        "causal S&P momentum tie-break",
    )
    text = _replace_once(
        text,
        "ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]",
        "_pool_sid=np.array([sp500_security_id(tick[int(_i)],ds) for _i in pool],dtype=object); ordscore=np.lexsort((tick[pool],_pool_sid,-score[pool])); durable=pool[ordscore]",
        "causal S&P score tie-break",
    )
    text = _replace_once(
        text,
        "return pit_model.group(str(sid[tid]), str(ds), str(tick[tid]))",
        "return pit_model.group(sp500_security_id(tick[tid],ds), str(ds), str(tick[tid]))",
        "causal S&P sector security key",
    )
    text = _replace_once(
        text,
        "return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sid[tid]}'",
        "return f'SEC_CIK:{cik}' if cik is not None else f'SEC_UNKNOWN:{sp500_security_id(tick[tid],ds)}'",
        "causal S&P issuer singleton",
    )
    return text


def _v3_plus_sp500(source: str) -> str:
    return _apply_sp500_pit_gate(_ORIGINAL_V3(source))


base.apply_open_time_whole_share_10bp = _v3_plus_sp500


def main() -> int:
    summary_path = Path(os.environ["SP500_UNIVERSE_SUMMARY"])
    universe = json.loads(summary_path.read_text(encoding="utf-8"))
    if universe.get("status") != "BEST_EFFORT_RUNNABLE":
        raise RuntimeError("S&P best-effort PIT universe is not runnable")
    if universe.get("membership_dataset_hash") != EXPECTED_MEMBERSHIP_DATASET_HASH:
        raise RuntimeError("S&P membership dataset hash changed")
    if universe.get("window_start") != "2006-07-31" or universe.get("window_end") != "2026-07-31":
        raise RuntimeError("S&P universe measurement window changed")

    rc = base.main()
    if rc != 0:
        return rc

    try:
        out = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
    except (ValueError, IndexError) as exc:
        raise RuntimeError("cannot locate V3 output path") from exc
    result_path = out / "RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["schema"] = "research.wealth-core-v3-ex3-sp500-pit/1"
    result["economic_scope"] = "WEALTH_CORE_V3_PLUS_PARALLEL_EX3_ON_SP500_PIT"
    result["universe"] = {
        "name": "S&P 500",
        "method": "DATED_BEST_EFFORT_PIT_MEMBERSHIP_WITH_CAUSAL_IDENTITY_RESOLUTION",
        "membership_dataset_hash": universe["membership_dataset_hash"],
        "window_start": universe["window_start"],
        "window_end": universe["window_end"],
        "formal_pit_certified": False,
        "best_effort_pit": True,
        "source_summary": universe,
    }
    result["formal_pit_certified"] = False
    result["best_effort_pit_universe"] = True
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("[WEALTH_CORE_V3_EX3_SP500_RESULT] " + json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
