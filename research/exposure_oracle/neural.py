"""Train and evaluate a causal neural imitator of the three-state oracle."""
import argparse
from decimal import Decimal as D
from importlib.metadata import version
import json
from pathlib import Path
import time

import numpy as np

from . import accounting as A, analysis, inputs, neural_data as data, neural_model as model

DEPENDENCIES = {'scikit-learn':'1.7.2','scipy':'1.16.3','joblib':'1.5.2','threadpoolctl':'3.6.0','numpy':'2.4.6'}


def environment() -> dict:
    actual = {name:version(name) for name in DEPENDENCIES}
    if actual != DEPENDENCIES:
        raise ValueError('use the pinned neural research environment')
    return actual


def authenticate_oracle(snapshot: Path, oracle: Path, binding: dict) -> tuple[dict,dict]:
    summary = json.loads((oracle/'summary.json').read_text())
    paths = json.loads((oracle/'paths.json').read_text())
    pointer = json.loads((snapshot/'latest-checkpoint.json').read_text())
    if (summary['schema'] != 'fractional-exposure-oracle/1' or
            summary['source_binding'] != inputs.digest(binding) or summary['checkpoint'] != pointer or
            summary['actions'] != [str(a) for a in data.ACTIONS]):
        raise ValueError('teacher artifact does not match authenticated snapshot/action set')
    for name in ('accounting.py','search.py','inputs.py'):
        if inputs.sha((Path(__file__).parent/name).read_bytes()) != summary['harness'][name]:
            raise ValueError('teacher source changed: '+name)
    return summary,paths


def export(path: Path, fitted: model.FrozenModel, checks: np.ndarray) -> tuple[model.FrozenModel,str]:
    inputs.write_json(path,fitted.model_dump())
    restored = model.FrozenModel.model_validate_json(path.read_text())
    if not np.array_equal(fitted.probabilities(checks),restored.probabilities(checks)):
        raise ValueError('model serialization changed inference')
    return restored,inputs.sha(path.read_bytes())


def score_paths(rows: list[dict], ideal: dict, predictions: np.ndarray, majority: int) -> dict:
    left,right = ideal['left'],ideal['right']
    selected = rows[left:right+1]
    days,initial,actual = A.tape(selected,canonical=False)
    if len(predictions) != len(days) or not np.isin(predictions,[0,1,2]).all():
        raise ValueError('one three-action prediction per following-open session required')
    exposures = dict(neural=[data.ACTIONS[int(i)] for i in predictions],sentinel=actual,
        core=[D(1)]*len(days),bil=[D(0)]*len(days),majority=[data.ACTIONS[majority]]*len(days))
    paths = {name:A.replay(days,initial,values,selected[0]['session']) for name,values in exposures.items()}
    paths['oracle'] = ideal['path']
    values = [D(r['spy']['nav'])/D(selected[0]['spy']['nav']) for r in selected]
    paths['spy'] = dict(**A.performance(values,[r['session'] for r in selected]),nav=[str(v) for v in values])
    return paths


