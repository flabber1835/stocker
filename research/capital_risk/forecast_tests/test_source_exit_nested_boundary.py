"""The exact stopped request227 path failure, using existing genuine DATA."""
import gzip,json,sys
from pathlib import Path
import pytest
C=Path(__file__).resolve().parents[1];sys.path.insert(0,str(C))
class Fence:
 def find_spec(self,n,path=None,target=None):
  if n.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('NESTED_BOUNDARY_DATA_ONLY:'+n)
sys.meta_path.insert(0,Fence())
import system_campaign_source_exit_runtime as p
from system_campaign_financial_partial import root_spec

@pytest.fixture(scope='module')
def actual():
 F=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8/P06-request227-source-snapshot/authenticated-artifact-13593557334')
 if not F.exists():pytest.skip('authenticated stopped request227 DATA required')
 root=Path('\\\\?\\'+str((F/'verified-output').resolve()));mf=json.loads((F/'authenticated-manifest.json').read_bytes())['members']
 spec=root_spec('P06');names=p.profiles.paths(spec)
 def member(name):
  raw=(root/name).read_bytes();assert dict(bytes=len(raw),sha256=p.sha(raw))==mf[name];return raw
 parent=json.loads(gzip.decompress(member(names['PARENT'])));neutral=json.loads(gzip.decompress(member(names['NEUTRAL'])))
 return root,spec,names,parent,neutral,member

def test_original_basename_lookup_reproduces_real_failure_and_bound_relative_path_passes(actual):
 root,spec,names,parent,neutral,member=actual;before=p.models.digest((parent,neutral))
 with pytest.raises(FileNotFoundError):
  p.legacy.boundary(root,names['DIRECTORY'],parent,Path(names['OVERLAY']).name,'2025-04-01')
 checked=p.adoption_boundary(spec,p.legacy.boundary)(root,names['DIRECTORY'],parent,Path(names['OVERLAY']).name,'2025-04-01')
 assert checked==neutral and checked['completed']==parent['completed']==1821 and len(checked['repairs'])==14
 assert checked['run']['state']==parent['run']['state'] and p.models.digest((parent,neutral))==before
 assert checked['sha256']=='e3561f6d7fd9851b966ea080088ebff52f30aa332a1b90e306f93c8f5858566c'

@pytest.mark.parametrize('root',[p.profiles.LEGACY_ROOT,'27c4e51a5fc479b418668a7950a4146129380eb73dc029840b0a62a9a0163da0'])
def test_both_profile_paths_delegate_whole_original_reader_with_exact_relative_filename(root):
 spec=root_spec('P06',root);names=p.profiles.paths(spec);seen=[]
 def original(*args):seen.append(args);return 'EXPLICIT_NONCANONICAL_BOUNDARY_READER_DTO'
 result=p.adoption_boundary(spec,original)(Path('EXPLICIT_NONCANONICAL_ROOT_DTO'),names['DIRECTORY'],
  'EXPLICIT_NONCANONICAL_PARENT_TOKEN_DTO',Path(names['OVERLAY']).name,'EXPLICIT_NONCANONICAL_DAY_DTO')
 assert result=='EXPLICIT_NONCANONICAL_BOUNDARY_READER_DTO'
 assert seen[0][3]==names['OVERLAY']

@pytest.mark.parametrize('change',['directory','overlay'])
def test_other_paths_cannot_be_redirected_to_selected_input(actual,change):
 root,spec,names,parent,_,_=actual;directory=names['DIRECTORY'];overlay=Path(names['OVERLAY']).name
 if change=='directory':directory='EXPLICIT_NONCANONICAL_WRONG_DIRECTORY_DTO'
 else:overlay='EXPLICIT_NONCANONICAL_WRONG_OVERLAY_DTO.json'
 with pytest.raises(ValueError,match='EXACT_SELECTED_BOUNDARY_FILENAME'):
  p.adoption_boundary(spec,p.legacy.boundary)(root,directory,parent,overlay,'2025-04-01')

@pytest.mark.parametrize('name',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_five_financial_import_fences(name):
 assert not any(n==name or n.startswith(name+'.') for n in sys.modules)
 with pytest.raises(ImportError):Fence().find_spec(name)
