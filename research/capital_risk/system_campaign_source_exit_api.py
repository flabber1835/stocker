"""Complete original Future lifecycle with an explicit full-history callback."""
import ast,json
from copy import deepcopy
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
import system_campaign_financial_future as original
import system_campaign_p06_BBIG_api as previous
import system_campaign_source_exit_input as source
from system_campaign_bounded_sensor_input import SCHEMA
FUTURE_SHA='54ebe4e7da0ecd090f5d9dc87a0dd80bb3571b34d2433127a12b35b1a102775c'
FUNCTIONS=('hydrate','document','qualify','prepare','review_input','source_scopes','hydration_name')
OVERLAY='source-exit-successor-overlay.json'
HYDRATED='hydrated-source-exit-successor-catalog.json'
QUALIFICATION='source-exit-successor-input-qualification.json'
SOURCE_SCOPES='source-exit-successor-scopes.json'

def typed_descriptor(root,current,visitor):
 need(callable(visitor),'SOURCE_EXIT_API_EXPLICIT_COMPLETE_HISTORY_VISITOR')
 visitor(root,current);matches=[]
 for entry in current['repairs']:
  name=entry['filename']
  need(Path(name).name==name and '/' not in name and '\\' not in name and name==entry['sha256']+'.json','SOURCE_EXIT_API_SAFE_EXACT_INPUT_DESCRIPTOR')
  raw=(Path(root)/'book/repairs'/name).read_bytes()
  need(sha(raw)==entry['sha256'],'SOURCE_EXIT_API_EXACT_DESCRIPTOR_BYTES')
  if json.loads(raw)['schema']==SCHEMA:matches.append(entry)
 need(len(matches)==1,'SOURCE_EXIT_API_ONE_TYPED_ABMD_DESCRIPTOR_IN_ENTIRE_HISTORY')
 return matches[0]

def api(parent,spec,*,visitor):
 from system_campaign_financial_partial import validate_root_spec
 from system_campaign_full_history_successor import current_commitments
 validate_root_spec(spec);value=source.catalog();term=value['term']
 current_commitments(parent,spec,lambda base,repairs:digest(dict(base=base,repairs=repairs)))
 need(parent['sha256']==spec['outer_sha256']==term['parent_outer_sha256'] and parent['repairs']==spec['repairs']
  and parent['base']==spec['base'] and parent['source_cursor']==spec['selected_session']==term['parent_cursor']
  and parent['run']['input_sha256']==spec['input_sha256'] and callable(visitor),'SOURCE_EXIT_API_ENTIRE_ORIGINAL_ADMITTED_PARENT_AND_EXPLICIT_HISTORY')
 raw=Path(original.__file__).read_bytes();need(sha(raw)==FUTURE_SHA,'SOURCE_EXIT_API_WHOLE_ORIGINAL_FUTURE_SOURCE')
 def validate_input(root,current):return typed_descriptor(root,current,visitor)['sha256']
 def validate_typed_input(root,current,entry):
  need(typed_descriptor(root,current,visitor)==entry,'SOURCE_EXIT_API_EXACT_TYPED_DESCRIPTOR_AFTER_COMPLETE_HISTORY')
 def save(path,value):
  path=Path(path)
  if path.name=='future-input-qualification.json':
   need(value['passed'] is True and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0,'SOURCE_EXIT_API_ORIGINAL_ZERO_FINANCIAL_PACKET_QUALIFICATION')
   path=path.with_name(QUALIFICATION)
  return original.save(path,value)
 namespace=dict(vars(original),selected=source.selected,OVERLAY=OVERLAY,HYDRATED=HYDRATED,SOURCE_SCOPES=SOURCE_SCOPES,
  validate_input=validate_input,validate_typed_input=validate_typed_input,TYPED_SCHEMA=SCHEMA,save=save)
 exec(compile(ast.Module(body=[previous.remaining_tree(raw)],type_ignores=[]),'<whole-original-remaining-terms-qualified-typed-dispatch>','exec'),namespace)
 for name in FUNCTIONS:
  fn=getattr(original,name);need(fn.__closure__ is None,'SOURCE_EXIT_API_WHOLE_ORIGINAL_FUNCTION_WITHOUT_CLOSURE')
  bound=FunctionType(fn.__code__,namespace,fn.__name__,fn.__defaults__);bound.__kwdefaults__=deepcopy(fn.__kwdefaults__)
  need(bound.__code__ is fn.__code__,'SOURCE_EXIT_API_IDENTICAL_COMPLETE_ORIGINAL_FUNCTION_CODE')
  namespace[name]=bound
 return SimpleNamespace(**{n:namespace[n] for n in (*FUNCTIONS,'remaining_ordinary_terms')},selected=source.selected,OVERLAY=OVERLAY,QUALIFICATION=QUALIFICATION,SOURCE_SCOPES=SOURCE_SCOPES)