def run(snapshot: Path, oracle: Path, output: Path, settings: model.Settings) -> dict:
    for source in (snapshot,oracle):
        if (output.resolve() == source.resolve() or output.resolve() in source.resolve().parents
                or source.resolve() in output.resolve().parents):
            raise ValueError('neural output must be separate from its immutable inputs')
    output.mkdir(parents=True,exist_ok=False)
    started = time.monotonic()
    def status(name, **details):
        record = dict(status=name,elapsed_seconds=round(time.monotonic()-started,2),**details)
        inputs.write_json(output/'status.json',record)
        print(json.dumps(record),flush=True)

    status('AUTHENTICATING')
    dependencies = environment()
    binding,rows = inputs.load(snapshot)
    original_summary,original_paths = authenticate_oracle(snapshot,oracle,binding)
    root = Path(__file__).resolve().parents[2]
    sources = inputs.verify_accountant_sources(binding,root)
    for name in ('sentinel/controller/champion.py','sentinel/controller/champion_frozen.py',
                 'sentinel/controller/owned_impairment.py','sentinel/core/kernel.py'):
        sources[name] = inputs.sha((root/name).read_bytes())
        if sources[name] != binding['production']['files'].get(name):
            raise ValueError('recorded feature/controller source changed: '+name)
    A.tape(rows)  # Check every ordinary transition against the canonical accountant.
    scopes = data.partitions(rows,settings.train_end,settings.validation_end)
    features = data.feature_matrix(rows)
    status('BUILDING_BOUNDED_TRAINING_LABELS',features=len(data.FEATURES))
    teachers = {name:data.teacher(rows,*scopes[name]) for name in ('train','validation')}
    samples = {name:data.supervised(rows,features,t) for name,t in teachers.items()}
    train_indices,x_train,y_train = samples['train']
    validation_indices,x_validation,y_validation = samples['validation']
    if rows[train_indices[-1]+1]['session'] > settings.train_end or rows[validation_indices[0]+1]['session'] <= settings.train_end:
        raise ValueError('training outcomes overlap validation')
    metadata = dict(role='TEMPORAL_EVALUATION',source_binding=inputs.digest(binding),
        trained_through=settings.train_end,selected_through=settings.validation_end,
        first_feature_session=rows[int(train_indices[0])]['session'],settings=settings.model_dump())
    status('TRAINING',training_samples=len(y_train),validation_samples=len(y_validation),
           training_classes=data.counts(y_train),validation_classes=data.counts(y_validation))
    fitted,history = model.select(x_train,y_train,x_validation,y_validation,data.FEATURES,settings,metadata)
    fitted,evaluation_sha = export(output/'evaluation-model.json',fitted,x_validation)
    inputs.write_json(output/'training-history.json',history)
    left,right = scopes['test']
    test_indices = np.arange(left,right)
    probabilities = fitted.probabilities(features[test_indices])
    predictions = probabilities.argmax(axis=1)
    prediction_rows = [dict(decision_session=rows[int(i)]['session'],return_session=rows[int(i)+1]['session'],
        probabilities=p.tolist(),target=str(data.ACTIONS[int(label)]))
        for i,p,label in zip(test_indices,probabilities,predictions)]
    inputs.write_json(output/'test-predictions.json',prediction_rows)
    prediction_sha = inputs.sha((output/'test-predictions.json').read_bytes())
    status('FROZEN_BEFORE_TEST_LABELS',selected_epoch=fitted.metadata['selected_epoch'],
           model_sha256=evaluation_sha,prediction_sha256=prediction_sha)

    teachers['test'] = data.teacher(rows,left,right)
    samples['test'] = data.supervised(rows,features,teachers['test'])
    indices,x_test,y_test = samples['test']
    if not np.array_equal(indices,test_indices):
        raise ValueError('held-out feature/next-open label alignment changed')
    classification = {name:model.classification(y,fitted.probabilities(x)) for name,(_,x,y) in samples.items()}
    majority = int(np.bincount(y_train,minlength=3).argmax())
    paths = score_paths(rows,teachers['test'],predictions,majority)
    actual_labels = np.array([data.ACTIONS.index(D(str(a))) for a in paths['sentinel']['exposure']])
    classification['test']['training_majority_accuracy'] = float(np.mean(y_test == majority))
    classification['test']['sentinel_accuracy'] = float(np.mean(y_test == actual_labels))
    status('TEST_SCORED',accuracy=classification['test']['accuracy'],
           neural=analysis.compact(paths['neural']),sentinel=analysis.compact(paths['sentinel']))

    status('VERIFYING_ORIGINAL_IDEAL_AND_REFITTING')
    full_teacher = data.teacher(rows,0,len(rows)-1)
    if (full_teacher['path']['exposure'] != original_paths['oracle']['exposure'] or
            abs(full_teacher['cap']-original_summary['actual_drawdown_cap']) > 1e-12):
        raise ValueError('recomputed full-period ideal differs from earlier selected teacher')
    full_indices,x_full,y_full = data.supervised(rows,features,full_teacher)
    refit_metadata = dict(role='ALL_HISTORY_REFIT',source_binding=inputs.digest(binding),
        trained_through=rows[-1]['session'],selected_through=settings.validation_end,
        settings=settings.model_dump(),evaluation_model_sha256=evaluation_sha,
        first_feature_session=rows[int(full_indices[0])]['session'])
    forward = model.refit(x_full,y_full,data.FEATURES,settings,fitted.metadata['selected_epoch'],refit_metadata)
    forward,refit_sha = export(output/'all-history-model.json',forward,x_full)
    if (inputs.sha((output/'evaluation-model.json').read_bytes()) != evaluation_sha or
            inputs.sha((output/'test-predictions.json').read_bytes()) != prediction_sha):
        raise ValueError('refit changed frozen evaluation evidence')
    phases = {name:dict(baseline=t['start'],last_outcome=t['end'],
        first_decision=rows[int(samples[name][0][0])]['session'],
        first_outcome=rows[int(samples[name][0][0])+1]['session'],samples=len(samples[name][2]),
        teacher_classes=data.counts(samples[name][2]),teacher_cap=t['cap'],teacher=analysis.compact(t['path']))
        for name,t in teachers.items()}
    summary = dict(schema='sentinel-neural-experiment/1',status='RESEARCH_ONLY_MODEL_HOLDOUT',
        source_binding=inputs.digest(binding),source_checkpoint=json.loads((snapshot/'latest-checkpoint.json').read_text()),
        original_teacher_files={name:inputs.sha((oracle/name).read_bytes()) for name in ('summary.json','paths.json')},
        source_hashes=sources,dependencies=dependencies,settings=settings.model_dump(),features=list(data.FEATURES),
        architecture=dict(hidden=[16,8],activation='tanh',outputs=[0,.55,1],
            parameters=sum(np.asarray(w).size for w in fitted.weights)+sum(len(b) for b in fitted.biases)),
        selected_epoch=fitted.metadata['selected_epoch'],epochs_run=len(history),partitions=phases,
        classification=classification,test_metrics={name:analysis.compact(p) for name,p in paths.items()},
        test_start=rows[left]['session'],test_end=rows[right]['session'],
        evaluation_model_sha256=evaluation_sha,test_predictions_sha256=prediction_sha,
        all_history_model_sha256=refit_sha,all_history_training_classes=data.counts(y_full),
        all_history_in_sample_classification=model.classification(y_full,forward.probabilities(x_full)),
        training_majority_action=str(data.ACTIONS[majority]),
        validation=dict(canonical_accounting='PASS',original_ideal_reproduced='PASS',model_roundtrip='PASS',
            predictions_frozen_before_test_labels='PASS',evaluation_unchanged_after_refit='PASS'),
        harness={p.name:inputs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')},
        limitations=['Previously inspected historical sample; not an untouched research holdout.',
            'Fixed Core path and scalar costs; not an Alpaca execution replay.',
            'No guaranteed future predictability; model is not installed in production.'])
    inputs.write_json(output/'summary.json',summary)
    inputs.write_json(output/'test-paths.json',paths)
    inputs.write_json(output/'teacher-labels.json',
        {name:{k:v for k,v in t.items() if k != 'path'} for name,t in {**teachers,'full_refit':full_teacher}.items()})
    selected = rows[left:right+1]
    months = analysis.monthly(selected,paths)
    inputs.write_json(output/'monthly.json',months)
    from .neural_report import write_report
    write_report(output,summary,selected,paths,months,history)
    status('COMPLETE',test=summary['test_metrics'],classification=classification['test'])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--oracle',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.snapshot,args.oracle,args.output,model.Settings())
