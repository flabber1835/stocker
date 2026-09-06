#!/usr/bin/env python3
"""Frozen V2 SPY/IWV index-observation comparison. RESEARCH / NOT CERTIFIED."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backtester import research_champion_market_risk_full_replay_v2 as v2
from backtester import research_champion_market_risk_full_replay as legacy
from backtester import research_champion_corrected_classification as corrected
from backtester import run_research_champion_pit_closure_20y as closure

_BASE_INSTALL = v2.install
STATUS = 'RESEARCH / NOT CERTIFIED'
BASELINE_SHA = 'fbc8a18d2e6f01bbc5154fe359990633bbe93e28b4dbeba57da0be149f4811a8'
IWV_SHA = 'ec57f38bc206466524091c31d0e73edc5b51cb115cfba4e26b62d2c44f712ce9'
VIX_SHA = '9bf13a7d758cd0727e3fb68d50a32715d6201ed7f0cd220841ecfe2a4901ee4b'
PARAMETERS = {
    'spy-center': dict(ratio_healthy=1.0, ratio_stress=1.15, rv20_healthy=0.20, rv20_stress=0.26),
    'iwv-center': dict(ratio_healthy=1.0, ratio_stress=1.15, rv20_healthy=0.19, rv20_stress=0.22),
}
INDEX_COLUMNS = ['comparison_r20', 'comparison_r40', 'comparison_dd', 'comparison_rv20', 'comparison_volratio']


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def authenticate(path: Path, expected: str) -> None:
    if sha256(path) != expected:
        raise RuntimeError(f'input digest mismatch: {path.name}')


def load_iwv_features(path: Path) -> pd.DataFrame:
    """Use only the retained cutoff witness; compute trailing close features."""
    authenticate(path, IWV_SHA)
    raw = pd.read_csv(path)
    if list(raw.columns) != ['date', 'iwv_close']:
        raise RuntimeError('IWV witness schema changed')
    dates = pd.to_datetime(raw.date, errors='raise')
    px = pd.to_numeric(raw.iwv_close, errors='raise').to_numpy(float)
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise RuntimeError('IWV witness dates are unordered or duplicated')
    if not np.isfinite(px).all() or (px <= 0).any():
        raise RuntimeError('IWV witness has invalid closes')
    if dates.iloc[-1] != pd.Timestamp('2026-07-31') or dates.iloc[0] >= pd.Timestamp('2006-01-03'):
        raise RuntimeError('IWV witness coverage changed')
    p = pd.Series(px, index=pd.DatetimeIndex(dates))
    ret = p.pct_change(fill_method=None)
    rv20 = ret.rolling(20).std(ddof=1) * np.sqrt(252.)
    rv40 = ret.rolling(40).std(ddof=1) * np.sqrt(252.)
    return pd.DataFrame({
        'comparison_r20': p.pct_change(20, fill_method=None),
        'comparison_r40': p.pct_change(40, fill_method=None),
        'comparison_dd': p / p.cummax() - 1.,
        'comparison_rv20': rv20,
        'comparison_volratio': rv20 / rv40,
    })


def install(text: str, market_proxy: str, params: dict) -> str:
    if market_proxy not in ('SPY', 'IWV') or params not in PARAMETERS.values():
        raise RuntimeError('unregistered index-comparison cell')
    text = _BASE_INSTALL(text, 'spy_vol', params)
    if market_proxy == 'IWV':
        addition = """    from backtester.research_champion_index_comparison_v2 import load_iwv_features as _load_iwv_features
    _index_obs=_load_iwv_features(Path(os.environ['MARKET_RISK_IWV_CSV']))
    spy=spy.join(_index_obs,how='left')
    _required=(spy.index>=pd.Timestamp('2006-01-03')) & (spy.index<=END)
    if spy.loc[_required,list(_index_obs.columns)].isna().any().any():
        raise RuntimeError('IWV observation missing for a replay session')
