#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pandas as pd

HERE = Path(__file__).resolve().parent
FORMAL_DIR = HERE.parents[0] / "wealth-core-v2-formal-ab-v1"
if str(FORMAL_DIR) not in sys.path:
    sys.path.insert(0, str(FORMAL_DIR))
import formal_ab

BASE_HEAD = "880209078f2b4817e837431984dc0ba0bf0b9d79"
FORMAL_TRIGGER_HEAD = "26b324f4da0f80cf790048103a0d92c1c0df3920"
FORMAL_RUN_ID = 34189070385
FORMAL_ARTIFACT_ID = 10042774099
DATASET_SHA256 = "5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993"
SP500_MEMBERSHIP_SHA256 = "1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d"
BUFFER_BPS = 10
BUFFER_FRAC = BUFFER_BPS / 10000.0
INITIAL_CAPITAL = 100_000.0


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_one(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected 1 seam, found {n}")
    return text.replace(old, new, 1)


def build_source(output: Path) -> tuple[str, str, str]:
    os.environ["WC_AB_VARIANT"] = "V2"
    _, transform = formal_ab._formal_transform()
    v1 = transform("fullpit", output)
    v2 = formal_ab.apply_v2_patch(v1)
    src = v2

    src = replace_one(
        src,
        "    cash:float=100_000_000.; receivables:list=field(default_factory=list)",
        "    cash:float=100_000.; receivables:list=field(default_factory=list)",
        "initial capital",
    )

    init_anchor = "actions,split_dates=load_actions(); spy,bil=load_funds(); book=Book(); native=Native()"
    init_block = r'''
    import csv as _sp500_csv, gzip as _sp500_gzip
    _sp500_by_date=defaultdict(set)
    _sp500_eligibility_path=Path(os.environ['SP500_PIT_ELIGIBILITY'])
    with _sp500_gzip.open(_sp500_eligibility_path,'rt',encoding='utf-8',newline='') as _fh:
        for _r in _sp500_csv.DictReader(_fh):
            _ds=str(_r['date'])[:10]; _sid=str(_r['security_id'])
            if _ds and _sid: _sp500_by_date[_ds].add(_sid)
    if not _sp500_by_date:
        raise RuntimeError('S&P 500 PIT eligibility tape is empty')
    _sp500_filter_sessions=0; _sp500_min_members=10**9; _sp500_max_members=0; _sp500_member_sum=0
'''
    src = replace_one(src, init_anchor, init_anchor + init_block, "S&P 500 PIT loader")

    src = replace_one(
        src,
        "            elig=_sec_ok&_base_elig",
        """            _sp500_ids=_sp500_by_date.get(ds)
            if not _sp500_ids:
                raise RuntimeError(f'S&P 500 PIT membership missing for market session {ds}')
            _sp500_ok=np.fromiter((str(sid[int(_tid)]) in _sp500_ids for _tid in tids),dtype=bool,count=len(tids))
            elig=_sec_ok&_base_elig&_sp500_ok
            _sp500_n=len(_sp500_ids); _sp500_filter_sessions+=1; _sp500_member_sum+=_sp500_n
            _sp500_min_members=min(_sp500_min_members,_sp500_n); _sp500_max_members=max(_sp500_max_members,_sp500_n)""",
        "S&P 500 eligibility filter",
    )

    counter_old = "rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0"
    counter_new = counter_old + "; nextopen_admissions=nextopen_blocks=nextopen_zero_qty=nextopen_cash_limited=nextopen_delayed=0; nextopen_max_delay=0; nextopen_rounding_underfill=0.; nextopen_reserved_dollars=0.; nextopen_executed_gross=0."
    src = replace_one(src, counter_old, counter_new, "next-open counters")

    src = replace_one(
        src,
        "target=eq*ENTRY_W; q=int(target//(float(px)*(1+COST))); required_cash=float(q)*float(px)*(1+COST)",
        f"target=eq*ENTRY_W; _buffer_required_close=max(0.,float(eq)*{BUFFER_FRAC!r}); required_cash=float(target)",
        "close-bound dollar intent",
    )

    close_old = (
        "                        if q<1: continue\n"
        "                        if required_cash>book.uncommitted_cash()+1e-8: slot_v2_rejected+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=float(q); s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1;"
    )
    close_new = (
        "                        _available_close=max(0.,book.uncommitted_cash()-_buffer_required_close)\n"
        "                        if required_cash>_available_close+1e-8: slot_v2_rejected+=1; continue\n"
        "                        s=ready[ad]; s.pending_tid=tid; s.pending_shares=0.; s.pending_signal_day=gday; s.reserved_cash=required_cash; slot_v2_reserved+=1; nextopen_admissions+=1; nextopen_reserved_dollars+=required_cash;"
    )
    src = replace_one(src, close_old, close_new, "10bp close admission and intent reservation")

    open_old = (
        "                    if _research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:\n"
        "                        continue\n"
        "                    afford=math.floor(s.reserved_cash/(float(px)*(1+COST))); q=min(int(round(s.pending_shares)),afford); slot_v2_gap_clipped+=int(q<int(round(s.pending_shares))); slot_v2_gap_cancelled+=int(q<1)"
    )
    open_new = (
        "                    _execution_budget=min(float(s.reserved_cash),float(book.cash)); q=math.floor(_execution_budget/(float(px)*(1+COST)))\n"
        "                    if q>=1 and _research_capacity_guard(q,_capacity_volumes.get(int(tid),()),security_id=str(sid[int(tid)]),session=ds,defer_excess=True) is None:\n"
        "                        continue\n"
        "                    nextopen_cash_limited+=int(float(book.cash)+1e-8<float(s.reserved_cash)); nextopen_zero_qty+=int(q<1); nextopen_blocks+=int(q<1); slot_v2_gap_cancelled+=int(q<1)"
    )
    src = replace_one(src, open_old, open_new, "next-open quantity determination")

    buy_old = "                        book.cash-=_gross; s.tid=tid; s.qty=float(q); s.entry_day=gday;"
    buy_new = (
        "                        _rounding=max(0.,float(_execution_budget)-float(_gross)); nextopen_rounding_underfill+=_rounding; nextopen_executed_gross+=float(_gross); "
        "_delay=max(0,int(gday)-int(s.pending_signal_day)-1); nextopen_delayed+=int(_delay>0); nextopen_max_delay=max(nextopen_max_delay,_delay); "
        "book.cash-=_gross; s.tid=tid; s.qty=float(q); s.entry_day=gday;"
    )
    src = replace_one(src, buy_old, buy_new, "execution telemetry")

    summary_old = "        'wealth_core_entry_funding':{'profile':'wealth-core-v2-full-whole-share-target-v1','reserved':slot_v2_reserved,'rejected_insufficient_uncommitted_cash':slot_v2_rejected,'gap_clipped':slot_v2_gap_clipped,'gap_cancelled':slot_v2_gap_cancelled},"
    summary_new = summary_old + (
        "\n        'wealth_core_next_open_sizing':{'profile':'wealth-core-v2-sp500-pit-next-open-whole-10bp-v1','initial_capital':100000.0,'buffer_basis_points':10,'buffer_role':'CLOSE_TIME_ADMISSION_CUSHION','share_quantity_bound_at_close':False,'whole_shares':True,'admissions':nextopen_admissions,'blocks':nextopen_blocks,'zero_quantity_blocks':nextopen_zero_qty,'cash_limited_open_executions':nextopen_cash_limited,'delayed_beyond_next_market_session':nextopen_delayed,'max_extra_market_session_delay':nextopen_max_delay,'rounding_underfill_dollars_total':nextopen_rounding_underfill,'reserved_dollars_total':nextopen_reserved_dollars,'executed_gross_total':nextopen_executed_gross},"
        "\n        'sp500_pit_filter':{'membership_dataset_hash':'1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d','formal_membership_certified':False,'best_effort_pit_membership':True,'sessions':_sp500_filter_sessions,'minimum_resolved_members':(_sp500_min_members if _sp500_filter_sessions else None),'average_resolved_members':(_sp500_member_sum/_sp500_filter_sessions if _sp500_filter_sessions else None),'maximum_resolved_members':(_sp500_max_members if _sp500_filter_sessions else None)},"
    )
    src = replace_one(src, summary_old, summary_new, "summary telemetry")

    if "afford=math.floor(s.reserved_cash/" in src:
        raise RuntimeError("close-bound share execution survived next-open patch")
    if "pending_shares=float(q)" in src:
        raise RuntimeError("close-bound pending share quantity survived next-open patch")
    compile(src, "<wealth-core-v2-sp500-next-open-10bp>", "exec")
    return v1, v2, src


def metrics(curve: pd.Series, dates: pd.Series) -> dict:
    c = pd.Series(curve.astype(float).to_numpy(), index=pd.to_datetime(dates)).dropna()
    rets = c.pct_change().dropna()
    years = (c.index[-1] - c.index[0]).days / 365.2425
    dd = c / c.cummax() - 1.0
    return {
        "start": str(c.index[0].date()), "end": str(c.index[-1].date()), "sessions": int(len(c)),
        "start_equity": float(c.iloc[0]), "end_equity": float(c.iloc[-1]),
        "ending_multiple": float(c.iloc[-1] / c.iloc[0]),
        "cagr": float((c.iloc[-1] / c.iloc[0]) ** (1.0 / years) - 1.0),
        "max_drawdown": float(dd.min()),
        "sharpe_daily_252": float(rets.mean() / rets.std(ddof=1) * (252.0 ** 0.5)) if rets.std(ddof=1) > 0 else None,
    }


def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument("--output", type=Path, required=True); p.add_argument("--self-test", action="store_true"); args = p.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)

    if args.self_test:
        prior = os.environ.get("CANONICAL_PIT_DATASET"); os.environ["CANONICAL_PIT_DATASET"] = "/tmp/source-generation-only-canonical-pit"
        try:
            v1, v2, src = build_source(Path("/tmp/wc-v2-sp500-next-open-selftest"))
            print(json.dumps({"status":"PASS","v1_sha256":hashlib.sha256(v1.encode()).hexdigest(),"v2_sha256":hashlib.sha256(v2.encode()).hexdigest(),"experiment_sha256":hashlib.sha256(src.encode()).hexdigest()}, sort_keys=True))
        finally:
            if prior is None: os.environ.pop("CANONICAL_PIT_DATASET", None)
            else: os.environ["CANONICAL_PIT_DATASET"] = prior
        return 0

    dataset = Path(os.environ["CANONICAL_PIT_DATASET"]); manifest = json.loads((dataset / "manifest.json").read_text())
    if manifest.get("dataset_hash") != DATASET_SHA256: raise RuntimeError("canonical PIT dataset hash mismatch")
    sp500_summary = json.loads(Path(os.environ["SP500_PIT_SUMMARY"]).read_text())
    if sp500_summary.get("membership_dataset_hash") != SP500_MEMBERSHIP_SHA256: raise RuntimeError("S&P 500 membership dataset hash mismatch")
    if sp500_summary.get("status") != "BEST_EFFORT_RUNNABLE": raise RuntimeError("S&P 500 PIT universe is not runnable")
    if sp500_summary.get("window_start") != "2006-01-03" or sp500_summary.get("window_end") != "2026-07-31": raise RuntimeError("S&P 500 PIT universe window mismatch")

    v1, v2, economic = build_source(out); audited, _ = formal_ab.install_audit(economic, variant="V2")
    compile(audited, "<wealth-core-v2-sp500-next-open-10bp-audited>", "exec")
    (out / "formal-v1-generated.py").write_text(v1); (out / "formal-v2-generated.py").write_text(v2); (out / "sp500-v2-next-open-10bp-generated.py").write_text(audited)
    module = types.ModuleType("wealth_core_v2_sp500_next_open_10bp"); module.__file__ = str(out / "sp500-v2-next-open-10bp-generated.py"); sys.modules[module.__name__] = module
    exec(compile(audited, module.__file__, "exec"), module.__dict__); module.run()

    summary = json.loads((out / "summary.json").read_text())
    if summary.get("canonical_pit_dataset_hash") != DATASET_SHA256: raise RuntimeError("replay summary lost canonical PIT binding")
    if summary.get("financial_grade_dividend_lag_sessions") != 1: raise RuntimeError("dividend lag changed")
    nx = summary.get("wealth_core_next_open_sizing") or {}
    observer = pd.read_csv(out / "wealth_core_daily_observer.csv"); daily = pd.read_csv(out / "daily.csv")
    if len(observer) != 5032 or len(daily) != 5032: raise RuntimeError(f"measurement session count mismatch: observer={len(observer)} daily={len(daily)}")
    wc = metrics(observer["wealth_core_equity"], observer["date"]); spy = metrics(daily["spy_nav"], daily["date"])
    pos = pd.read_csv(out / "wealth_core_position_lifecycle.csv"); entries = pos[pos["entry_event_type"].eq("ENTRY")].copy(); entry_weights = pd.to_numeric(entries["entry_open_portfolio_weight"], errors="coerce").dropna()
    blotter = pd.read_csv(out / "wealth_core_order_blotter.csv"); buy_orders = blotter[blotter["side"].eq("BUY")]; sell_orders = blotter[blotter["side"].eq("SELL")]

    result = {
        "schema": "research.wealth-core-v2-sp500-pit-next-open-10bp/1", "status": "PASS", "research_only": True, "base_head": BASE_HEAD,
        "formal_v2_authority": {"trigger_head": FORMAL_TRIGGER_HEAD, "run_id": FORMAL_RUN_ID, "artifact_id": FORMAL_ARTIFACT_ID},
        "canonical_pit_dataset_sha256": DATASET_SHA256,
        "sp500_membership": {"dataset_sha256": SP500_MEMBERSHIP_SHA256, "formal_pit_certified": False, "best_effort_pit": True, "summary": sp500_summary},
        "experiment": {"initial_capital": INITIAL_CAPITAL, "window": ["2006-07-31", "2026-07-31"], "warmup_start": "2006-01-03", "universe": "historical S&P 500 resolved PIT membership", "wealth_core": "V2", "buffer_basis_points": BUFFER_BPS, "sizing": "close-bound dollar intent; next-valid-open whole-share quantity determination", "share_quantity_bound_at_close": False, "whole_shares": True},
        "wealth_core_performance": wc, "spy_performance": spy,
        "execution": {**nx, "summary_buys": int(summary.get("buys", 0)), "summary_sells": int(summary.get("sells", 0)), "buy_orders": int(len(buy_orders)), "sell_orders": int(len(sell_orders)), "entry_episodes": int(len(entries)), "minimum_entry_open_weight": float(entry_weights.min()) if len(entry_weights) else None, "median_entry_open_weight": float(entry_weights.median()) if len(entry_weights) else None, "entries_below_1pct": int((entry_weights < 0.01).sum()), "entries_below_2pct": int((entry_weights < 0.02).sum()), "entries_below_3pct": int((entry_weights < 0.03).sum())},
        "integrity": {"financial_grade_dividend_lag_sessions": summary.get("financial_grade_dividend_lag_sessions"), "sp500_filter": summary.get("sp500_pit_filter"), "formal_v1_generated_sha256": hashlib.sha256(v1.encode()).hexdigest(), "formal_v2_generated_sha256": hashlib.sha256(v2.encode()).hexdigest(), "experiment_generated_sha256": hashlib.sha256(audited.encode()).hexdigest()},
    }
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    ins = f"""# Wealth Core V2 — S&P 500 PIT, 10 bp next-open sizing\n\n## Status\n\nPASS — research only. Historical S&P membership is the repository's best-effort PIT reconstruction; full-PIT market data, metadata, actions, terminal economics, and one-session dividend timing are preserved.\n\n## Design\n\n- Initial capital: $100,000\n- Measurement: 2006-07-31 through 2026-07-31\n- Universe: historical S&P 500 resolved membership\n- Wealth Core: V2\n- Cash cushion: 10 bp at close admission\n- Sizing: close binds ticker + dollar intent; whole-share quantity is determined from the actual next valid open\n- Close-bound share quantity: no\n\n## Headline result\n\n| Metric | Wealth Core V2 | SPY |\n|---|---:|---:|\n| CAGR | {wc['cagr']:.6%} | {spy['cagr']:.6%} |\n| Max DD | {wc['max_drawdown']:.6%} | {spy['max_drawdown']:.6%} |\n| Sharpe | {wc['sharpe_daily_252']:.6f} | {spy['sharpe_daily_252']:.6f} |\n| Ending multiple | {wc['ending_multiple']:.4f}x | {spy['ending_multiple']:.4f}x |\n\n## Execution\n\n- Admissions: {nx.get('admissions')}\n- Next-open zero-quantity blocks: {nx.get('zero_quantity_blocks')}\n- Delayed beyond the next market session: {nx.get('delayed_beyond_next_market_session')}\n- Maximum extra market-session delay: {nx.get('max_extra_market_session_delay')}\n- Cumulative whole-share rounding underfill: ${nx.get('rounding_underfill_dollars_total',0):,.2f}\n- Entry episodes: {len(entries)}\n- Entries below 1% portfolio weight: {int((entry_weights < 0.01).sum())}\n- Minimum entry-open weight: {(float(entry_weights.min()) if len(entry_weights) else float('nan')):.6%}\n\n## Interpretation\n\nThis experiment tests Wealth Core V2 with the execution contract discussed in research: bind economic intent at the close and determine the whole-share quantity only when the next valid opening price is known. Performance is reported as a path outcome, not used to tune the execution rule.\n"""
    (out / "INSIGHTS.md").write_text(ins)
    members = [p for p in sorted(out.iterdir()) if p.is_file() and p.name != "EXPERIMENT_SHA256SUMS.txt"]
    (out / "EXPERIMENT_SHA256SUMS.txt").write_text("".join(f"{sha(p)}  {p.name}\n" for p in members)); print(json.dumps(result, sort_keys=True), flush=True); return 0


if __name__ == "__main__":
    raise SystemExit(main())
