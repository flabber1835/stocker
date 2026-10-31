"""Exact finish boundary; invented checkpoint metadata only."""
import ast,copy
from pathlib import Path
import pytest
from system_campaign_finish_run import selected_current


def case():
    c={'sha256':'current','source_cursor':'2025-12-31','completed':2010}
    s={'selected_checkpoint':'book/checkpoint.json.gz','outer_sha256':'current','selected_session':'2025-12-31'}
    return s,c


def test_prior_checkpoint_and_finished_book_refuse():
    s,c=case();selected_current(s,c)
    s['selected_checkpoint']='book/month-end/2024-12-31.json.gz'
    with pytest.raises(ValueError,match='EXACT_INCOMPLETE_CURRENT'):selected_current(s,c)
    s,c=case();c['source_cursor']=s['selected_session']='2026-07-31';c['completed']=2156
    with pytest.raises(ValueError,match='EXACT_INCOMPLETE_CURRENT'):selected_current(s,c)


def test_actual_current_boundary_guard_removal_falsifier():
    s,c=case();s['outer_sha256']='earlier'
    with pytest.raises(ValueError,match='EXACT_INCOMPLETE_CURRENT'):selected_current(s,c)
    tree=ast.parse(Path(selected_current.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='selected_current')
    node.body=[ast.Pass()];scope=dict(selected_current.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-current-checkpoint-guard>','exec'),scope)
    assert scope['selected_current'](s,c) is None


def test_finish_actual_timeout_and_dependency_closure():
    from system_campaign_finish_job import known_timeout,SOURCES
    from forecast_tests.test_basis_job_sources import dependencies
    assert not dependencies(SOURCES)-set(SOURCES)
    r={'status':'PARTIAL_FACTUAL_PREFIX_REVIEWED','worker':{'stopped':True,'exit_code':0,'oom_killed':False,'wait_error':'TimeoutExpired'},
        'reviewer':{'stopped':True,'exit_code':0,'oom_killed':False}}
    s={'selected_checkpoint':'book/checkpoint.json.gz','timeout_known_stopped':True};known_timeout(r,s)
    for field,bad in [('stopped',False),('oom_killed',True),('exit_code',1),('wait_error',None)]:
        broken=copy.deepcopy(r);broken['worker'][field]=bad
        with pytest.raises(ValueError,match='ACTUAL_REVIEWED_ORDERLY_TIMEOUT'):known_timeout(broken,s)
