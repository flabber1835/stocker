"""Real immutable transport bytes and explicit nonfinancial authority checks."""
import ast,base64,json,sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('REQUEST238_TEST_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_p07_request238_review as p


def request():
 return dict(execution_mode=p.MODE,arms=['P07'],financial_resume_authorized=False,readonly_partial_review=True,
  readonly_source_witnesses=False,maximum_parallel_financial_workers=0,maximum_parallel_readonly_workers=1,
  **{p.FIELD:{'P07':p.declaration(p.target())}})


def test_actual_saved_august_target_preserves_failed_stops_and_full27_history():
 t=p.target();assert p.validate_target(t) and p.require_request(request(),t)
 assert (t['measured_closes'],len(t['repairs']))==(1426,27)
 assert t['manifest']==dict(member_count=639,raw_member_bytes=786073898)
 assert t['review_sha256'] is None and not t['financial_authority']
 assert [t['prior_stops'][n]['exit_code'] for n in ('preflight','worker','reviewer')]==[0,1,1]
 assert not p.entry.parent_transport.applies(t)


def test_every_required_literal_field_of_original_admitter_is_bound():
 import system_campaign_financial_partial as partial
 fn=next(n for n in ast.parse(Path(partial.crypto.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='admit')
 keys={n.slice.value for n in ast.walk(fn) if isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name)
  and n.value.id=='spec' and isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str)}
 prior=json.loads((C/'P07-request238-readonly-recovery-fact.json').read_bytes())
 assert keys-set(prior['target'])=={'stage'} and keys<=set(p.target())
 assert p.target()['stage']=='campaign-factual-suffix'
 assert p.fact()['original_incomplete_transport_fact_sha256']==p.sha((C/'P07-request238-readonly-recovery-fact.json').read_bytes())


@pytest.mark.parametrize('field,value',[('financial_resume_authorized',True),('readonly_partial_review',False),
 ('readonly_source_witnesses',True),('maximum_parallel_financial_workers',1),('maximum_parallel_financial_workers',False),
 ('maximum_parallel_readonly_workers',True),('arms',['P07','P03']),('execution_mode',p.entry.MODE)])
def test_readonly_request_cannot_gain_financial_authority(field,value):
 r=request();r[field]=value
 with pytest.raises(ValueError,match='ZERO_FINANCIAL'):p.require_request(r,p.target())


def test_financial_authority_guard_removal_is_detected(monkeypatch):
 r=request();r['maximum_parallel_financial_workers']=1
 with pytest.raises(ValueError):p.require_request(r,p.target())
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label=='REQUEST238_EXPLICIT_ZERO_FINANCIAL_READONLY_REQUEST' else old(ok,label))
 assert p.require_request(r,p.target())


class PublicArchive:
 def __init__(self):self.raw={n:base64.b64decode(b,validate=True) for n,b in p.fact()['public_member_bytes'].items()}
 def namelist(self):return [*self.raw,p.target()['encrypted_output']['name']]
 def getinfo(self,name):return SimpleNamespace(file_size=len(self.raw[name]))
 def read(self,name):return self.raw[name]


def test_original_failed_public_receipt_and_all_public_guards_preserved():
 a=PublicArchive();assert p.public_names(p.target(),a)==set(a.namelist())
 receipt=json.loads(a.raw['campaign-factual-P07.json'])
 assert receipt['run_id']==str(p.RUN) and receipt['head']==p.HEAD and receipt['status']==p.STATUS
 a.raw['campaign-factual-P07.json']+=b' '
 with pytest.raises(ValueError,match='PUBLIC'):p.public_names(p.target(),a)


def test_exact_two_july_records_match_original_authenticated_source():
 records=p.supplement_records()
 assert len(records)==2 and sum(map(len,records.values()))==1035
 assert all(name not in p.fact()['original_manifest'] for name in records)
 assert {json.loads(raw)['session'] for raw in records.values()}=={'2023-07-11','2023-07-28'}


