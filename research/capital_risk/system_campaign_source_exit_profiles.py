"""One exact data-selected restart path for successive source-exit inputs."""
import json
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
HERE=Path(__file__).parent
CATALOG='system-campaign-source-exit-profiles.json'
LEGACY_ROOT='ed91d2845587672a335b6af5a921c96668432a6129d337db062c3eedff88c845'


def records():
 value=json.loads((HERE/CATALOG).read_bytes())
 need(value['schema']=='research.source-exit-profiles/1' and value['financial_authority'] is False,'SOURCE_PROFILES_DATA_ONLY')
 return value['roots']


def candidate(spec):return isinstance(spec,dict) and spec.get('root_admission_sha256') in records() and spec.get('arm')=='P06'


def profile(spec):
 from system_campaign_financial_partial import validate_root_spec
 validate_root_spec(spec);value=records()[spec['root_admission_sha256']]
 need(value['parent_outer_sha256']==spec['outer_sha256'] and value['parent_inputs']==len(spec['repairs'])
  and value['seed_rows']==spec['root_admission']['branch_uncertainty_proof']['rows']+spec['root_admission']['branch_uncertainty_proof'].get('retained_rows',0),
  'SOURCE_PROFILES_EXACT_ADMITTED_PARENT_AND_ALL_RETAINED_PROOFS')
 return value


def source(spec):
 value=profile(spec)
 if value['source_version']==1:
  import system_campaign_source_exit_input_v1 as module
  selected=module.selected;catalog=module.catalog;validator=module.original.research_source_exit_term
 else:
  import system_campaign_source_exit_input as module
  need(value['source_version']==2,'SOURCE_PROFILES_SUPPORTED_SOURCE_VERSION')
  selected=partial(module.selected,catalog_name=value['catalog']);catalog=partial(module.catalog,value['catalog']);validator=module.boundary_validator()
 need(sha(Path(module.__file__).read_bytes())==value['compiler_sha256'] and sha((HERE/value['catalog']).read_bytes())==value['catalog_sha256'],
  'SOURCE_PROFILES_EXACT_SOURCE_CATALOG_AND_COMPILER_BYTES')
 return SimpleNamespace(CATALOG=value['catalog'],catalog=catalog,selected=selected,validate_term=validator,version=value['source_version'],module=module)


def paths(spec):
 value=profile(spec)
 if spec['root_admission_sha256']==LEGACY_ROOT:
  return dict(PARENT='ordinary-successor-origin/parent-checkpoint.json.gz',DIRECTORY='ordinary-successor-adoption',
   NEUTRAL='ordinary-successor-adoption/checkpoint.json.gz',PROOF='ordinary-successor-adoption/proof.json',PROVENANCE='ordinary-successor-origin',
   OLD_PROOF='ordinary-successor-origin/original-full442-uncertainty-certificate.jsonl',OVERLAY='source-exit-successor-overlay.json',
   HYDRATED='hydrated-source-exit-successor-catalog.json',QUALIFICATION='source-exit-successor-input-qualification.json',
   SOURCE_SCOPES='source-exit-successor-scopes.json',OBSERVATION='source-exit-successor-observation',
   BOUNDARY='source-exit-successor-genuine-neutral-boundary.json',CANARY='source-exit-successor-dependency-canary.json',
   PREPARATION='source-exit-successor-zero-financial-preparation.json',RECEIPT='source-exit-successor-adopted-input-receipt.json')
 prefix='source-successors/'+spec['root_admission_sha256'];origin=prefix+'/origin';adoption=prefix+'/adoption'
 return dict(PARENT=origin+'/parent-checkpoint.json.gz',DIRECTORY=adoption,NEUTRAL=adoption+'/checkpoint.json.gz',PROOF=adoption+'/proof.json',
  PROVENANCE=origin,OLD_PROOF=origin+'/original-retained-proof.jsonl',OVERLAY=prefix+'/input-overlay.json',HYDRATED=prefix+'/hydrated-catalog.json',
  QUALIFICATION=prefix+'/input-qualification.json',SOURCE_SCOPES=prefix+'/source-scopes.json',OBSERVATION=prefix+'/observation',
  BOUNDARY=prefix+'/boundary-review.json',CANARY=prefix+'/dependency-canary.json',PREPARATION=prefix+'/zero-financial-preparation.json',RECEIPT=prefix+'/adopted-input-receipt.json')


def previous(root,current,spec):
 if profile(spec)['parent_inputs']==12:
  import system_campaign_p06_WWE12_models as module
  return module.full(root,current)
 from system_campaign_source_exit_history import full
 return full(root,current)
