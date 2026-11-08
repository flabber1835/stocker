"""Whole original absent-quote hydration with exact PFNX calendar/annual counts."""
import ast
from pathlib import Path
from types import SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_abmd_bounded_hydration as original
import system_campaign_p03_PFNX_source as source
ORIGINAL_SHA='1091ea25621f9b9ebb5b7f113ecb6adbd8e6e8e876b29a7492e93776fe7d64f7'
DATES={'2022-12-20':source.PRIOR,'2022-12-21':source.NATIVE,'2022-12-22':source.DAY,'observations-2022.csv.gz':'observations-2020.csv.gz'}

def tree(raw,name):
 need(sha(raw)==ORIGINAL_SHA and name in ('witness','hydrate'),'PFNX_HYDRATE_ENTIRE_ORIGINAL_SOURCE_AND_DECLARED_FUNCTION')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name];hits={k:0 for k in DATES};counts={2080223:0,245:0}
 for node in ast.walk(fn):
  if isinstance(node,ast.Constant):
   if isinstance(node.value,str) and node.value in DATES:
    old=node.value;node.value=DATES[old];hits[old]+=1
   elif type(node.value)is int and node.value in counts:
    old=node.value;node.value={2080223:1541141,245:189}[old];counts[old]+=1
 expected=({'2022-12-20':2,'2022-12-21':4,'2022-12-22':0,'observations-2022.csv.gz':0},{2080223:1,245:1}) if name=='witness' else ({'2022-12-20':1,'2022-12-21':2,'2022-12-22':2,'observations-2022.csv.gz':2},{2080223:0,245:0})
 need((hits,counts)==expected,'PFNX_HYDRATE_ONLY_EXACT_ORIGINAL_CALENDAR_AND_ACTUAL_ANNUAL_COUNT_SITES')
 return ast.fix_missing_locations(fn)

def functions():
 scope=dict(vars(original),validate=source.validate,SID=source.SID,encoded=source.encoded)
 exec(compile(ast.Module(body=[tree(Path(original.__file__).read_bytes(),name) for name in ('witness','hydrate')],type_ignores=[]),
  '<whole-original-absent-quote-hydration-PFNX-calendar-and-annual-counts>','exec'),scope)
 return SimpleNamespace(witness=scope['witness'],hydrate=scope['hydrate'])

def witness(*args,**kwargs):return functions().witness(*args,**kwargs)

def hydrate(value,out):
 from full_system_core import hosted
 hosted();source.catalog();source.verify_semantics(value)
 return functions().hydrate(value,out)
