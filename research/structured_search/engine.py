"""Fit inner models, freeze selection, then evaluate chronologically."""
import json
from pathlib import Path
import time

import numpy as np

from research.exposure_oracle import accounting as A, inputs, logic
from . import data as D, models, policies, protocol


def candidates_at(candidates, x, days, baseline, cutoff, progress=None):
    families = {f:[] for f in protocol.FAMILIES}
    paths, fitted = {}, {}
    for c in candidates:
        if c.family=='state': path = policies.state_path(x,baseline,c.params)
        elif c.family=='trend': path = policies.trend_path(x,baseline,c.params)
        elif c.family=='predictive':
            key = models.key(c.params)
            if key not in fitted:
                model = models.fit(x,days,c.params,cutoff)
                fitted[key] = dict(model=model,prediction=models.predict(model,x))
            path = policies.forecast_path(fitted[key]['prediction'],baseline,c.params)
        else: path = policies.combine(families,c.params)
        paths[c.id] = path
        families[c.family].append(path)
        if progress and len(paths)%48==0: progress(completed=len(paths),family=c.family)
    return paths,{key:v['model'] for key,v in fitted.items()}


def array_archive(path, ids, arrays):
    np.savez_compressed(path,ids=np.array(ids),actions=np.stack([arrays[k] for k in ids]).astype(np.int8))


def assert_frozen(path, expected):
    if inputs.sha(path.read_bytes())!=expected:
        raise ValueError('outer evaluation mutated frozen selection')


