"""Authentic manifest DATA and explicit noncanonical export-assembly DTOs."""
import hashlib,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
import system_campaign_preflight_export as p


def test_actual_FIN366_inventory_retains_every_book_and_unique_member():
 f=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/financial366-source-snapshot/authenticated-artifact-13587599730/authenticated-manifest.json')
 if not f.exists():pytest.skip('authenticated FIN366 inventory required')
 inventory=json.loads(f.read_bytes())['members'];before=deepcopy(inventory);value=p.validate(p.plan(inventory),inventory)
 assert value['original_bytes']==980668378 and value['omitted_bytes']==195677611
 assert value['kept_bytes']+len(p.encoded(value))<800_000_000
 assert {n for n in inventory if n.startswith(('book/','lineage/','parent-preflight/book/','parent-preflight/lineage/'))}<=set(value['kept_paths'])
 assert all(pin['kept_path'] in value['kept_paths'] for pin in value['omitted_duplicates'].values())
 assert inventory==before and value['financial_sessions_advanced']==0


def inventory_DTO():return {'A.bin':dict(bytes=p.MINIMUM,sha256='a'*64),'B.bin':dict(bytes=p.MINIMUM,sha256='b'*64),'parent-preflight/A.bin':dict(bytes=p.MINIMUM,sha256='a'*64),'book/EXPLICIT_NONCANONICAL_DTO.bin':dict(bytes=p.MINIMUM,sha256='a'*64)}


def test_equal_size_different_hash_does_not_allow_omission():
 inventory=inventory_DTO();value=p.plan(inventory);value['omitted_duplicates']['parent-preflight/A.bin']['kept_path']='B.bin'
 with pytest.raises(ValueError,match='EXACT_ALREADY_KEPT'):p.validate(value,inventory)


def test_exact_byte_guard_removal_falsifier(monkeypatch):
 inventory=inventory_DTO();value=p.plan(inventory);value['omitted_duplicates']['parent-preflight/A.bin']['kept_path']='B.bin'
 with pytest.raises(ValueError):p.validate(value,inventory)
 original=p.need;monkeypatch.setattr(p,'need',lambda v,label:None if label=='PREFLIGHT_EXPORT_EXACT_ALREADY_KEPT_BYTES_NO_ALIAS_CHAIN' else original(v,label))
 assert p.validate(value,inventory)['omitted_duplicates']['parent-preflight/A.bin']['kept_path']=='B.bin'


@pytest.mark.parametrize('name',['../escape','/absolute','C:/escape','a\\b','a//b','a/./b','.'])
def test_unsafe_or_aliased_paths_refused(name):
 with pytest.raises(ValueError):p.safe(name)


def test_plaintext_bound_remains_one_gib():
 inventory={'book/EXPLICIT_NONCANONICAL_SIZE_DTO':dict(bytes=p.LIMIT,sha256='a'*64)}
 with pytest.raises(ValueError,match='ONE_GIB'):p.validate(p.plan(inventory),inventory)


@pytest.mark.parametrize('change',['live','unknown','oom'])
def test_live_or_unknown_or_oom_writer_forbids_export(tmp_path,change):
 for i,name in enumerate(('parent-preflight/worker-inspect.json','worker-inspect.json','stopped-review/worker-inspect.json')):
  state=dict(Running=False,OOMKilled=False,ExitCode=0)
  if i==1:state.update({'Running':True} if change=='live' else {'ExitCode':None} if change=='unknown' else {'OOMKilled':True})
  path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(p.encoded(dict(EXPLICIT_NONCANONICAL_INSPECTION_DTO=True,Id='a'*64,State=state)))
 with pytest.raises(ValueError,match='WRITERS_POSITIVELY_STOPPED'):p.stopped(tmp_path)


def test_unselected_policy_calls_whole_original_seal_unchanged(tmp_path):
 request=tmp_path/'request.json';request.write_bytes(b'{}');args=(tmp_path/'absent',tmp_path/'output',b'EXPLICIT_NONCANONICAL_KEY_DTO',request,'P06')
 expected=object();calls=[]
 def original(*a,**k):calls.append((a,k));return expected
 assert p.bind_seal(original)(*args,stage='DTO') is expected and calls==[(args,dict(stage='DTO'))]


