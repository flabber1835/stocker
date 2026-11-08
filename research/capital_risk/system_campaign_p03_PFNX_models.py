"""Whole original loader/seed functions, followed by one original PFNX codec."""
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p03_PTLA_models as previous
import system_campaign_p03_PTLA_runtime as old_runtime
import system_campaign_p03_PFNX_history as history
resources,source=history.resources,history.source

def selected(spec):return isinstance(spec,dict) and spec.get('arm')=='P03' and spec.get('root_admission_sha256')==source.ROOT

def phase(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);need(selected(spec),'PFNX_MODELS_ONLY_CURRENT_ADMITTED671_ROOT')
 proof=spec['root_admission']['branch_uncertainty_proof']
 need(proof['passed'] is True and (proof['retained_rows'],proof['rows'])==(174,43),'PFNX_MODELS_EXACT217_ADMITTED_SEED_COUNTS')
 return dict(rows=217,new_rows=43,retained_rows=174)

def physical(parent,spec,root):
 from full_system_core import hosted
 hosted();resources.parent_contract(parent,spec);history.full_parent(root,parent);hashes=resources.fact()['controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'][n]==h and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
  'PFNX_MODELS_ALL_SIX_ORIGINAL_PHYSICAL_CONTROLLER_FILES')
 return hashes

def seed_function():
 fn=old_runtime.seed_reader
 result=FunctionType(fn.__code__,dict(fn.__globals__,history=history,resources=resources,phase=phase,physical=physical),fn.__name__,fn.__defaults__)
 result.__kwdefaults__=fn.__kwdefaults__;return result

def seed_reader():return seed_function()()

def codec_function():
 fn=previous.codecs.__wrapped__;need(fn.__closure__ is None,'PFNX_MODELS_WHOLE_CLOSED_ORIGINAL_PTLA_CONTEXT')
 old_history=SimpleNamespace(**dict(vars(previous.history),full=history.full))
 bound=FunctionType(fn.__code__,dict(fn.__globals__,history=old_history),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__;return bound

@contextmanager
def codecs(root,current,spec,out,*,base_context):
 from full_system_core import hosted
 hosted();root,out=Path(root),Path(out);need(selected(spec),'PFNX_MODELS_EXACT_SELECTED_PROFILE')
 history.full(root,current)
 parent=current if current['sha256']==spec['outer_sha256'] else history.archived_parent(lambda n:(root/n).read_bytes())
 source.parent_contract(parent,spec);metadata=previous.history.spec()
 need(metadata['measured_closes']==628 and len(metadata['repairs'])==20,'PFNX_MODELS_GENUINE_OLD628_METADATA_FOR_LOADERS_ONLY')
 @contextmanager
 def base(where,cp,ignored):
  need(Path(where)==root and cp==current and ignored==metadata,'PFNX_MODELS_BASE_CONTEXT_ACTUAL_CURRENT_AND_LOADER_METADATA_ONLY')
  with base_context(where,cp,spec):yield
 with contextmanager(codec_function())(root,current,metadata,out,base_context=base) as stml:
  from research.pooled_vacancy_funding import backtest
  from system_campaign_second_bounded_codec import SuccessorCodec
  from system_campaign_p03_PFNX_hydration import hydrate
  value=source.catalog();path=out/history.SOURCE;path.parent.mkdir(parents=True,exist_ok=True);native,_=hydrate(value,path)
  with SuccessorCodec(value['event'],source.evidence(value),native,previous_event=previous.stml.catalog()['event'],previous_evidence=previous.stml.evidence(previous.stml.catalog())) as codec:
   need(codec.previous_owner() is stml,'PFNX_MODELS_ORIGINAL_STML_PREVIOUS_OWNER')
   objects=[backtest.load_repair(root/'book/repairs'/d['filename'],resume_session=d['resume_session'],predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256']) for d in current['repairs']]
   need([obj.sha256 for obj in objects]==[d['sha256'] for d in current['repairs']],'PFNX_MODELS_ALL_CURRENT_TYPED_OBJECTS_IN_ORIGINAL_ORDER')
   yield codec

def installed():
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_second_bounded_codec import SuccessorCodec
 codec=getattr(backtest.load_repair,'__self__',None)
 need(type(codec) is SuccessorCodec and codec.event==source.catalog()['event'] and backtest.load_repair==codec.load,
  'PFNX_MODELS_ACTUAL_INSTALLED_PFNX_OWNER')
 old=codec.previous_owner();first=old.previous_owner()
 need(old.event==previous.stml.catalog()['event'] and first.event==previous.dova.catalog()['event'],
  'PFNX_MODELS_COMPLETE_THREE_DECLARED_ORIGINAL_OWNERS')
 return codec

def active_branch(backtest,root,current):
 from full_system_core import hosted
 hosted();codec=installed()
 need(getattr(backtest.load_repair,'__self__',None) is codec,'PFNX_MODELS_ACTUAL_ACTIVE_LOADER_ONLY')
 first=codec.previous_owner().previous_owner()
 return old_runtime.legacy.active_codec(SimpleNamespace(load_repair=first.original_load),Path(root),current)

def source_names():return (Path(__file__).name,Path(previous.__file__).name,Path(old_runtime.__file__).name,*history.source_names())
