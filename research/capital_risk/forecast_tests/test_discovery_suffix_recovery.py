"""Pure transport/stub guards for exact diagnostic suffixes; no strategy."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from types import ModuleType

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import system_campaign_discovery_suffix_parent as parent
import system_campaign_discovery_suffix_replay as replay
import system_campaign_discovery_suffix_job as job
import system_campaign_parallel_discovery_export as export
from system_campaign_discovery_context import TAINT,digest,encoded


def test_original_suffix_ast_only_declared_continuation_sites_and_linear_proof_commitment():
    tree=replay.suffix_tree(replay.proven.exact_raw(replay.original));text=ast.unparse(tree)
    assert 'runtime.advance(run, published)' in text
    assert 'first.prepare(buffer, run)' in text and 'first.after(run, next_run)' in text
    assert 'observed = list(old_days)' in text and "chain = saved['transition_chain_sha256']" in text
    assert 'retained_anchor_qualifications=anchor_gate.commitment()' in text
    assert 'recovered_stream(book, saved)' in text and 'if len(observed) == len(old_days) + 1:' in text
    assert 'complete = observed == full_wanted' in text
    compile(tree,'<actual-common-suffix>','exec')


def test_crypto_body_retains_authentication_and_complete_inventory_before_diagnostic_parse():
    tree=parent.admission_tree();text=ast.unparse(tree)
    assert 'authenticate(z, asset, key)' in text and 'seen == set(inventory)' in text
    assert text.index('authenticate(z, asset, key)') < text.index('tarfile.open(') < text.index('validate_contents(')
    assert 'proof_review_refusal' not in text and "cp['run']" not in text
    parent.compile_body(tree,vars(parent.crypto))


@pytest.mark.parametrize('arm',parent.ARMS)
def test_own_scopes_are_exact_diagnostic_not_financial_origin(arm):
    spec=parent.specification(arm)
    assert spec['financial_strict_predecessor']['arm']==arm
    assert spec['expected_remaining_sessions']+spec['transitions']==spec['cumulative_expected_sessions']
    assert spec['source_cursor']==spec['selected_session']<spec['next_session']
    assert len(spec['full_current_streams'])==6


def test_prefix_keeps_tail_explicit_and_refuses_changed_committed_bytes():
    raw=b'{}\n';commit=dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),
                         last_record_sha256=hashlib.sha256(raw).hexdigest())
    assert parent.verify_prefix(raw+b'unsent\n',commit,last=True)==raw
    with pytest.raises(ValueError,match='COMMITTED_PREFIX'):parent.verify_prefix(b'[]\nunsent\n',commit)


def test_committed_events_continue_without_adopting_full_unsent_tail(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    import test_discovery_context as stubs
    monkeypatch.setattr(replay.context_source,'hosted',lambda:None)
    previous=tmp_path/'old';previous.mkdir();out=tmp_path/'new';out.mkdir()
    event=dict(sequence=0,authority=TAINT,context=dict(bypass=True))
    chain=digest(dict(previous=digest(dict(authority=TAINT)),event=event))
    raw=encoded(dict(event=event,chain_sha256=chain))+b'\n'
    (previous/'discovery-events.jsonl').write_bytes(raw+b'UNSENT_TAIL')
    saved=dict(events=dict(bytes=len(raw),prefix_sha256=hashlib.sha256(raw).hexdigest(),rows=1,chain_sha256=chain),
               discovery_transitions=461)
    value=replay.ContinuedContext(out,source_sha256='1'*64,previous=previous,saved=saved,bindings=stubs.bindings())
    with value as ctx:
        ctx.current=(stubs.prior(),stubs.Publication());ctx.emit('SYNTHETIC_SUFFIX')
        actual=(out/'discovery-events.jsonl').read_bytes()
        assert actual.startswith(raw) and b'UNSENT_TAIL' not in actual and ctx.sequence==2 and ctx.transitions==461
        assert (previous/'discovery-events.jsonl').read_bytes()==raw+b'UNSENT_TAIL'


def test_first_inline_adjacency_guard_and_actual_removal_falsifier(tmp_path):
    before=dict(state='SYNTHETIC');state=SimpleNamespace(state_hash=digest(before),to_dict=lambda:deepcopy(before))
    run=SimpleNamespace(state=state,input_sha256='1'*64)
    anchor=SimpleNamespace(prepare=lambda *a:SimpleNamespace(),after=lambda *a:None)
    spec=dict(next_session='2020-03-02',state_sha256=digest(before),input_sha256='1'*64,
              runtime_checkpoint_sha256='2'*64)
    gate=replay.FirstTransition(tmp_path,{},spec,anchor)
    buffer=SimpleNamespace(current=SimpleNamespace(day='2020-03-03'))
    with pytest.raises(ValueError,match='FIRST_ACTUAL_NEXT_SESSION'):gate.prepare(buffer,run)
    owner,=[n for n in ast.parse(Path(replay.__file__).read_bytes()).body if isinstance(n,ast.ClassDef) and n.name=='FirstTransition']
    fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='prepare']
    for n in ast.walk(fn):
        if isinstance(n,ast.If):n.body=[v for v in n.body if not(isinstance(v,ast.Expr) and any(isinstance(k,ast.Constant)
            and k.value=='SUFFIX_FIRST_ACTUAL_NEXT_SESSION_PRIOR_STATE_INPUT_ADJACENCY' for k in ast.walk(v)))]
    scope=dict(vars(replay));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<actual-suffix-adjacency-guard-removed>','exec'),scope)
    scope['prepare'](gate,buffer,run);assert gate.prepared


def test_disjoint_book_keeps_complete_lineage_and_calls_actual_recovery_api_before_append(tmp_path,monkeypatch):
    previous=tmp_path/'previous';previous.mkdir();(previous/'diagnostic-book').mkdir()
    (previous/'diagnostic-book/discovery-checkpoint.json.gz').write_bytes(b'SYNTHETIC_OLD_CP')
    old=b'{}\n';full=old+b'SYNTHETIC_UNSENT_TAIL\n'
    entry=dict(bytes=len(old),prefix_sha256=hashlib.sha256(old).hexdigest(),
               last_record_sha256=hashlib.sha256(old).hexdigest())
    for n in ('daily','watch','formation','monthly'):(previous/f'diagnostic-book/{n}.jsonl').write_bytes(full)
    (previous/'discovery-events.jsonl').write_bytes(b'SYNTHETIC_COMPLETE_EVENTS_WITH_TAIL')
    (previous/'retained-anchor-events.jsonl').write_bytes(b'SYNTHETIC_COMPLETE_ANCHORS_WITH_TAIL')
    output=tmp_path/'out';output.mkdir();book=output/'diagnostic-book'
    saved=dict(journals={n:dict(entry) for n in ('daily','watch','formation','monthly')})
    replay.seed_book(book,previous,saved)
    assert (book/'daily.jsonl').read_bytes()==full
    assert (output/'lineage/diagnostic-predecessor/diagnostic-book/daily.jsonl').read_bytes()==full
    assert (output/'lineage/diagnostic-predecessor/diagnostic-book/discovery-checkpoint.json.gz').read_bytes()==b'SYNTHETIC_OLD_CP'
    calls=[]
    class Journal:
        def __init__(self,path,resume):assert Path(path)==book and resume
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def verify(self,value):assert value==saved['journals'];calls.append('verify')
        def recover(self,value):
            assert calls==['verify'];calls.append('recover');tails=[]
            for n,c in value.items():
                raw=(book/(n+'.jsonl')).read_bytes();path=book/('interrupted-'+n+'-'+'1'*32+'.jsonl')
                path.write_bytes(raw[c['bytes']:]);tails.append(path)
                (book/(n+'.jsonl')).write_bytes(raw[:c['bytes']])
            return tails
        def commitment(self):
            return {n:dict(bytes=(book/(n+'.jsonl')).stat().st_size,
                prefix_sha256=hashlib.sha256((book/(n+'.jsonl')).read_bytes()).hexdigest(),
                last_record_sha256=hashlib.sha256((book/(n+'.jsonl')).read_bytes().splitlines(keepends=True)[-1]).hexdigest())
                for n in saved['journals']}
    pkg=ModuleType('research.pooled_vacancy_funding');pkg.journal=SimpleNamespace(Journal=Journal)
    monkeypatch.setitem(sys.modules,'research.pooled_vacancy_funding',pkg)
    with replay.recovered_stream(book,saved) as stream:
        assert calls==['verify','recover'] and stream.commitment()==saved['journals']
        assert all((book/(n+'.jsonl')).read_bytes()==old for n in saved['journals'])
    proof=json.loads((output/'actual-journal-recovery.json').read_bytes())
    assert proof['actual_canonical_journal_recover'] and proof['recovered_tails']['daily']['bytes']>0
    assert (previous/'diagnostic-book/daily.jsonl').read_bytes()==full


@pytest.mark.parametrize('arm',parent.ARMS)
def test_real_marker_encrypt_authenticate_decrypt_before_parent(tmp_path,monkeypatch,arm):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40)
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='a'*64)))
    proof=export.qualify_export(tmp_path/'marker',request,arm)
    assert proof['synthetic_marker_only'] and not proof['market_or_financial_state_processed']


def test_worker_fences_and_exact_disjoint_readonly_mounts(tmp_path,monkeypatch):
    monkeypatch.setattr(job.os,'getuid',lambda:1001,raising=False)
    monkeypatch.setattr(job.os,'getgid',lambda:1001,raising=False)
    for arm in job.SELECTED_ARMS:
        name=f'capital-system-diagnostic-suffix-{arm.lower()}-worker-123-1'
        cmd=job.worker_command(name,arm,tmp_path/'source',tmp_path/'frozen',tmp_path/'out',tmp_path/'old',tmp_path/'previous')
        assert cmd[cmd.index('-B'):]==job.entrypoint(arm) and cmd[cmd.index('--network')+1]=='none'
        assert any('target=/previous,readonly' in v for v in cmd)
        value=dict(Name='/'+name,Image=job.inspector_source.EXECUTION_IMAGE,Id='1'*64,
            HostConfig=dict(NetworkMode='none',Memory=8*1024**3,MemorySwap=8*1024**3,NanoCpus=2000000000,
                PidsLimit=64,ReadonlyRootfs=True,CapDrop=['ALL'],SecurityOpt=['no-new-privileges']),
            Config=dict(Cmd=job.entrypoint(arm),WorkingDir='/variant',User='1001:1001',Env=[],
                Labels={'research.study':'full-system-search-20261029','research.role':'worker'}),
            Mounts=[dict(Destination=n,Type='bind',RW=n=='/out') for n in ('/variant','/frozen','/driver','/out','/old','/previous')])
        monkeypatch.setattr(job.inspector_source.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
        assert job.inspect(name,'1'*64)==value
        value['Mounts'][-1]['RW']=True
        with pytest.raises(ValueError,match='MOUNTS'):job.inspect(name,'1'*64)


def test_unknown_does_not_snapshot_and_public_phase_omits_exception_values(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_SHA','1'*40);monkeypatch.setenv('RUNNER_TEMP',str(tmp_path))
    monkeypatch.setattr(job,'memory_bytes',lambda:dict(MemAvailable=123))
    try:raise ValueError('SYNTHETIC_PRIVATE_MARKET_VALUE')
    except ValueError as error:job.phase(tmp_path/'phase.json','P03','FAILURE',error)
    raw=(tmp_path/'phase.json').read_bytes()
    assert b'SYNTHETIC_PRIVATE_MARKET_VALUE' not in raw and b'ValueError' in raw
    monkeypatch.setattr(export,'sealed',lambda *a:(_ for _ in ()).throw(AssertionError('Snapshot forbidden')))
    request=tmp_path/'request.json';request.write_text(json.dumps(dict(protocol_sha256='a'*64)))
    value=dict(arm='P03',stage='campaign-disposable-discovery',financial_authority=False,
        account_performance_computed=False,production_contacted=False,status='DIAGNOSTIC_SUFFIX_WRITER_STOP_UNKNOWN_NO_SNAPSHOT')
    assert not export.finish_export(value,tmp_path/'ABSENT',tmp_path/'public.json',b'x'*32,request,known=False)['encrypted_output_exported']


def test_marker_precedes_both_fetches_and_worker_and_qualification_is_reused():
    raw=Path(job.__file__).read_text();fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    text=ast.unparse(fn)
    assert text.index('qualify_export(')<text.index('admit_strict(')<text.index('admit_diagnostic(')<text.index('stopped_run(')
    assert text.count('stopped_run(')==1 and 'qualify_wait_seconds' not in text
    workflow=(Path(__file__).resolve().parents[3]/'.github/workflows/capital-system-discovery-suffix.yml').read_text()
    assert 'max-parallel: 2' in workflow and 'fail-fast: false' in workflow and 'retention-days: 7' in workflow
    request=job.expected_request()
    assert request['arms']==['P03','P05']
    assert parent.SPINOFF_SPEC not in request['sources']
    assert 'system_campaign_discovery_spinoff_deferral.py' not in request['sources']
