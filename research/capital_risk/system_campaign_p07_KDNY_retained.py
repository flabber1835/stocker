"""Exact full26 metadata,949 seed and ABMD->KDNY->BWA handler order."""
import ast,json
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p07_KDNY_resources as resources
import system_campaign_bounded_sensor_runtime_v2 as bodies
import system_campaign_postclose_distribution_restart as previous
import system_campaign_p07_abmd_lifecycle as original_lifecycle
history,source=resources.history,resources.source


def selected(spec):return isinstance(spec,dict) and spec.get('arm')=='P07' and spec.get('root_admission_sha256')==source.ROOT


def phase(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);need(selected(spec),'KDNY_RETAINED_EXACT_ADMITTED_ROOT')
 proof=spec['root_admission']['branch_uncertainty_proof']
 need(proof['rows']==20 and proof['retained_rows']==929,'KDNY_RETAINED_ACTUAL_ADMISSION_COUNTS')
 return dict(rows=949,new_rows=20,retained_rows=929)


def physical(parent,spec):
 from full_system_core import hosted
 hosted();source.parent_contract(parent,spec);hashes=resources.fact()['controller_sources']
 need(len(hashes)==6 and all(parent['base']['sources'].get(n)==h
  and sha((Path('/variant')/n).read_bytes())==h for n,h in hashes.items()),
  'KDNY_RETAINED_ALL_SIX_ORIGINAL_PHYSICAL_CONTROLLER_SOURCES')
 return hashes


def seed_reader(*,validate_input=history.full,retained_contract=physical):
 from system_campaign_bounded_sensor_seed_binding import bind_seed
 whole=bind_seed(validate_input=validate_input,retained_contract=retained_contract,retained_phase=phase)
 def read(old,parent,spec):
  source.parent_contract(parent,spec);value=whole(Path(old),parent,spec)
  resources.seed_contract(parent,value[1],value[2]);resources.raw_contract(lambda n:(Path(old)/n).read_bytes(),value[1]);return value
 return read


def declaration_tree(raw):
 need(sha(raw)==previous.saved.retained.LIFECYCLE_SHA,'KDNY_RETAINED_WHOLE_ORIGINAL_ABMD_DECLARATION_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='valid_retained']
 checks=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="len(spec['repairs']) == 24"]
 need(len(checks)==1,'KDNY_RETAINED_ONE_ORIGINAL_DESCRIPTOR_COUNT_SITE');checks[0].comparators[0].value=26
 return ast.fix_missing_locations(fn)


def lifecycle():
 life=history.previous.lifecycle();scope=life.phase.__globals__
 exec(compile(ast.Module(body=[declaration_tree(Path(original_lifecycle.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-retained-ABMD-declaration-current-full26>','exec'),scope)
 life.valid_retained=scope['valid_retained'];return life


@contextmanager
def codecs(root,current,spec,out):
 from full_system_core import hosted
 hosted();root,out=Path(root),Path(out);need(selected(spec),'KDNY_RETAINED_ONLY_EXACT_CURRENT_PROFILE')
 history.full(root,current)
 parent=current if current['sha256']==spec['outer_sha256'] else history.archived_parent(lambda n:(root/n).read_bytes())
 source.parent_contract(parent,spec)
 life=lifecycle();api=life.runtime_api(root,parent,spec,life.catalog())
 native,market=source.hydrate(source.catalog(),out/history.SOURCE,old=root)
 from system_campaign_second_bounded_codec import SuccessorCodec
 from system_campaign_abmd_bounded_catalog import evidence
 with api.original_chain(root,parent,spec) as inherited:
  old=life.catalog()
  with SuccessorCodec(source.catalog()['event'],source.evidence(source.catalog()),native,
    previous_event=old['event'],previous_evidence=evidence(old)) as codec:
   codec.previous_owner()
   with previous.projection(root):yield codec,market,inherited


def installed():
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_second_bounded_codec import SuccessorCodec
 layer=getattr(backtest.load_repair,'__self__',None)
 need(isinstance(layer,previous.inputs.typed.InputCodec),'KDNY_RETAINED_ACTUAL_OUTER_BWA_PROJECTION_REQUIRED')
 loader=previous.without_distribution(backtest.load_repair);codec=getattr(loader,'__self__',None)
 need(type(codec)is SuccessorCodec and loader==codec.load and codec.event==source.catalog()['event'],
  'KDNY_RETAINED_ACTUAL_INSTALLED_KDNY_CODEC_BELOW_BWA')
 codec.previous_owner();return codec


def active_branch(backtest,old,current):
 from full_system_core import hosted
 hosted()
 from system_campaign_zogenix_input import InputCodec
 from system_campaign_financial_projection import OwnProjection
 codec=installed();abmd=codec.previous_owner();loader=abmd.original_load;z=getattr(loader,'__self__',None)
 need(isinstance(z,InputCodec) and loader==z.load,'KDNY_RETAINED_ORIGINAL_ZOGENIX_HANDLER_BELOW_ABMD')
 own=getattr(z.original_load,'__self__',None)
 need(isinstance(own,OwnProjection) and own.active and z.original_load==own.load,
  'KDNY_RETAINED_ACTUAL_ACTIVE_ORIGINAL_APHA_PROJECTION')
 return bodies.legacy.active_codec(SimpleNamespace(load_repair=z.original_load),old,current)


def zogenix_arguments(codec,root):
 from full_system_core import hosted
 hosted()
 from dataclasses import asdict
 from system_campaign_zogenix_input import InputCodec
 from system_campaign_zogenix_facts import PRIVATE,CONTRACT
 need(codec is installed(),'KDNY_RETAINED_CONSTRUCTOR_ONLY_ACTUAL_INSTALLED_SUCCESSOR')
 abmd=codec.previous_owner();loader=abmd.original_load;z=getattr(loader,'__self__',None)
 need(isinstance(z,InputCodec) and loader==z.load and z.objects,'KDNY_RETAINED_ACTUAL_LOADED_ZOGENIX_CONSTRUCTOR_CODEC')
 contract=json.loads((Path(__file__).parent/CONTRACT).read_bytes())
 need(asdict(z.native)==contract['native'] and z.native_sha256==contract['native_term_sha256'],
  'KDNY_RETAINED_ORIGINAL_ZOGENIX_CONSTRUCTOR_NATIVE')
 raw=(Path(root)/PRIVATE).read_bytes();expected=resources.fact()['resources'][PRIVATE]
 need(resources.pin(raw)=={k:expected[k] for k in ('bytes','sha256')},'KDNY_RETAINED_AUTHENTIC_COMPLETE_ZOGENIX_PRIVATE_SOURCE')
 return dict(zogenix_codec=z,zogenix_native=z.native,zogenix_source=json.loads(raw))


def growth_scope(current,spec):
 from full_system_core import hosted
 hosted()
 import system_campaign_financial_additional_sensor_runtime as original
 need(selected(spec),'KDNY_RETAINED_ORIGINAL_P07_MIXED_GROWTH_ONLY')
 need(current['base']==spec['base'] and current['repairs'][:26]==spec['repairs']
  and len(current['repairs']) in (26,27),'KDNY_RETAINED_GENUINE_CURRENT_INPUT_AXIS_FOR_MIXED_GROWTH')
 return original.growth_scope(current,spec)
