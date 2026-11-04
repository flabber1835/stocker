"""Three exact existing initial prefixes grant reporting only; DATA/synthetic."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_partial as p
import system_campaign_financial_resume as m


def target(arm):return json.loads((p.HERE/m.PARTIALS).read_bytes())['arms'][arm]


@pytest.mark.parametrize('arm',['P05','P06','P11'])
def test_exact_own_existing_prefix_uses_its_real_zero_measurement_seed_only(arm):
    value=target(arm);before=deepcopy(value);seed=p.reporting_seed(value)
    assert value==before and p.digest(value)==p.INITIAL_PREFIX_TARGETS[arm]
    assert (value['measured_closes'],value['selected_session'])==(21,'2018-01-31')
    assert (seed['measured_closes'],seed['selected_session'])==(0,'2017-06-30')
    assert seed['base']==value['base'] and seed['selected_checkpoint'].startswith('lineage/original-checkpoints/')
    assert value['financial_authority'] is value['financial_predecessor_admitted'] is False
    assert arm not in p.ADMISSIONS
    with pytest.raises(ValueError,match='EXACT_ADMITTED_ARM'):p.root_spec(arm)


@pytest.mark.parametrize('change',['arm','checkpoint','cash','seed','counter','format','authority','marker','date'])
def test_arbitrary_or_modified_existing_initial_prefix_is_not_report_authority(change):
    value=deepcopy(target('P05'))
    if change=='arm':value['arm']='P06'
    elif change=='checkpoint':value['outer_sha256']='0'*64
    elif change=='cash':value['base']['capital']='50001'
    elif change=='seed':value['initial_monthly_seed']['selected_checkpoint']='diagnostic/checkpoint.json.gz'
    elif change=='counter':value['initial_monthly_seed']['measured_closes']=1
    elif change=='format':value['archive_format']=p.FRESH_FORMAT
    elif change=='authority':value['financial_authority']=True
    elif change=='marker':value['initial_prefix_reporting']=False
    else:value['selected_session']='2018-02-01'
    with pytest.raises(ValueError,match='EXACT_EXISTING_INITIAL_PREFIX_TARGET'):p.reporting_seed(value)


def without_guard(code):
    fn=next(n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='initial_prefix_seed')
    guard=next(n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and any(isinstance(a,ast.Constant) and a.value==code for a in n.value.args))
    fn.body.remove(guard);ns=dict(vars(p))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-initial-prefix-guard>','exec'),ns)
    return ns['initial_prefix_seed']


def test_exact_target_guard_removal_accepts_substituted_transport():
    value=deepcopy(target('P05'));value['receipt_name']='wrong-receipt.json'
    with pytest.raises(ValueError):p.initial_prefix_seed(value)
    assert without_guard('PARTIAL_EXACT_EXISTING_INITIAL_PREFIX_TARGET')(value)['measured_closes']==0


def test_zero_seed_guard_removal_accepts_a_nonzero_seed(monkeypatch):
    value=deepcopy(target('P05'));value['initial_monthly_seed']['measured_closes']=1
    monkeypatch.setattr(p,'INITIAL_PREFIX_TARGETS',dict(p.INITIAL_PREFIX_TARGETS,P05=p.digest(value)))
    with pytest.raises(ValueError,match='ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED'):p.initial_prefix_seed(value)
    assert without_guard('PARTIAL_ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED')(value)['measured_closes']==1


def test_initial_report_request_can_never_start_financial_workers(monkeypatch):
    monkeypatch.setattr(m,'SELECTED_ARMS',('P05','P06','P11'))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    value=m.expected_request()
    assert value['arms']==['P05','P06','P11'] and value['maximum_parallel_financial_workers']==0
    assert value['financial_resume_authorized'] is False and value['readonly_partial_review'] is True
    assert value['admitted_checkpoints']=={} and set(value['initial_reporting_origins'])=={'P05','P06','P11'}
    monkeypatch.setattr(m,'EXECUTION_MODE','OWN_ADMITTED_FINANCIAL_CONTINUATION')
    with pytest.raises(ValueError,match='EXACT_ADMITTED_ARM'):m.expected_request()


def test_initial_reporting_does_not_repin_original_fresh_p00_origin():
    assert p.FRESH_TARGET_SHA=='0aaa2967a245b4eefc9097fd84b6227a0f99717c65dc88b21b2736aeecdf2d1d'
    assert p.FRESH_REQUEST_SHA=='13d68690a7e940bc52d1060098a04d577932f292b30418a29cbfc2346f242b0d'