def run(snapshot: Path, output: Path, progress=None):
    snapshot,output = snapshot.resolve(),output.resolve()
    if snapshot==output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('output must be separate from retained history')
    output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    def status(label,**items):
        value = dict(status=label,elapsed_seconds=round(time.monotonic()-started,2),**items)
        inputs.write_json(output/'status.json',value)
        print(json.dumps(value),flush=True)
        if progress: progress(value)
    status('AUTHENTICATING')
    binding,rows = inputs.load(snapshot)
    root = Path(__file__).resolve().parents[2]
    sources = inputs.verify_accountant_sources(binding,root)
    for name in ('sentinel/core/kernel.py','sentinel/controller/champion.py',
                 'sentinel/controller/champion_frozen.py','sentinel/controller/owned_impairment.py'):
        sources[name] = inputs.sha((root/name).read_bytes())
        if sources[name]!=binding['production']['files'].get(name):
            raise ValueError('recorded source changed: '+name)
    days,initial,actual = A.tape(rows)
    logic.decisions(rows,verify_baseline=True)
    initial_index = int(D.action_indices([float(initial)])[0])
    actual_actions = D.action_indices([float(a) for a in actual])
    baseline = np.array([float(r['decision']['target_core_exposure']) for r in rows])
    if not np.array_equal(D.apply(baseline,days),actual_actions):
        raise ValueError('baseline next-open mismatch')
    x = D.features(rows)
    dates = [r['session'] for r in rows]
    folds = protocol.folds(dates)
    candidates = protocol.menu()
    by_id = {c.id:c for c in candidates}
    menu = dict(schema='sentinel-structured-search/1',seed=protocol.SEED,
        candidates=[c.model_dump() for c in candidates],folds=folds,features=list(D.FEATURES),
        actions=D.GRID.tolist(),cost=.001,bootstrap_resamples=500,bootstrap_block=20,
        source_manifest=json.loads((snapshot/'manifest.json').read_text()),source_hashes=sources,
        harness={str(p.relative_to(root)):inputs.sha(p.read_bytes()) for p in
                 [*Path(__file__).parent.glob('*.py'),root/'docs/sentinel-structured-search.md']},
        caveat='Previously inspected history. Chronological model holdouts, not untouched research holdouts.')
    inputs.write_json(output/'protocol.json',menu)
    protocol_hash = inputs.sha((output/'protocol.json').read_bytes())
    status('PROTOCOL_FROZEN',sha256=protocol_hash,candidates=len(candidates))
    matrix = D.matrices(days)
    selector_names = ['selected',*protocol.FAMILIES]
    stitched = {name:actual_actions.copy() for name in selector_names}
    all_actions = {c.id:actual_actions.copy() for c in candidates}
    selections = []
    for fold in folds:
        fid = fold['id']; left,right = fold['left'],fold['right']
        status('INNER_FIT',fold=fid)
        inner,inner_models = candidates_at(candidates,x[:left+1],days[:left],baseline[:left+1],
            fold['fit_end'],lambda **v:status('INNER_CANDIDATES',fold=fid,**v))
        inner_actions = {k:D.apply(v,days[:left]) for k,v in inner.items()}
        inner_rows = []
        a,b = fold['val_left'],fold['val_right']
        # Same known opening account for every validation candidate. Intended state
        # is primed from available past observations, independently of that account.
        old = int(actual_actions[a-1])
        base_metrics = D.metrics(D.returns(matrix[a:b],actual_actions[a:b],old),
            dates[a:b+1],actual_actions[a:b],old)
        base_record = dict(id='baseline',family='baseline',metrics=base_metrics)
        for c in candidates:
            actions = inner_actions[c.id][a:b]
            m = D.metrics(D.returns(matrix[a:b],actions,old),dates[a:b+1],actions,old)
            inner_rows.append(dict(id=c.id,family=c.family,metrics=m))
        selection = dict(fold=fold,baseline=base_record,records=inner_rows,
            choices={name:protocol.choose(inner_rows,base_record,None if name=='selected' else name)
                     for name in selector_names},protocol_sha256=protocol_hash)
        inputs.write_json(output/f'{fid}-inner-models.json',inner_models)
        array_archive(output/f'{fid}-inner-actions.npz',list(inner_actions),inner_actions)
        selection_path = output/f'{fid}-selection.json'
        inputs.write_json(selection_path,selection)
        frozen_hash = inputs.sha(selection_path.read_bytes())
        status('SELECTION_FROZEN',fold=fid,sha256=frozen_hash,
               choices={n:r['id'] for n,r in selection['choices'].items()})
        del inner,inner_models,inner_actions
        outer,outer_models = candidates_at(candidates,x[:right+1],days[:right],baseline[:right+1],left,
            lambda **v:status('OUTER_REFIT',fold=fid,**v))
        inputs.write_json(output/f'{fid}-outer-models.json',outer_models)
        outer_applied = {k:D.apply(v,days[:right]) for k,v in outer.items()}
        for c in candidates: all_actions[c.id][left:right] = outer_applied[c.id][left:right]
        for name,choice in selection['choices'].items():
            path = actual_actions if choice['id']=='baseline' else outer_applied[choice['id']]
            stitched[name][left:right] = path[left:right]
        assert_frozen(selection_path,frozen_hash)
        selection['sha256'] = frozen_hash
        selection['outer_metrics'] = {name:D.window(matrix,p,initial_index,dates,left,right)
                                      for name,p in {**stitched,'baseline':actual_actions}.items()}
        selections.append(selection)
        status('OUTER_BLOCK_COMPLETE',fold=fid,metrics=selection['outer_metrics'])
        del outer,outer_models,outer_applied
    start = folds[0]['left']
    controls = {'baseline':actual_actions.copy(),'always_core':actual_actions.copy(),
                'simple_trend':actual_actions.copy()}
    controls['always_core'][start:] = 2
    simple = D.apply(policies.trend_path(x,baseline,policies.SIMPLE_TREND),days)
    controls['simple_trend'][start:] = simple[start:]
    paths = {**controls,**stitched}
    array_archive(output/'outer-candidates.npz',list(all_actions),all_actions)
    array_archive(output/'outer-selectors.npz',list(paths),paths)
    inputs.write_json(output/'selections.json',selections)
    metrics = {name:D.window(matrix,p,initial_index,dates,start,len(days)) for name,p in paths.items()}
    spy_log = np.diff(np.log(np.array([float(r['spy']['nav']) for r in rows])))
    metrics['spy'] = D.metrics(spy_log[start:],dates[start:])
    inputs.write_json(output/'summary.json',dict(schema='sentinel-structured-search-results/1',
        source_start=dates[0],source_end=dates[-1],baseline=dates[start],first_return=dates[start+1],
        returns=len(days)-start,candidates=len(candidates),inner_trials=len(candidates)*len(folds),
        protocol_sha256=protocol_hash,metrics=metrics,
        selection_hashes={s['fold']['id']:s['sha256'] for s in selections},
        caveat=menu['caveat']))
    status('SEARCH_COMPLETE',metrics=metrics)
    return rows,days,initial_index,all_actions,paths,selections
