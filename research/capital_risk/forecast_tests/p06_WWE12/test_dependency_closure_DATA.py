"""Actual FIN355 missing dependency regression; opaque bytes, no book staging."""
import json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[2];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('DEPENDENCY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_dependencies as d
import system_campaign_p06_WWE12_resources as resources
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_bounded_sensor_event_review import permissions
import system_campaign_p06_abmd_lifecycle_data as lifecycle
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
@pytest.fixture(scope='module')
def actual():
 F=R/'financial339-P06-source-snapshot/capture-P06-13525611349-001'
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()));pins=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 def read(n):
  raw=(root/n).read_bytes();assert d.pin(raw)==pins[n];return raw
 cp=strict_json(read('book/checkpoint.json.gz'));rows=[json.loads(v) for v in read('uncertainty-certificate.jsonl').splitlines()[:173]]
 _,rs=permissions(root,rows,lifecycle.catalog(),through=cp['source_cursor'],input_descriptors=cp['repairs'][:10])
 return read,rs

def test_complete_closure_includes_actual_old_event_omitted_by_static88(actual):
 read,rs=actual;closed=resources.closed_inventory(read,rs)['dependency_closure']
 assert len(closed['requirements'])==89
 assert {v['path'] for v in closed['requirements']}==set(resources.plan()['resources'])|{rs[0]['actual']}
 assert rs[0]['actual'].startswith('book/pre-event/2022-12-22-')
 assert closed['financial_checkpoint_replaced'] is closed['financial_authority'] is False

def test_actual_FIN355_output_refused_even_though_all88_static_assets_match(actual):
 read,rs=actual;F=R/'financial355-P06-source-snapshot/capture-P06-13569129128-001'
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()))
 for n,pin in resources.plan()['resources'].items():assert d.pin((root/n).read_bytes())==pin
 manifest=d.build(resources.plan()['resources'],rs,read)
 with pytest.raises(FileNotFoundError):d.verify(manifest,resources.plan()['resources'],rs,read,lambda n:(root/n).read_bytes())

def test_complete_copy_and_handoff_with_explicit_noncanonical_resource_callbacks(actual):
 read,rs=actual;manifest=d.build({},rs,read);present=set()
 # This DTO retains names only; it creates no file, book, alias or checkpoint.
 def write(n,b):assert d.pin(b)['sha256']==rs[0]['gzip_sha256'];present.add(n)
 def output(n):
  if n not in present:raise FileNotFoundError('EXPLICIT_NONCANONICAL_RESOURCE_DTO_MISSING:'+n)
  return read(n)
 d.copy_checked(manifest,read,write)
 assert d.verify(manifest,{},rs,read,output) is True
 present.remove(rs[0]['actual'])
 with pytest.raises(FileNotFoundError):d.verify(manifest,{},rs,read,output)

def test_omitted_reference_guard_and_meaningful_removal(actual,monkeypatch):
 read,rs=actual;manifest=d.build({},rs,read);manifest['requirements']=[]
 with pytest.raises(ValueError,match='OMITS'):d.verify(manifest,{},rs,read,read)
 original=d.build;monkeypatch.setattr(d,'build',lambda *a,**k:manifest)
 assert d.verify(manifest,{},rs,read,read) is True
 monkeypatch.setattr(d,'build',original)

def test_changed_original_event_bytes_refused(actual):
 read,rs=actual
 with pytest.raises(ValueError,match='ARCHIVE_BYTES_CHANGED'):d.build({},rs,lambda n:read(n)+b'EXPLICIT_NONCANONICAL_CORRUPTION')

@pytest.mark.parametrize('path',['../escape','/absolute','book/checkpoint.json.gz','book/pre-event/unbound.json.gz','C:/escape'])
def test_unsafe_or_current_checkpoint_alias_refused(path):
 with pytest.raises(ValueError):d.Requirement(path=path,bytes=1,sha256='e'*64,role='pre_event_archive' if path.startswith('book/pre-event/') else 'historical_asset')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
