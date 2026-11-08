"""Whole original absent-bar qualifier; complete21 retained objects precede PFNX."""
import ast
from pathlib import Path
from full_system_benchmark import need
import system_campaign_p07_KDNY_preparation as previous
import system_campaign_p03_PFNX_source as source
original=previous.original

def packet_tree(raw):
 fn=previous.packet_tree(raw);dates={previous.NATIVE:source.NATIVE,previous.DAY:source.DAY};hits={day:0 for day in dates}
 for node in ast.walk(fn):
  if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value in dates:
   old=node.value;node.value=dates[old];hits[old]+=1
 need(hits=={previous.NATIVE:7,previous.DAY:3},'PFNX_PREPARATION_EXACT_WHOLE_ORIGINAL_CALENDAR_SITES')
 limits,=[n for n in ast.walk(fn) if isinstance(n,ast.List) and ast.unparse(n)=='[40.0, 44.0]']
 limits.elts=[ast.Constant(12.),ast.Constant(14.)]
 return ast.fix_missing_locations(fn)

def packet_qualifier(objects,apply_repair):
 def cumulative(packet,final):
  for obj in objects:packet=apply_repair(packet,obj)
  return apply_repair(packet,final)
 scope=dict(vars(original),apply_cumulative=cumulative)
 exec(compile(ast.Module(body=[packet_tree(Path(original.__file__).read_bytes())],type_ignores=[]),'<whole-original-absent-bar-PFNX-full21-and12-to14>','exec'),scope)
 return scope['qualify_packets']

def qualify_packets(parent,path,loaded,native,value,objects):
 from full_system_core import hosted
 hosted()
 from research.pooled_vacancy_funding import backtest
 from system_campaign_financial_partial import root_spec
 source.parent_contract(parent,root_spec('P03',source.ROOT))
 need(value==source.catalog() and len(objects)==len(parent['repairs'])==21
  and [obj.sha256 for obj in objects]==[descriptor['sha256'] for descriptor in parent['repairs']],
  'PFNX_PREPARATION_ALL21_ACTUAL_INSTALLED_TYPED_OBJECTS_IN_ORIGINAL_ORDER')
 return packet_qualifier(objects,backtest.apply_repair)(parent,path,loaded,native,value)
