"""Independent raw-ledger accounting and frozen-selection/model-boundary audit."""
from decimal import Decimal
from datetime import date
import json
from pathlib import Path

import numpy as np

from research.exposure_oracle import inputs
from research.exposure_oracle.target_audit import factor, metrics as decimal_metrics
from . import data, protocol


def archive(path):
    with np.load(path,allow_pickle=False) as z:
        return dict(zip(z['ids'].tolist(),z['actions'].copy()))


def raw_logs(rows, actions, old):
    """Rebuild from raw opening/closing ledgers, not transition matrices."""
    levels = np.array([0.,.55,1.])
    new = levels[actions]; previous = np.r_[levels[old],new[:-1]]
    co,cc,cp,bo,bc,bp = [],[],[],[],[],[]
    for p,r in zip(rows,rows[1:]):
        e = r['economics']
        co.append(float(e['parent_core_open_equity']))
        cc.append(float(e['parent_core_close_equity']))
        cp.append(float(p['economics']['parent_core_close_equity']))
        bo.append(float(e['bil_open_adjusted']))
        bc.append(float(e['bil_close_adjusted']))
        bp.append(float(e['bil_previous_close_adjusted_current_publication']))
    co,cc,cp,bo,bc,bp = map(np.array,(co,cc,cp,bo,bc,bp))
    full = new*cc/cp+(1-new)*bc/bp
    changed = (previous*co/cp+(1-previous)*bo/bp)*(new*cc/co+(1-new)*bc/bo)
    net = np.where(new==previous,full,changed)*(1-.001*np.abs(new-previous))
    for i,r in enumerate(rows[1:]):
        if r['economics']['initial_deployment']:
            if new[i]!=float(r['economics']['held_allocation']): raise ValueError('funding action changed')
            net[i]=float(r['economics']['net_factor'])
    if not np.isfinite(net).all() or (net<=0).any(): raise ValueError('invalid independent ledger')
    return np.log(net)


def raw_metrics(rows, actions, old):
    logs = raw_logs(rows,actions,old)
    nav = np.r_[1.,np.exp(np.cumsum(logs))]
    elapsed = (date.fromisoformat(rows[-1]['session'])-date.fromisoformat(rows[0]['session'])).days
    level = np.array([0.,.55,1.]); delta = level[actions]-level[np.r_[old,actions[:-1]]]
    return dict(cagr=float(nav[-1]**(365.2425/elapsed)-1),multiple=float(nav[-1]),
        maxdd=float(np.max(1-nav/np.maximum.accumulate(nav))),turnover=float(abs(delta).sum()),
        switches=int(np.count_nonzero(delta)),mean_exposure=float(level[actions].mean()))


def assert_metrics(saved, expected):
    for k in expected:
        if k not in saved or not np.isclose(float(saved[k]),expected[k],rtol=1e-10,atol=1e-10):
            raise ValueError('independent metrics mismatch: '+k)


def check_model(model,x,cutoff):
    h = model['horizon']; indices = np.arange(data.WARMUP,cutoff-h+1)
    if (model['cutoff']!=cutoff or model['last_outcome']!=cutoff
            or model['last_example']!=cutoff-h or model['examples']!=len(indices)):
        raise ValueError('model training boundary changed')
    values = x[indices][:,model['columns']]
    mean,std = values.mean(axis=0),values.std(axis=0)
    std[std<1e-10]=1.
    if not np.allclose(mean,model['xmean'],rtol=1e-12,atol=1e-12):
        raise ValueError('model scaler includes wrong training observations')
    if not np.allclose(std,model['xscale'],rtol=1e-12,atol=1e-12):
        raise ValueError('model scale differs from training observations')