@pytest.mark.parametrize('fail',[False,True])
def test_owned_noncanonical_export_view_seals_and_cleans_without_mutating_original(tmp_path,monkeypatch,fail):
 root=tmp_path/'financial-resume-output-P06';root.mkdir();(root/'parent-preflight').mkdir()
 raw=b'EXPLICIT_NONCANONICAL_DUPLICATE_PAYLOAD_DTO'+b'x'*p.MINIMUM
 for name in ('source.bin','parent-preflight/source.bin'):(root/name).write_bytes(raw)
 for name in ('parent-preflight/worker-inspect.json','worker-inspect.json','stopped-review/worker-inspect.json'):
  path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(p.encoded(dict(EXPLICIT_NONCANONICAL_INSPECTION_DTO=True,Id='a'*64,State=dict(Running=False,OOMKilled=False,ExitCode=0))))
 request=tmp_path/'noncanonical-request.json';request.write_bytes(p.encoded({p.FIELD:p.POLICY,'sources':{Path(p.__file__).name:hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()}}))
 monkeypatch.setattr(p,'hosted_root',lambda value:(root,tmp_path));before=p.inventory(root);seen=[]
 def original(view,*args,**kwargs):
  seen.append(view);assert (view/'source.bin').read_bytes()==raw and not (view/'parent-preflight/source.bin').exists()
  receipt=json.loads((view/p.RECEIPT).read_bytes());assert receipt['original_inventory']==before
  if fail:raise RuntimeError('EXPLICIT_NONCANONICAL_SEAL_FAILURE_DTO')
  return dict(EXPLICIT_NONCANONICAL_ASSET_DTO=True)
 seal=p.bind_seal(original)
 if fail:
  with pytest.raises(RuntimeError):seal(root,tmp_path/'out',b'DTO',request,'P06')
 else:assert seal(root,tmp_path/'out',b'DTO',request,'P06')['EXPLICIT_NONCANONICAL_ASSET_DTO'] is True
 assert p.inventory(root)==before and len(seen)==1 and not seen[0].parent.exists()


def test_local_policy_refuses_before_view_creation(tmp_path,monkeypatch):
 monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
 request=tmp_path/'request.json';request.write_bytes(p.encoded({p.FIELD:p.POLICY,'sources':{Path(p.__file__).name:hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()}}))
 root=tmp_path/'must-not-exist'
 with pytest.raises(ValueError):p.bind_seal(lambda *a,**k:None)(root,tmp_path/'out',b'DTO',request,'P06')
 assert not root.exists() and not list(tmp_path.glob('research-preflight-export-view-*'))


def test_original_synthetic_marker_probe_is_preserved_exactly(tmp_path,monkeypatch):
 root=tmp_path/'financial-resume-probe-P06';root.mkdir();(root/'marker.json').write_bytes(p.PROBE)
 request=tmp_path/'request.json';request.write_bytes(p.encoded({p.FIELD:p.POLICY,'sources':{Path(p.__file__).name:hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()}}))
 monkeypatch.setattr(p,'hosted_root',lambda value:(root,tmp_path));calls=[]
 def original(*args,**kwargs):calls.append(args[0]);assert set(root.iterdir())=={root/'marker.json'};return 'NONCANONICAL_SEAL_DTO'
 assert p.bind_seal(original)(root,tmp_path/'out',b'DTO',request,'P06')=='NONCANONICAL_SEAL_DTO' and calls==[root]
 (root/'extra-file').write_bytes(b'EXPLICIT_NONCANONICAL_EXTRA_DTO')
 with pytest.raises(ValueError,match='EXACT_ORIGINAL_SYNTHETIC_PROBE'):p.bind_seal(original)(root,tmp_path/'out',b'DTO',request,'P06')


def test_failed_preparation_keeps_original_diagnostic_export_without_new_view(tmp_path,monkeypatch):
 root=tmp_path/'financial-resume-output-P06';root.mkdir();(root/'worker.log').write_bytes(b'EXPLICIT_NONCANONICAL_PREFLIGHT_REFUSAL_DTO')
 request=tmp_path/'request.json';request.write_bytes(p.encoded({p.FIELD:p.POLICY,'sources':{Path(p.__file__).name:hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest()}}))
 monkeypatch.setattr(p,'hosted_root',lambda value:(root,tmp_path));before=p.inventory(root)
 def original(actual,*args,**kwargs):assert actual==root;return 'UNCHANGED_NONCANONICAL_FAILED_EXPORT_DTO'
 assert p.bind_seal(original)(root,tmp_path/'out',b'DTO',request,'P06')=='UNCHANGED_NONCANONICAL_FAILED_EXPORT_DTO'
 assert p.inventory(root)==before and not list(tmp_path.glob('research-preflight-export-view-*'))
