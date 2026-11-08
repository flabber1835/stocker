"""Exact972 baseline and original codec/mixed-growth contexts for full27/28."""
import ast
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_KDNY_retained as original
import system_campaign_p07_vivo_retained as prior_growth
import system_campaign_p07_ordinary28_history as history
resources,data=history.resources,history.data
installed=original.installed
active_branch=original.active_branch
zogenix_arguments=original.zogenix_arguments

def selected(spec):return isinstance(spec,dict) and spec.get('arm')=='P07' and spec.get('root_admission_sha256')==data.ROOT

def phase(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);need(selected(spec),'ORDINARY28_RETAINED_EXACT_CURRENT_ADMITTED_ROOT')
 p=spec['root_admission']['branch_uncertainty_proof']
 need(p['passed']is True and (p['retained_rows'],p['rows'])==(949,23),'ORDINARY28_RETAINED_ACTUAL972_ADMISSION_COUNTS')
 return dict(rows=972,new_rows=23,retained_rows=949)

def physical(parent,spec):
 from full_system_core import hosted
 hosted();data.parent_contract(parent,spec);hashes=resources.fact()['controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'][n]==h and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
  'ORDINARY28_RETAINED_ALL_SIX_ORIGINAL_PHYSICAL_CONTROLLER_SOURCES')
 return hashes

def seed_reader(*,validate_input=history.full,retained_contract=physical):
 from system_campaign_bounded_sensor_seed_binding import bind_seed
 whole=bind_seed(validate_input=validate_input,retained_contract=retained_contract,retained_phase=phase)
 def read(root,parent,spec):
  data.parent_contract(parent,spec);value=whole(Path(root),parent,spec)
  resources.seed_contract(parent,value[1],value[2]);resources.raw_contract(lambda n:(Path(root)/n).read_bytes(),value[1]);return value
 return read

def codec_function():
 fn=original.codecs.__wrapped__
 need(fn.__closure__ is None,'ORDINARY28_RETAINED_COMPLETE_CLOSED_ORIGINAL_CODEC_CONTEXT')
 h=SimpleNamespace(**dict(vars(original.history),full=history.full))
 bound=FunctionType(fn.__code__,dict(fn.__globals__,history=h),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'ORDINARY28_RETAINED_WHOLE_ORIGINAL_CODEC_CONTEXT_CODE')
 return bound

@contextmanager
def codecs(root,current,spec,out):
 from full_system_core import hosted
 hosted();root=Path(root);need(selected(spec),'ORDINARY28_RETAINED_ONLY_CURRENT_PROFILE')
 history.full(root,current)
 parent=current if current['sha256']==spec['outer_sha256'] else history.archived_parent(lambda n:(root/n).read_bytes())
 data.parent_contract(parent,spec)
 archived_spec=original.history.spec()
 need(archived_spec['root_admission_sha256']==original.source.ROOT and len(archived_spec['repairs'])==26,
  'ORDINARY28_RETAINED_GENUINE_ARCHIVED26_METADATA_FOR_ORIGINAL_LOADERS_ONLY')
 with contextmanager(codec_function())(root,current,archived_spec,out) as chain:yield chain

def proof_scope(root,current,spec):
 from full_system_core import hosted
 hosted()
 from system_campaign_point_growth import point_growth_scope
 need(selected(spec) and current['base']==spec['base'] and len(current['repairs'])in (27,28)
  and current['repairs'][:27]==spec['repairs'] and current['base']['sources']['sentinel/controller/median5.py']==prior_growth.WITNESS_SHA,
  'ORDINARY28_RETAINED_FULL_CURRENT_AXIS_AND_PHYSICAL_POINT_WITNESS')
 result=history.full(root,current)
 need(result['passed']is True and result['full_inputs']==len(current['repairs']),'ORDINARY28_RETAINED_COMPLETE_HISTORY_BEFORE_POINT_SCOPE')
 return point_growth_scope(Path('/variant/sentinel/controller/median5.py').read_bytes(),prior_growth.WITNESS_SHA)

def growth_tree():return prior_growth.growth_tree(Path(prior_growth.additional_runtime.__file__).read_bytes())

def growth_function(root):
 scope=dict(vars(prior_growth.additional_runtime),proof_scope=lambda cp,spec:proof_scope(root,cp,spec))
 exec(compile(ast.Module(body=[growth_tree()],type_ignores=[]),'<whole-original-mixed-growth-current27or28-proof-scope>','exec'),scope)
 return scope['growth_scope']

def growth_scope(root,current,spec):
 from full_system_core import hosted
 hosted();return growth_function(root)(current,spec)

def source_names():return (Path(__file__).name,Path(original.__file__).name,Path(prior_growth.__file__).name,*history.source_names())
