"""Whole original packet preflight, without a provider-alias staging requirement."""
import ast,json
from pathlib import Path
from types import FunctionType
import system_campaign_p03_cash14_stage as prior
import system_campaign_p03_HABT19_runtime as runtime
import system_campaign_p03_HABT19_data as data
import system_campaign_p03_HABT19_api as batch
HERE=Path(__file__).parent
def preparation_tree():
 raw=Path(prior.__file__).read_bytes();data.need(data.sha(raw)=='3017c1356d7a9bbe28c06eb56edd267424aebbfe7e78c7d2bdab95ed62484023','HABT_WHOLE_ORIGINAL_PREFLIGHT_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='prepare_after_preflight']
 class Finite(ast.NodeTransformer):
  def visit_Constant(self,n):
   if type(n.value) is int and n.value in (19,28,14):return ast.copy_location(ast.Constant({19:33,28:2,14:1}[n.value]),n)
   if n.value=='2020-02-19':return ast.copy_location(ast.Constant('2020-03-18'),n)
   if n.value=='research.P03-cash14-original28-packet-preparation/1':return ast.copy_location(ast.Constant('research.P03-HABT-original2-packet-preparation/1'),n)
   if n.value=='genuine_neutral18_created':return ast.copy_location(ast.Constant('genuine_neutral19_created'),n)
   return n
 return ast.fix_missing_locations(Finite().visit(fn))
def prepare_after_preflight(old,out,spec):
 scope=dict(vars(prior),runtime=runtime,data=data,batch=batch)
 exec(compile(ast.Module(body=[preparation_tree()],type_ignores=[]),'<whole-original-preflight-two-HABT-packet-checks>','exec'),scope)
 return scope['prepare_after_preflight'](old,out,spec)
def bind_preflight(original):
 def preflight(old,out,spec):
  request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes());enabled=runtime.request_selected(spec,request)
  result=original(old,out,spec)
  if enabled:prepare_after_preflight(old,out,spec)
  return result
 return preflight