def run(snapshot: Path, output: Path):
    _,rows = inputs.load(snapshot)
    config = json.loads((output/'protocol.json').read_text())
    summary = json.loads((output/'summary.json').read_text())
    source = Path(__file__).resolve().parents[2]
    for name,sha in config['harness'].items():
        if inputs.sha((source/name).read_bytes())!=sha:
            raise ValueError('research source changed after protocol freeze: '+name)
    if inputs.sha((output/'protocol.json').read_bytes())!=summary['protocol_sha256']:
        raise ValueError('protocol hash changed')
    if config['candidates']!=[c.model_dump() for c in protocol.menu()]:
        raise ValueError('candidate menu changed')
    x = data.features(rows)
    baseline = np.searchsorted([0.,.55,1.],[float(r['economics']['held_allocation']) for r in rows[1:]])
    start = config['folds'][0]['left']; dates = [r['session'] for r in rows]
    selections = json.loads((output/'selections.json').read_text())
    all_actions = archive(output/'outer-candidates.npz')
    selectors = archive(output/'outer-selectors.npz')
    training_count = model_count = 0
    for fold,selection in zip(config['folds'],selections):
        fid=fold['id']; a,b = fold['val_left'],fold['val_right']
        frozen = json.loads((output/f'{fid}-selection.json').read_text())
        if inputs.sha((output/f'{fid}-selection.json').read_bytes())!=summary['selection_hashes'][fid]:
            raise ValueError('frozen selection changed')
        if frozen['choices']!=selection['choices']: raise ValueError('stitched selection differs')
        inner = archive(output/f'{fid}-inner-actions.npz')
        for record in frozen['records']:
            assert_metrics(record['metrics'],raw_metrics(rows[a:b+1],inner[record['id']][a:b],int(baseline[a-1])))
            training_count += 1
        assert_metrics(frozen['baseline']['metrics'],raw_metrics(rows[a:b+1],baseline[a:b],int(baseline[a-1])))
        for name,chosen in frozen['choices'].items():
            allowed=[frozen['baseline'],*(r for r in frozen['records'] if
                (name=='selected' or r['family']==name) and
                r['metrics']['maxdd']<=frozen['baseline']['metrics']['maxdd']+1e-10)]
            expected=min(allowed,key=lambda r:(-r['metrics']['cagr'],r['metrics']['turnover'],r['metrics']['switches'],r['id']))
            if chosen!=expected: raise ValueError('selection violated drawdown/ranking rule')
            path=baseline if chosen['id']=='baseline' else all_actions[chosen['id']]
            left,right=fold['left'],fold['right']
            if not np.array_equal(selectors[name][left:right],path[left:right]):
                raise ValueError('stitched policy differs from frozen winner')
        for suffix,cutoff in (('inner',fold['fit_end']),('outer',fold['left'])):
            fitted=json.loads((output/f'{fid}-{suffix}-models.json').read_text())
            for model in fitted.values():
                check_model(model,x,cutoff); model_count+=1
    # Independent reconstruction of every outer trial, not merely the winner.
    from . import data as fast
    from research.exposure_oracle.accounting import tape
    days,initial,_ = tape(rows,canonical=False)
    mat = fast.matrices(days)
    ledger_rows=0
    for actions in [*all_actions.values(),*selectors.values()]:
        independent=raw_logs(rows[start:],actions[start:],int(actions[start-1]))
        expected=fast.returns(mat[start:],actions[start:],int(actions[start-1]))
        if not np.allclose(independent,expected,rtol=1e-10,atol=1e-12):
            raise ValueError('independent outer daily ledger mismatch')
        ledger_rows+=len(independent)
    public=json.loads((output/'paths.json').read_text())
    navs={}; decimal_rows=0
    for name,actions in selectors.items():
        nav=[Decimal(1)]; old=Decimal(str([0.,.55,1.][actions[start-1]]))
        for i in range(start,len(rows)-1):
            new=Decimal(str([0.,.55,1.][actions[i]]))
            nav.append(nav[-1]*factor(rows[i],rows[i+1],old,new)); old=new
        if any(abs(v-Decimal(saved))>Decimal('1e-20') for v,saved in zip(nav,public[name]['nav'])):
            raise ValueError('independent Decimal daily NAV mismatch')
        assert_metrics(summary['metrics'][name],raw_metrics(rows[start:],actions[start:],int(actions[start-1])))
        navs[name]=nav; decimal_rows+=len(nav)-1
    navs['spy']=[Decimal(r['spy']['nav'])/Decimal(rows[start]['spy']['nav']) for r in rows[start:]]
    monthly=json.loads((output/'monthly.json').read_text()); count=0
    for month in monthly:
        end=dates.index(month['session'])-start
        for name,nav in navs.items():
            measured=decimal_metrics(nav[:end+1],dates[start:start+end+1])
            assert_metrics(month['series'][name],measured); count+=1
    audit=dict(status='PASS',training_candidates=training_count,models_with_verified_training_boundary=model_count,
        independent_outer_daily_returns=ledger_rows,independent_decimal_daily_returns=decimal_rows,
        monthly_series=count,source_and_protocol_hashes='PASS',frozen_selection_and_stitching='PASS',
        caveat='Economic ledger is independently reconstructed; policy/model algorithms also have targeted falsifiers.')
    inputs.write_json(output/'audit.json',audit)
    return audit
