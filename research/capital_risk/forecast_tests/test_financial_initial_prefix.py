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


def initial_entry(arm):
    bundle=json.loads((p.HERE/p.ROOTS).read_bytes())
    return next(e for e in [*bundle['arms'].values(),*bundle['historical_roots'].values()]
        if e['transport']['arm']==arm and p.digest(e['transport'])==p.INITIAL_PREFIX_TARGETS[arm])


def target(arm):return deepcopy(initial_entry(arm)['transport'])


@pytest.mark.parametrize('arm',['P05','P06','P11'])
def test_exact_own_existing_prefix_uses_its_real_zero_measurement_seed_only(arm):
    value=target(arm);before=deepcopy(value);seed=p.reporting_seed(value)
    assert value==before and p.digest(value)==p.INITIAL_PREFIX_TARGETS[arm]
    assert (value['measured_closes'],value['selected_session'])==(21,'2018-01-31')
    assert (seed['measured_closes'],seed['selected_session'])==(0,'2017-06-30')
    assert seed['base']==value['base'] and seed['selected_checkpoint'].startswith('lineage/original-checkpoints/')
    assert value['financial_authority'] is value['financial_predecessor_admitted'] is False
    root=p.authorized_spec(initial_entry(arm),arm)
    assert root['outer_sha256']==value['outer_sha256'] and root['measured_closes']==21
    assert root['root_admission']['financial_continuation_authorized'] is True
    assert root['root_admission']['performance_scoring_authorized'] is False
    assert root['root_admission']['independent_accounting_snapshots']==294


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


def test_new_reporting_uses_current_admitted_seed_without_financial_workers(monkeypatch):
    original=p.root_spec
    monkeypatch.setattr(m,'root_spec',lambda arm:original(arm,initial_entry(arm)['admission_sha256']) if arm=='P03' else original(arm))
    monkeypatch.setattr(m,'SELECTED_ARMS',('P03',))
    monkeypatch.setattr(m,'EXECUTION_MODE','READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION')
    value=m.expected_request()
    assert value['arms']==['P03'] and value['maximum_parallel_financial_workers']==0
    assert value['financial_resume_authorized'] is False and value['readonly_partial_review'] is True
    assert set(value['admitted_checkpoints'])=={'P03'} and value['initial_reporting_origins']=={}
    monkeypatch.setattr(m,'SELECTED_ARMS',('P06',))
    with pytest.raises(ValueError,match='ONLY_NEW_SUFFIX_FROM_CURRENT_ADMITTED_REPORTING_SEED'):m.expected_request()


@pytest.mark.parametrize('arm,days',[('P05',211),('P06',291),('P11',169)])
def test_first_admitted_suffix_preserves_initial_seed_as_exact_history(arm,days):
    old=initial_entry(arm)
    bundle=json.loads((p.HERE/p.ROOTS).read_bytes())
    entry=next(e for e in [*bundle['arms'].values(),*bundle['historical_roots'].values()]
        if e['transport']['arm']==arm and e['admission']['completed']==days)
    current=p.root_spec(arm,entry['admission_sha256'])
    assert current['measured_closes']==days
    assert current['root_admission']['parent_root_admission_sha256']==old['admission_sha256']
    assert p.root_spec(arm,old['admission_sha256'])['measured_closes']==21
    assert current['root_admission']['performance_scoring_authorized'] is False


def test_p04_complete_target_is_explicit_readonly_evidence_from_own1970_seed():
    value=json.loads((p.HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P04']
    assert p.full_target(value) is True
    assert value['readonly_full_financial_target'] is True
    assert (value['measured_closes'],value['selected_session'])==(2156,'2026-07-31')
    assert p.reporting_seed(value)['measured_closes']==1970


def test_exact_p03_saved82_prefix_reports_only_from_its_own_zero_seed():
    value=target('P03')
    seed=p.reporting_seed(value)
    assert (value['measured_closes'],value['selected_session'])==(82,'2018-04-30')
    assert p.digest(value)==p.INITIAL_PREFIX_TARGETS['P03']
    assert (seed['measured_closes'],seed['selected_session'])==(0,'2017-06-30')
    assert seed['outer_sha256']=='fa1f7daca5e345490b4938fd786995755701664bdc265876d6d3545ce6fca6e0'
    assert seed['base']==value['base'] and seed['journals']['daily']['bytes']==seed['journals']['monthly']['bytes']==0
    spec=p.root_spec('P03',initial_entry('P03')['admission_sha256'])
    assert spec['outer_sha256']==value['outer_sha256'] and spec['measured_closes']==82
    assert spec['root_admission']['independent_accounting_snapshots']==416
    assert spec['root_admission']['new_monthly_reports']==4
    assert spec['root_admission']['performance_scoring_authorized'] is False


def test_p03_axis_guard_removal_admits_the_other_arms_counter(monkeypatch):
    value=target('P03')
    value['measured_closes']=21;value['selected_session']='2018-01-31'
    monkeypatch.setattr(p,'INITIAL_PREFIX_TARGETS',dict(p.INITIAL_PREFIX_TARGETS,P03=p.digest(value)))
    with pytest.raises(ValueError,match='ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED'):p.initial_prefix_seed(value)
    assert without_guard('PARTIAL_ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED')(value)['measured_closes']==0


def test_initial_reporting_does_not_repin_original_fresh_p00_origin():
    assert p.FRESH_TARGET_SHA=='0aaa2967a245b4eefc9097fd84b6227a0f99717c65dc88b21b2736aeecdf2d1d'
    assert p.FRESH_REQUEST_SHA=='13d68690a7e940bc52d1060098a04d577932f292b30418a29cbfc2346f242b0d'