"""
        text = legacy._once(text, '    cash=_CANONICAL.cash_factors()\n', addition + '    cash=_CANONICAL.cash_factors()\n', 'IWV observation join')
        values = ','.join(f"float(spy.loc[date,{c!r}])" for c in INDEX_COLUMNS)
    else:
        values = 'spy20,spy40,spydd,rv20,volratio'
    old = '            a_d,a_reason=ca.step(native_target,effective_native,dd,spy20,spy40,spydd,rv20,volratio,vix,vixchg5,vixz,vixpct,r20)'
    new = f'            market20,market40,marketdd,marketvol,marketratio={values}\n' + '            a_d,a_reason=ca.step(native_target,effective_native,dd,market20,market40,marketdd,marketvol,marketratio,vix,vixchg5,vixz,vixpct,r20)'
    text = legacy._once(text, old, new, 'Candidate A index-only call')
    old = "'native_close_target':native_target,"
    new = f"'market_observation_proxy':{market_proxy!r},'market_r20':market20,'market_r40':market40,'market_dd':marketdd,'market_rv20':marketvol,'market_vol_ratio':marketratio," + old
    text = legacy._once(text, old, new, 'index observation telemetry')
    compile(text, '<index-comparison-v2>', 'exec')
    return text


def validate_frozen_path(daily: pd.DataFrame, baseline: pd.DataFrame) -> dict:
    if daily.date.tolist() != baseline.date.tolist() or len(daily) != 5032:
        raise RuntimeError('replay session alignment changed')
    if daily.date.iloc[0] != '2006-07-31' or daily.date.iloc[-1] != '2026-07-31':
        raise RuntimeError('replay window changed')
    exact = ['research_ranking_sha256', 'research_selected_positions_sha256',
             'research_selected_positions', 'research_eligible_universe', 'research_ranking_count',
             'native_close_target', 'effective_native', 'fast_signal', 'slow_signal']
    for col in exact:
        if not daily[col].equals(baseline[col]):
            raise RuntimeError(f'frozen path changed: {col}')
    gaps = {}
    for col in ['research_wealth_core_equity', 'research_wealth_core_open_equity', 'spy_nav', 'spy_r20', 'B_nav', 'B_allocation']:
        x = daily[col].to_numpy(float); y = baseline[col].to_numpy(float)
        if not np.allclose(x, y, rtol=1e-12, atol=1e-12, equal_nan=True):
            raise RuntimeError(f'frozen economics changed: {col}')
        gaps[col] = float(np.nanmax(np.abs(x-y)))
    for left, right in [('research_nav', 'A_nav'), ('research_allocation', 'A_allocation')]:
        if not np.array_equal(daily[left].to_numpy(float), daily[right].to_numpy(float)):
            raise RuntimeError('Candidate A promotion parity failed')
    allocation = daily.research_allocation.to_numpy(float)
    if not np.isfinite(allocation).all() or (allocation < 0).any() or (allocation > 1).any():
        raise RuntimeError('invalid allocation')
    native = daily.effective_native.to_numpy(float)
    if (allocation > native + 1e-12).any():
        raise RuntimeError('Candidate A exceeded Native Sentinel ceiling')
    return {'status': 'PASS', 'sessions': len(daily), 'exact_columns': exact, 'maximum_absolute_gaps': gaps}


def seal(output: Path) -> None:
    # Logs are live while this function executes; immutable evidence is sealed here.
    files = sorted(p for p in output.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt' and p.suffix != '.log')
    (output/'SHA256SUMS.txt').write_text(''.join(f'{sha256(p)}  {p.relative_to(output)}\n' for p in files))


def finalize(output: Path, market_proxy: str, parameter_set: str, baseline: Path, iwv: Path) -> None:
    daily = pd.read_csv(output/'daily.csv.gz')
    audit = validate_frozen_path(daily, pd.read_csv(baseline))
    params = PARAMETERS[parameter_set]
    manifest = {
        'status': STATUS, 'methodology_version': 'OBSERVATION_ONLY_V2_INDEX_COMPARISON',
        'market_proxy': market_proxy, 'parameter_set': parameter_set, 'parameters': params,
        'source_sha': os.environ.get('GITHUB_SHA'), 'workflow_run_id': os.environ.get('GITHUB_RUN_ID'),
        'runtime_sha': closure.RUNTIME_MAIN_SHA, 'baseline_daily_sha256': sha256(baseline),
        'iwv_witness_sha256': sha256(iwv), 'vix_witness_sha256': VIX_SHA,
        'frozen_path_validation': audit,
        'observation_scope': 'Candidate A volatility, rebound and cross-surface market inputs only',
        'native_sentinel_market_series': 'SPY', 'benchmark_series': 'SPY',
        'security_universe': 'frozen corrected broad common-stock universe',
        'iwv_data_status': 'retained vendor-adjusted historical ETF series; historical-vintage certification pending',
        'timing': 'current close observations; existing next-session raw-open execution',
        'selection': 'preselected SPY/IWV plateau centers; both indices run at both parameter sets',
    }
    (output/'index-comparison-v2-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    (output/'frozen-path-validation.json').write_text(json.dumps(audit, indent=2, sort_keys=True)+'\n')
    daily['market_observation_proxy'] = market_proxy
    daily['index_parameter_set'] = parameter_set
    daily.to_csv(output/'daily.csv.gz', index=False, compression={'method': 'gzip', 'mtime': 0})
    metrics = pd.read_csv(output/'metrics.csv')
    metrics['market_observation_proxy'] = market_proxy
    metrics['index_parameter_set'] = parameter_set
    metrics.to_csv(output/'metrics.csv', index=False)
    for name in ['summary.json', 'run-status.json', 'pit-closure-replay-identity.json', 'market-risk-controller-manifest.json', 'market-risk-controller-v2-manifest.json']:
        path = output/name
        doc = json.loads(path.read_text())
        doc.update(status=STATUS, certification_status='NOT_CERTIFIED', market_observation_proxy=market_proxy,
                   index_parameter_set=parameter_set, index_comparison=manifest)
        if name == 'market-risk-controller-v2-manifest.json':
            doc['preserved_state_machine'] = ['episode creation', 'persistence', '11% market rebound route', 'cross-surface recovery', 'latch/clear', '55% ceiling', 'next-open timing']
        path.write_text(json.dumps(doc, indent=2, sort_keys=True)+'\n')
    lines = [f'# {market_proxy} / {parameter_set}: exact 20-year V2 replay', '', STATUS, '',
             'Frozen corrected Wealth Core path, Native Sentinel and SPY benchmark validation: PASS.', '',
             '| Years | Series | CAGR | Max drawdown | Sharpe | Ending multiple |', '|---:|---|---:|---:|---:|---:|']
    for row in metrics.itertuples(index=False):
        lines.append(f'| {row.window_years} | {row.variant} | {row.cagr:.2%} | {row.max_drawdown:.2%} | {row.sharpe:.3f} | {row.ending_multiple:.3f}x |')
    lines += ['', 'IWV changes Candidate A market observations. Native Sentinel and the benchmark retain SPY.',
              'The 2006-07-31 to 2026-07-31 interval is research in-sample. Vendor historical-vintage and strategy-path PIT certification remain pending.']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    seal(output)
    print(json.dumps({'index_comparison': market_proxy, 'parameter_set': parameter_set, 'finalization': 'PASS', 'sessions': len(daily)}, sort_keys=True), flush=True)


def run(output: Path, market_proxy: str, parameter_set: str, baseline: Path, iwv: Path, vix: Path) -> int:
    authenticate(baseline, BASELINE_SHA); authenticate(iwv, IWV_SHA); authenticate(vix, VIX_SHA)
    if os.environ.get('PIT_OFFICIAL_BACKTEST', '0') not in ('', '0'):
        raise RuntimeError('index comparison is a research-only replay')
    params = PARAMETERS[parameter_set]
    original = v2.install
    saved_env = os.environ.get('MARKET_RISK_IWV_CSV')
    os.environ['MARKET_RISK_IWV_CSV'] = str(iwv.resolve())
    def assembly(text, family, parameters):
        if family != 'spy_vol' or parameters != params:
            raise RuntimeError('V2 wrapper configuration changed')
        return install(text, market_proxy, params)
    v2.install = assembly
    try:
        rc = v2.run(output, 'spy_vol', params, vix)
    finally:
        v2.install = original
        if saved_env is None:
            os.environ.pop('MARKET_RISK_IWV_CSV', None)
        else:
            os.environ['MARKET_RISK_IWV_CSV'] = saved_env
    if rc:
        return rc
    finalize(output.resolve(), market_proxy, parameter_set, baseline, iwv)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--market-proxy', choices=['SPY', 'IWV'], required=True)
    ap.add_argument('--parameter-set', choices=sorted(PARAMETERS), required=True)
    ap.add_argument('--baseline-daily', type=Path, required=True)
    ap.add_argument('--iwv-csv', type=Path, required=True)
    ap.add_argument('--vix-csv', type=Path, required=True)
    a = ap.parse_args()
    return run(a.output, a.market_proxy, a.parameter_set, a.baseline_daily, a.iwv_csv, a.vix_csv)

if __name__ == '__main__':
    raise SystemExit(main())