def test_changed_historical_record_refused_and_guard_removal_falsifier(monkeypatch):
 value=deepcopy(p.fact());name=next(iter(value['observer_supplements']))
 item=value['observer_supplements'][name];item['base64']=base64.b64encode(base64.b64decode(item['base64'])+b' ').decode()
 monkeypatch.setattr(p,'fact',lambda:value)
 with pytest.raises(ValueError,match='UNCHANGED_AUTHENTICATED'):p.supplement_records()
 old=p.need;monkeypatch.setattr(p,'need',lambda ok,label:None if label.startswith('REQUEST238_UNCHANGED_AUTHENTICATED_ORIGINAL_JULY_RECORD:') else old(ok,label))
 assert p.supplement_records()[name].endswith(b' ')


def test_whole_original_failed_transport_has_only_qualified_size_option():
 before=p.previous.legacy_tree('admit');after=p.legacy('admit')
 assert after.__name__=='admit' and after.__globals__['HEAD']==p.HEAD and after.__globals__['RUN']==p.RUN
 assert after.__globals__['request_only_readonly'] is p.require_request
 assert after.__globals__['prove_refusal'] is p.prove_refusal
 assert any(isinstance(n,ast.BinOp) and ast.unparse(n)=='1024 * 1024 ** 2' for n in ast.walk(before))


def test_original_parent_reader_keeps_whole_qualified_transport(monkeypatch):
 seen={};origin=p.history.spec();r=request()
 scope=dict(seen=seen,p=p)
 exec("def reader(spec,root,key,inspector,*,request,authorize):\n seen['spec']=spec;seen['request']=request\n assert p.require_request(request,p.target())\n return 'EXPLICIT_NONCANONICAL_TRANSPORT_DTO'\n",scope)
 monkeypatch.setattr(p.entry.parent_transport,'admit',scope['reader'])
 assert p.admit_origin(origin,None,None,None,r)=='EXPLICIT_NONCANONICAL_TRANSPORT_DTO'
 assert seen==dict(spec=origin,request=r)


def test_all_four_mature_worker_bodies_are_unchanged():
 names=p.fact()['original4_AST']
 actual={n.name:p.sha(ast.dump(n,include_attributes=False).encode()) for n in ast.parse((C/'system_campaign_financial_resume.py').read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name in names}
 assert actual==names and p.entry.mature_review(__import__('system_campaign_financial_resume')).__name__=='review'


def test_selected_closed_request_and_imported_source_closure():
 import system_campaign_financial_resume as m
 r=json.loads((C/m.REQUEST).read_bytes())
 if not r.get(p.FIELD):pytest.skip('New read-only request not selected yet')
 assert r==m.expected_request() and p.require_request(r,p.target())
 imported={Path(v.__file__).name for v in list(sys.modules.values()) if getattr(v,'__file__',None)
  and Path(v.__file__).suffix=='.py' and Path(v.__file__).resolve().parent==C}
 assert imported<=set(r['sources']),sorted(imported-set(r['sources']))


def test_local_financial_entry_closed():
 with pytest.raises(ValueError,match='FINANCIAL_CALLBACK_FORBIDDEN'):p.deny()
 with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
  with p.worker_context(None,p.target(),mode='preflight',out=None,request=request()):pytest.fail('Local worker opened')


def test_launch_diagnostic_reports_guard_and_restores_trace(capsys):
 scope={};filename='EXPLICIT_NONCANONICAL_SOURCE_DTO'
 exec(compile("def launch():\n try:raise ValueError('REFUSED_FULL_SYSTEM_EXPLICIT_NONCANONICAL_DTO')\n except ValueError:return 2\n",filename,'exec'),scope)
 old=sys.gettrace();assert p.diagnose_launch(scope['launch'],filename)==2;assert sys.gettrace() is old
 result=json.loads(capsys.readouterr().out)
 assert result['exception_type']=='ValueError' and result['guard_code']=='REFUSED_FULL_SYSTEM_EXPLICIT_NONCANONICAL_DTO'


def test_launch_diagnostic_does_not_emit_arbitrary_exception_text(capsys):
 scope={};filename='EXPLICIT_NONCANONICAL_SOURCE_DTO'
 exec(compile("def launch():\n try:raise ValueError('EXPLICIT_NONCANONICAL_PRIVATE_DTO')\n except ValueError:return 2\n",filename,'exec'),scope)
 assert p.diagnose_launch(scope['launch'],filename)==2
 raw=capsys.readouterr().out;assert 'EXPLICIT_NONCANONICAL_PRIVATE_DTO' not in raw
 assert 'guard_code' not in json.loads(raw)


@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
