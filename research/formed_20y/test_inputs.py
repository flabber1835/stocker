from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from .inputs import TARGETS, verify_scope


def material(tmp_path):
    variant=dict(eligible_days={'CONTROL':['synthetic']*5284},consumed_sha256='a'*64)
    proof=dict(status='PASS_DIAGNOSTIC',incoming=[],source_admission_changed=False,
        source_status='FAIL',sessions=5410,variants={k:deepcopy(variant)
        for k in ('original','stated_ratio','perturbed_signal')})
    payloads={'current-code-reachability.json':proof}
    for kind in ('adv20','both'):
        payloads[f'reachability-refusal-{kind}.json']=dict(status='REFUSED',
            reason='TARGET_BECAME_ELIGIBLE',identities=list(TARGETS))
    def save():
        for name,value in payloads.items():
            (tmp_path/name).write_text(json.dumps(value))
        return dict(status='RESEARCH_ONLY',source_status='FAIL',
            evidence_files={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in payloads})
    return payloads,save


def test_normal_scoped_permission_keeps_failed_source_status(tmp_path):
    payloads,save=material(tmp_path)
    cert=save()
    verify_scope(tmp_path,cert)
    assert cert['source_status'] == 'FAIL'
    cert['source_status']='PASS'
    with pytest.raises(ValueError,match='source admission'):
        verify_scope(tmp_path,cert)


@pytest.mark.parametrize('fault',['incoming','reachable','no_control','different_output','missing_variant','mutation_survived'])
def test_rehashed_incomplete_scope_evidence_still_refuses(tmp_path,fault):
    payloads,save=material(tmp_path)
    proof=payloads['current-code-reachability.json']
    if fault == 'incoming': proof['incoming']=[{'delivered_security_id':next(iter(TARGETS))}]
    elif fault == 'reachable': proof['variants']['original']['eligible_days'][next(iter(TARGETS))]=['2005-07-29']
    elif fault == 'no_control': proof['variants']['original']['eligible_days']['CONTROL']=[]
    elif fault == 'different_output': proof['variants']['perturbed_signal']['consumed_sha256']='b'*64
    elif fault == 'missing_variant': del proof['variants']['stated_ratio']
    else: payloads['reachability-refusal-both.json']['status']='PASS'
    with pytest.raises(ValueError): verify_scope(tmp_path,save())


def test_changed_evidence_bytes_refuse_before_consumption(tmp_path):
    _,save=material(tmp_path)
    cert=save()
    with (tmp_path/'current-code-reachability.json').open('a') as f: f.write(' ')
    with pytest.raises(ValueError,match='bytes changed'): verify_scope(tmp_path,cert)
