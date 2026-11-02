"""Metadata/guard falsifiers only; canonical cases execute solely on GitHub."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_campaign_remainder_input as inputs
from system_campaign_remainder_facts import validate


def document():
    parent = dict(file_sha256='1'*64, outer_sha256='2'*64, inner_sha256='3'*64,
        state_sha256='4'*64, input_sha256='5'*64, source_sha256='6'*64, session='2025-04-30')
    refs = [dict(reference='case:'+str(i), description='Exact commitment', sha256=str(i)*64) for i in range(4)]
    value = dict(schema=inputs.SCHEMA, predecessor_checkpoint_sha256=parent['inner_sha256'], parent=parent,
        catalog_sha256='7'*64, private_sha256='8'*64, ordinary_overlay_sha256='9'*64,
        treatment='CANONICAL_ACTIONS_AND_UNOWNED_COMPLETE_OUTCOME_RANGE_PROOF', source_evidence=refs)
    return value, dict(resume_session=parent['session'], predecessor_checkpoint_sha256=parent['inner_sha256'],
        parent=deepcopy(parent), expected_evidence=deepcopy(refs), catalog_sha256='7'*64,
        private_sha256='8'*64, ordinary_sha256='9'*64)


@pytest.mark.parametrize('field', ['file_sha256','outer_sha256','inner_sha256','state_sha256',
    'input_sha256','source_sha256'])
def test_each_wrong_own_parent_identity_refuses(tmp_path, field):
    value, kwargs = document(); value['parent'][field] = 'a'*64
    path = tmp_path/'input.json'; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='EXACT_OWN_PARENT'):
        inputs.parse(path, **kwargs)


@pytest.mark.parametrize('field', ['catalog_sha256','private_sha256','ordinary_overlay_sha256'])
def test_changed_derived_financial_input_refuses(tmp_path, field):
    value, kwargs = document(); value[field] = 'a'*64
    path = tmp_path/'input.json'; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='EXACT_CATALOG_PRIVATE'):
        inputs.parse(path, **kwargs)


def test_exact_unconsumed_parse_and_duplicate_key_refusal(tmp_path):
    value, kwargs = document(); path = tmp_path/'input.json'; raw = json.dumps(value)
    path.write_text(raw)
    obj = inputs.parse(path, **kwargs)
    assert obj.sha256 == inputs.sha(path.read_bytes()) and obj.earliest_affected_session == '2025-05-16'
    with pytest.raises(ValueError, match='UNCONSUMED'):
        inputs.parse(path, **dict(kwargs, resume_session='2025-05-16'))
    path.write_text(raw[:-1]+',"schema":"'+inputs.SCHEMA+'"}')
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        inputs.parse(path, **kwargs)


def clean_state():
    return SimpleNamespace(wealth_core={'episodes':{}}, pending=[],
        ledger={'receivables':[], 'events':[{'security_id':'A','event_type':'DIVIDEND_PAID'}]},
        last_evidence={'cash_distributions':{'pending':[]}})


@pytest.mark.parametrize('surface', ['owned','ordered','receivable','forward'])
def test_every_financial_entitlement_surface_refuses(surface):
    state = clean_state()
    if surface == 'owned': state.wealth_core['episodes']['0'] = {'security_id':'A'}
    if surface == 'ordered': state.pending.append({'security_id':'A'})
    if surface == 'receivable': state.ledger['receivables'].append({'security_id':'A','amount':1.})
    if surface == 'forward': state.last_evidence['cash_distributions']['pending'].append({'security_id':'A'})
    with pytest.raises(ValueError): inputs.require_no_position(state,'A')


def test_settled_historical_dividend_is_not_an_outstanding_right():
    inputs.require_no_position(clean_state(),'A')


def test_actual_episode_guard_removal_admits_owned_case():
    source = ast.parse((ROOT/'system_campaign_remainder_input.py').read_bytes())
    fn = next(v for v in source.body if isinstance(v,ast.FunctionDef) and v.name=='require_no_position')
    owned = next(v for v in ast.walk(fn) if isinstance(v,ast.Call) and v.args
                 and isinstance(v.args[-1],ast.Constant)
                 and v.args[-1].value=='REMAINDER_SENSOR_MUST_NOT_BE_OWNED')
    comparison = next(v for v in ast.walk(owned) if isinstance(v,ast.Compare)
                      and ast.unparse(v)=="v['security_id'] != sid")
    class Remove(ast.NodeTransformer):
        def visit_Compare(self,node):
            return ast.copy_location(ast.Constant(True),node) if node is comparison else self.generic_visit(node)
    changed = Remove().visit(fn); namespace = dict(vars(inputs))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[changed],type_ignores=[])),
        '<actual-owned-guard-removal>','exec'),namespace)
    state = clean_state();state.wealth_core['episodes']['0']={'security_id':'A'}
    with pytest.raises(ValueError): inputs.require_no_position(state,'A')
    namespace['require_no_position'](state,'A')


@pytest.mark.parametrize('ticker,field,value', [('DFS','exchange_ratio','1.0'),('CDTX','cash_per_share',15505.),
    ('TMHC','cash_per_share',72.51)])
def test_contractual_action_mutation_refuses(ticker,field,value):
    catalog = json.loads((ROOT/inputs.CATALOG).read_bytes())
    case = next(v for v in catalog['cases'] if v['ticker']==ticker); case['added'][field]=value
    with pytest.raises(ValueError): validate(catalog)


def test_cvr_floor_substitution_and_tmhc_missing_quote_are_explicit():
    catalog = validate(json.loads((ROOT/inputs.CATALOG).read_bytes()))
    by = {v['ticker']:v for v in catalog['cases']}
    assert 'added' not in by['BPMC'] and 'added' not in by['ETNB']
    assert by['TMHC']['event_quote']['present'] is False
    by['ETNB']['consideration_bounds']=['14.50','14.50']
    with pytest.raises(ValueError): validate(catalog)


def test_exact_source_bound_orchestration_and_worker_scope():
    from system_campaign_pxd_financial_body import tree
    from system_campaign_p02_remainder_job import SITES
    node = next(v for v in ast.parse((ROOT/'system_campaign_p02_remainder_run.py').read_bytes()).body
                if isinstance(v,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ECONOMIC' for t in v.targets))
    body = tree('system_campaign_p02_q4_cash_run.py','economic',ast.literal_eval(node.value),
        insert_after='actual_packets_and_own_cash_gate')
    assert ast.unparse(body).count('backtest.main') == 1
    job = tree('system_campaign_p02_close_job.py','main',SITES,
        expected_counts={'COMPLETE_P02_CLOSE_SUFFIX_REVIEWED':2})
    text = ast.unparse(job)
    assert 'p02-remainder' in text and 'STOP_UNKNOWN' in text and 'stopped_run' in text


def bounded_reader_fixture(tmp_path):
    source = ast.parse((ROOT/'system_campaign_remainder_review.py').read_bytes())
    selected = [v for v in source.body if isinstance(v,(ast.ClassDef,ast.FunctionDef))
                and v.name in ('CertificateRows','seed_tree')]
    def need(value,reason):
        if not value:raise ValueError(reason)
    namespace = dict(ast=ast,json=json,need=need)
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<bounded-metadata-reader>','exec'),namespace)
    tree = namespace['seed_tree']((ROOT/'system_campaign_uncertainty_review.py').read_bytes())
    schema='research.leadership-uncertainty-certificate/1';watch_schema='research.leadership-uncertainty-certificate-commitment/1'
    chain=inputs.digest(schema);rows=[];financial=[];watches=[]
    for day in ('2025-05-01','2025-05-02'):
        row=dict(schema=schema,session=day,next_state_sha256=inputs.sha(day.encode()),input_sha256='1'*64)
        chain=inputs.digest(dict(previous=chain,record=row));row['chain_sha256']=chain;rows.append(row)
        financial.append(dict(session=day,state_sha256=row['next_state_sha256'],input_sha256='1'*64))
        watches.append(dict(schema=watch_schema,session=day,next_state_sha256=row['next_state_sha256'],
            input_sha256='1'*64,certificate_chain_sha256=chain))
    def committed(book,cp,name):return [] if name=='formation' else financial if name=='daily' else watches
    namespace.update(committed_rows=committed,DAY='2019-10-22',WATCH_SCHEMA=watch_schema,SCHEMA=schema,
        digest=inputs.digest,encoded=inputs.encoded,row_schema=lambda row,model:row['schema']==schema,model=None)
    exec(compile(tree,'<actual-original-seed-bounded-storage>','exec'),namespace)
    path=tmp_path/'uncertainty-certificate.jsonl'
    def write():path.write_bytes(b''.join(inputs.encoded(v)+b'\n' for v in rows))
    write()
    return namespace, rows, financial, watches, path, write


def test_actual_original_chain_reader_keeps_only_one_row(tmp_path):
    namespace,rows,_,_,_,_=bounded_reader_fixture(tmp_path)
    result=namespace['seed'](tmp_path,{'source_cursor':'2025-05-02'})
    assert len(result)==2 and result[-1]==rows[-1] and list(result.new(1))==rows[1:]
    assert set(result.__dict__)=={'path','cursor','count','last'}


@pytest.mark.parametrize('surface',['chain','financial_state','financial_input','watch_chain','axis'])
def test_bounded_original_reader_preserves_every_binding_guard(tmp_path,surface):
    namespace,rows,financial,watches,path,write=bounded_reader_fixture(tmp_path)
    if surface=='chain':rows[0]['chain_sha256']='f'*64;write()
    if surface=='financial_state':financial[0]['state_sha256']='f'*64
    if surface=='financial_input':financial[0]['input_sha256']='f'*64
    if surface=='watch_chain':watches[0]['certificate_chain_sha256']='f'*64
    if surface=='axis':financial[0]['session']='2025-04-30'
    with pytest.raises(ValueError):namespace['seed'](tmp_path,{'source_cursor':'2025-05-02'})


def test_dfs_component_supplies_both_required_conversion_bases():
    tree=ast.parse((ROOT/'system_campaign_remainder_gate.py').read_bytes())
    dictionaries=[v for v in ast.walk(tree) if isinstance(v,ast.Call) and isinstance(v.func,ast.Name)
                  and v.func.id=='dict' and {'source_signal_to_raw_scale','delivered_signal_to_raw_scale'}
                  <= {k.arg for k in v.keywords}]
    assert len(dictionaries)==1
    assert 'REMAINDER_DFS_ORIGINAL_MISSING_BASIS_GUARD_REPRODUCED' in (ROOT/'system_campaign_remainder_gate.py').read_text()
