"""Invented numerical observations: common budgets, chronology and leak refusal."""
import ast,copy,math
from datetime import date
from fractions import Fraction as Q
from pathlib import Path
import pytest
from system_campaign_selection import assemble,lock,acquisition_records
from system_campaign_space import initial
from system_campaign_joint_space import joint_profiles
from system_campaign_facts import digest


def metrics(multiple,dd):
    days=(date(2020,12,31)-date(2018,1,2)).days;m=Q(str(multiple))
    return dict(anchor='2018-01-02',start='2018-01-03',end='2020-12-31',closes=755,
        initial_nav='50000',nav=str(50000*m),multiple=str(m),total_return=str(m-1),
        cagr=math.expm1(math.log(float(m))*365.2425/days),
        maximum_drawdown_magnitude=str(dd),measured_closes=756)


def envelopes():
    registry=joint_profiles();proposals=initial()[:2];result=[]
    for index,p in enumerate(proposals):
        rows=[dict(id=j['id'],group=str(k),metrics=metrics(1.,'.1'),turnover='1')
            for k,j in enumerate(registry['joint_profiles'])]
        rows[0]['metrics']=metrics(1.2,'.2') if index==0 else metrics(1.21,'.8')
        if index:
            rows[1]['metrics']=metrics(2.,'.3')
            rows[2]['metrics']=metrics(1.6,'.15')
            rows[3]['metrics']=metrics(1.3,'.10')
        result.append(dict(core_id=p['id'],parameters=p['parameters'],available_after='INITIAL',
            common_factual_basis_sha256='a'*64,numeric_review_sha256='b'*64,
            training=dict(cutoff='2020-12-31',records=rows,core_profile_sha256=digest(p['parameters']),
                no_evaluation_fields=True)))
    return result


def test_global_budgets_use_official_baseline_not_each_candidates_own_dd():
    e=envelopes();ids=[v['core_id'] for v in e]
    rows,base,scope=assemble(e,'2020-12-31',ids[0],ids,'c'*64)
    chosen=lock(rows,base,'2020-12-31',scope);joint=joint_profiles()['joint_profiles']
    assert chosen['budget_choices'][0]['id']==ids[1]+'::'+joint[3]['id']
    assert chosen['budget_choices'][1]['id']==ids[1]+'::'+joint[2]['id']
    assert chosen['budget_choices'][2]['id']==ids[1]+'::'+joint[2]['id']
    scores=acquisition_records(rows,base,'2020-12-31',scope['parameters'],initial_ids=ids)
    assert all(b['baseline_drawdown_magnitude']==.2 for r in scores for b in r['budgets'])


def test_future_fields_and_mixed_fact_versions_are_refused():
    e=envelopes();ids=[v['core_id'] for v in e]
    e[0]['training']['records'][0]['metrics']['evaluation_cagr']=99
    with pytest.raises(ValueError,match='TRAINING_METRIC_ONLY'):assemble(e,'2020-12-31',ids[0],ids,'c'*64)
    del e[0]['training']['records'][0]['metrics']['evaluation_cagr'];e[1]['common_factual_basis_sha256']='d'*64
    with pytest.raises(ValueError,match='UNIFORM_FACTS'):assemble(e,'2020-12-31',ids[0],ids,'c'*64)


def test_later_acquisitions_cannot_enter_earlier_lock_and_actual_guard_falsifier():
    e=envelopes();ids=[v['core_id'] for v in e];e[1]['available_after']='2022-12-30'
    rows,base,scope=assemble(e,'2020-12-31',ids[0],ids,'c'*64)
    assert {r['core_id'] for r in rows}=={ids[0]} and scope['later_only_core_ids_excluded']==[ids[1]]
    tree=ast.parse(Path(assemble.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='assemble')
    class Remove(ast.NodeTransformer):
        def visit_If(self,n):
            if any(isinstance(v,ast.Continue) for v in ast.walk(n)):return None
            return self.generic_visit(n)
    node=Remove().visit(node);space=dict(assemble.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-chronological-admission>','exec'),space)
    wrong,_,_=space['assemble'](e,'2020-12-31',ids[0],ids,'c'*64)
    assert {r['core_id'] for r in wrong}==set(ids)


def test_missing_paths_remain_unknown_and_no_false_complete_class_claim():
    e=envelopes();ids=[v['core_id'] for v in e]
    rows,base,scope=assemble(e[:1],'2020-12-31',ids[0],ids,'c'*64)
    result=lock(rows,base,'2020-12-31',scope)
    assert scope['missing_core_ids']==[ids[1]] and result['status'].startswith('PARTIAL_CLASS')
    assert not result['global_optimum_claim']
