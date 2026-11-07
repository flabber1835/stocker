"""Whole original P02 WWE qualifier/reviewer, finite external own27 role binding."""
import ast,json
from pathlib import Path
import system_campaign_wwe_gate as original_gate
import system_campaign_wwe_review as original_review
import system_campaign_wwe_facts as facts
import system_campaign_p06_WWE173_preconditions as preconditions
import system_campaign_p06_WWE_source_asset as source_asset
from full_system_benchmark import need
from system_campaign_facts import sha
HERE=Path(__file__).parent
REQUEST='system-campaign-p02-wwe-request.json'
def original_sources():
    value=source_asset.protocol()['exact_original_WWE_sources']
    for module in (original_gate,original_review,facts,facts.stock):
        name=Path(module.__file__).name;need(sha(Path(module.__file__).read_bytes())==value[name],'P06_WWE27_ENTIRE_ORIGINAL_QUALIFIED_SOURCE:'+name)
    return value
def role_tree(raw,name):
    pins=original_sources();module='system_campaign_wwe_gate.py' if name=='qualify' else 'system_campaign_wwe_review.py'
    need(name in ('qualify','actual_conversion') and sha(raw)==pins[module],'P06_WWE27_ONLY_COMPLETE_ORIGINAL_QUALIFIER_OR_REVIEW')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Constant) and type(n.value)is int and n.value==16]
    need(len(sites)==(5 if name=='qualify' else 1),'P06_WWE27_EXACT_ORIGINAL_FIXED16_ROLE_SITES')
    for node in sites:node.value=27
    return ast.fix_missing_locations(fn)
def bound(name):
    module=original_gate if name=='qualify' else original_review;scope=dict(vars(module))
    exec(compile(ast.Module(body=[role_tree(Path(module.__file__).read_bytes(),name)],type_ignores=[]),
        '<whole-original-WWE-external-P06-own27-role>','exec'),scope)
    return scope[name]
def qualify(out,parent,material,loaded,old_objects,request,*,spec):
    preconditions.require_admitted(parent,spec,request)
    return bound('qualify')(out,parent,material,loaded,old_objects,request)
def actual_conversion(root,current,parent,output,*,spec,request):
    preconditions.require_admitted(parent,spec,request)
    return bound('actual_conversion')(root,current,parent,output)
def source_names():return (Path(__file__).name,'system_campaign_wwe_gate.py','system_campaign_wwe_review.py',
    'system_campaign_wwe_facts.py','system_campaign_stock_calendar.py',*source_asset.source_names(),*preconditions.source_names())
