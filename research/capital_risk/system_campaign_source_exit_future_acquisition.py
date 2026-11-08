"""Complete original strict-future source compiler, one exact native action pair."""
import ast,json
from functools import partial
from pathlib import Path
from types import FunctionType
import system_campaign_source_exit_input_v1 as previous
from system_campaign_facts import sha
from full_system_benchmark import need
HERE=Path(__file__).parent
ORIGINAL_SHA='d8b80226163b399251953d09c6877e1ef29b17bdf06a73530705ac72e60c9594'
CATALOG='P06-SGN-source-exit-input-catalog.json'
original=previous.original
encoded=previous.encoded

def validator_tree(raw):
 need(sha(raw)==ORIGINAL_SHA,'SOURCE_FUTURE_ACQUISITION_WHOLE_ORIGINAL_V1_COMPILER')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='validate']
 sites=[n for n in ast.walk(fn) if isinstance(n,ast.Set)
  and all(isinstance(v,ast.Constant) for v in n.elts)
  and {v.value for v in n.elts}=={'delisted','regulatorydelisting'}]
 need(len(sites)==1,'SOURCE_FUTURE_ACQUISITION_ONE_ORIGINAL_NATIVE_PAIR_SITE')
 sites[0].elts=[ast.Constant('acquisitionby'),ast.Constant('delisted')]
 return ast.fix_missing_locations(fn)

def validate(value,*,root_lookup):
 namespace=dict(vars(previous))
 exec(compile(ast.Module(body=[validator_tree(Path(previous.__file__).read_bytes())],type_ignores=[]),
  '<whole-original-source-compiler-exact-future-acquisition-pair>','exec'),namespace)
 return namespace['validate'](value,root_lookup=root_lookup)

def catalog(name=CATALOG):
 from system_campaign_financial_partial import root_spec
 need(type(name)is str and Path(name).name==name and '/' not in name and '\\' not in name,
  'SOURCE_FUTURE_ACQUISITION_SAFE_EXPLICIT_CATALOG')
 return validate(json.loads((HERE/name).read_bytes()),root_lookup=root_spec)

def selected(arm,*,cursor,catalog_name=CATALOG):
 fn=previous.selected
 scope=dict(fn.__globals__,__file__=__file__,CATALOG=catalog_name,catalog=partial(catalog,catalog_name))
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 need(bound.__code__ is fn.__code__,'SOURCE_FUTURE_ACQUISITION_ORIGINAL_SELECTOR_CODE')
 return bound(arm,cursor=cursor)
