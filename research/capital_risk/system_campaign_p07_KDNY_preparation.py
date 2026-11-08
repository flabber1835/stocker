"""Whole absent-bar qualifier, exact KDNY clock, complete retained input stack."""
import ast
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_abmd_bounded_preparation as original

ORIGINAL_SHA='6a998f614f814b9dd4e4d20ff9c7f7a76389fdb4513689bdb7858c3c2cf57443'
NATIVE='2023-08-10'
DAY='2023-08-11'


def packet_tree(raw):
 need(sha(raw)==ORIGINAL_SHA,'KDNY_PREPARATION_WHOLE_ORIGINAL_ABSENT_BAR_QUALIFIER')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='qualify_packets']
 dates={'2022-12-21':NATIVE,'2022-12-22':DAY};hits={old:0 for old in dates}
 for n in ast.walk(fn):
  if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value in dates:
   old=n.value;n.value=dates[old];hits[old]+=1
 need(hits=={'2022-12-21':7,'2022-12-22':3},'KDNY_PREPARATION_EXACT_ORIGINAL_CALENDAR_SITES')
 limits,=[n for n in ast.walk(fn) if isinstance(n,ast.List) and ast.unparse(n)=='[380.0, 415.0]']
 limits.elts=[ast.Constant(40.),ast.Constant(44.)]
 apply,=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n)=='backtest.apply_repair(original, loaded)']
 apply.func=ast.Name(id='apply_cumulative',ctx=ast.Load())
 return ast.fix_missing_locations(fn)


def packet_qualifier(objects,apply_repair):
 """One complete original function; the callback preserves input order."""
 def apply_cumulative(packet,final):
  for obj in objects:packet=apply_repair(packet,obj)
  return apply_repair(packet,final)
 scope=dict(vars(original),apply_cumulative=apply_cumulative)
 exec(compile(ast.Module(body=[packet_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
  '<whole-absent-bar-packet-qualifier-KDNY-dates-range-all-retained-inputs>','exec'),scope)
 return scope['qualify_packets']


def qualify_packets(cp,path,loaded,native,value,objects):
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_p07_KDNY_source import catalog,parent_contract
 from system_campaign_financial_partial import root_spec
 spec=root_spec('P07',catalog()['parent_root_admission_sha256']);parent_contract(cp,spec)
 need(value==catalog() and len(objects)==len(cp['repairs'])==26
  and [obj.sha256 for obj in objects]==[d['sha256'] for d in cp['repairs']],
  'KDNY_PREPARATION_ALL26_ACTUAL_INSTALLED_RETAINED_INPUTS_IN_ORIGINAL_ORDER')
 return packet_qualifier(objects,backtest.apply_repair)(cp,path,loaded,native,value)
