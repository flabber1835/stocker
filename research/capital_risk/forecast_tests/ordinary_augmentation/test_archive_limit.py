"""Exact known transport selects an existing original bound; no restore or I/O."""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import pytest


class Fence:
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
            raise ImportError('ARCHIVE_LIMIT_DATA_ONLY:'+fullname)


sys.meta_path.insert(0,Fence())
import system_campaign_financial_partial as data


def target():
    return deepcopy(json.loads((data.HERE/'system-campaign-financial-partials.json').read_bytes())['arms']['P07'])


def test_actual_zip_exceeds_512_mib_and_passes_only_the_existing_one_gib_option():
    spec=target()
    assert spec['zip_bytes']==576040524 and spec['manifest']['raw_member_bytes']==731251188
    with pytest.raises(ValueError,match='ENCRYPTED_DOWNLOAD_BOUND'):data.crypto.archive_bound(spec,512*1024**2)
    assert data.reviewed_archive_limit(spec)==1024**3
    data.crypto.archive_bound(spec,data.reviewed_archive_limit(spec))
    assert data.sha(Path(data.crypto.__file__).read_bytes())==data.CRYPTO_SHA


@pytest.mark.parametrize('field,value',[('arm','P05'),('run_id',42100223337),('head','0'*40),
    ('artifact_id',13451345163),('zip_sha256','0'*64)])
def test_unknown_large_archive_never_gets_the_selected_option(field,value):
    spec=target();spec[field]=value
    assert data.reviewed_archive_limit(spec)==512*1024**2
    with pytest.raises(ValueError,match='ENCRYPTED_DOWNLOAD_BOUND'):
        data.crypto.archive_bound(spec,data.reviewed_archive_limit(spec))


@pytest.mark.parametrize('mutation',['size','manifest_count','manifest_size','selected_file','outer','cursor',
    'float_closes','authority','admitted','receipt','unknown','oom','review_failure','bool_exit'])
def test_known_clock_with_changed_commitments_or_failed_stop_refuses(mutation):
    spec=target()
    if mutation=='size':spec['zip_bytes']+=1
    elif mutation=='manifest_count':spec['manifest']['member_count']+=1
    elif mutation=='manifest_size':spec['manifest']['raw_member_bytes']=1024**3
    elif mutation=='selected_file':spec['selected_file']['sha256']='0'*64
    elif mutation=='outer':spec['outer_sha256']='0'*64
    elif mutation=='cursor':spec['selected_session']='2022-12-20'
    elif mutation=='float_closes':spec['measured_closes']=1238.
    elif mutation=='authority':spec['financial_authority']=True
    elif mutation=='admitted':spec['financial_predecessor_admitted']=True
    elif mutation=='receipt':spec['receipt_status']='COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
    elif mutation=='unknown':spec['prior_stops']['worker']['stopped']=False
    elif mutation=='oom':spec['prior_stops']['worker']['oom_killed']=True
    elif mutation=='review_failure':spec['prior_stops']['reviewer']['exit_code']=1
    else:spec['prior_stops']['worker']['exit_code']=True
    with pytest.raises(ValueError):data.reviewed_archive_limit(spec)


def test_an_ordinary_small_historical_archive_keeps_the_original_limit():
    spec=target();spec['artifact_id']=1;spec['zip_bytes']=1024
    assert data.reviewed_archive_limit(spec)==512*1024**2
    data.crypto.archive_bound(spec,data.reviewed_archive_limit(spec))


def test_removing_positive_stop_scope_would_select_an_oom_archive():
    spec=target();spec['prior_stops']['worker']['oom_killed']=True
    with pytest.raises(ValueError,match='POSITIVE_REVIEW_AND_STOP_SCOPE'):data.reviewed_archive_limit(spec)
    fn,=[n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='reviewed_archive_limit']
    guards=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(a,ast.Constant) and a.value=='PARTIAL_QUALIFIED_ONE_GIB_POSITIVE_REVIEW_AND_STOP_SCOPE' for a in n.value.args)]
    assert len(guards)==1;fn.body.remove(guards[0]);namespace=dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<archive-stop-guard-removal-data-only>','exec'),namespace)
    assert namespace['reviewed_archive_limit'](spec)==1024**3


@pytest.mark.parametrize('name',['research.pooled_vacancy_funding','stock_strategy_shared.wealth_core','sentinel.controller','numpy','pandas'])
def test_financial_runtime_import_fences(name):
    with pytest.raises(ImportError,match='DATA_ONLY'):importlib.import_module(name)
