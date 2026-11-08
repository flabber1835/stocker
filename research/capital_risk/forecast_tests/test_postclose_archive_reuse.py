"""Opaque noncanonical resource DTOs; never copy or execute a financial book."""
import ast,inspect,json,shutil,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):
   raise ImportError('ARCHIVE_REUSE_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_postclose_distribution_restart as p
import system_campaign_p07_abmd_legacy as legacy
import system_campaign_uncertainty_archive as archive
import full_system_benchmark as benchmark

@pytest.fixture
def resource(tmp_path,monkeypatch):
 # Hosted Linux saves LF; preserve the exact metadata contract on Windows too.
 def save_lf(path,value):
  with path.open('xb') as stream:stream.write(legacy.origin.encoded(value))
 monkeypatch.setattr(benchmark,'save',save_lf)
 source=tmp_path/'EXPLICIT_NONCANONICAL_SOURCE_DTO';out=tmp_path/'EXPLICIT_NONCANONICAL_OUTPUT_DTO'
 name='book/pre-event/EXPLICIT_NONCANONICAL_ARCHIVE_DTO.bin'
 raw=b'opaque noncanonical resource DTO'
 for root in (source,out):
  (root/name).parent.mkdir(parents=True);(root/name).write_bytes(raw)
 proof=dict(schema='research.uncertainty-readonly-archive-resolution/1',requested='book/pre-event/2019-10-22.json.gz',
  actual=name,file_sha256=p.sha(raw),outer_sha256='a'*64,source_cursor='2019-10-21',state_sha256='b'*64,
  input_sha256='c'*64,exact_first_certificate_identity=True,checkpoint_bytes_or_name_changed=False,
  new_checkpoint_or_alias_created=False,financial_sessions_advanced=0)
 pin={k:proof[k] for k in ('actual','outer_sha256','state_sha256','input_sha256')};pin['gzip_sha256']=proof['file_sha256']
 monkeypatch.setattr(p.resources,'plan',lambda spec:dict(historical_archive_resolutions=[pin]))
 namespace=dict(vars(archive),resolve=lambda where:(source/name,proof),
  same_existing_archive=lambda *a:False,shutil=SimpleNamespace(copyfile=legacy.safe_copy),save=legacy.save_archive_receipt)
 tree=legacy.archive_tree(Path(archive.__file__).read_bytes())
 exec(compile(ast.Module(body=[tree],type_ignores=[]),'<whole-original-preserver-noncanonical-resource-DTO>','exec'),namespace)
 original=namespace['preserve'];bound=p.preserved_archive(original,source,out,{})
 assert inspect.getclosurevars(bound).nonlocals['bound'].__code__ is original.__code__
 return source,out,name,raw,bound

def test_exact_duplicate_reuses_original_preserver_without_overwrite(resource,monkeypatch):
 source,out,name,raw,bound=resource
 before=(out/name).stat().st_mtime_ns
 monkeypatch.setattr(shutil,'copyfile',lambda *a,**kw:pytest.fail('existing bytes must not be copied again'))
 assert bound(source,out)==out/name and (out/name).read_bytes()==raw
 assert (out/name).stat().st_mtime_ns==before
 receipt=out/'uncertainty-event-archive-preservation.json';prior=receipt.read_bytes()
 assert bound(source,out)==out/name and receipt.read_bytes()==prior

def test_conflicting_existing_resource_refuses_and_is_not_overwritten(resource):
 source,out,name,raw,bound=resource;(out/name).write_bytes(b'conflicting DTO')
 with pytest.raises(ValueError,match='DISJOINT_NEW_EVIDENCE'):bound(source,out)
 assert (out/name).read_bytes()==b'conflicting DTO'
 assert not (out/'uncertainty-event-archive-preservation.json').exists()

def test_selected_directory_guard_and_meaningful_removal(resource,monkeypatch):
 source,out,name,raw,bound=resource;wrong=source/'wrong-noncanonical-directory'
 with pytest.raises(ValueError,match='SELECTED_RESTART_DIRECTORIES'):bound(wrong,out)
 original=p.need
 monkeypatch.setattr(p,'need',lambda ok,label:None if label=='POSTCLOSE_ARCHIVE_ONLY_SELECTED_RESTART_DIRECTORIES' else original(ok,label))
 assert bound(wrong,out)==out/name

def test_conflicting_original_receipt_still_refuses(resource):
 source,out,name,raw,bound=resource
 receipt=out/'uncertainty-event-archive-preservation.json';receipt.write_bytes(b'conflicting metadata DTO')
 with pytest.raises(ValueError,match='RECEIPT_EXACT_BYTES_NO_OVERWRITE'):bound(source,out)
 assert receipt.read_bytes()==b'conflicting metadata DTO'
