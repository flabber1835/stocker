"""Whole original stock compiler with one explicit immutable provider read root."""
import ast,json
from pathlib import Path
from types import FunctionType,MethodType
import system_campaign_stock_calendar as original
import system_campaign_wwe_facts as facts
import system_campaign_p06_WWE_source_asset as source_asset
import system_campaign_p06_WWE173_preconditions as preconditions
from full_system_benchmark import need
from system_campaign_facts import sha
def hydrate_tree(raw):
    need(sha(raw)==source_asset.protocol()['exact_original_WWE_sources']['system_campaign_stock_calendar.py'],
        'P06_WWE_STOCK_SOURCE_ENTIRE_ORIGINAL_COMPILER_BYTES')
    cls,=[n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='StockCalendar']
    fn,=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='hydrate']
    site,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='provider']
    need(ast.unparse(site.value)=="(old / 'provider-source/SHARADAR_ACTIONS.zip').read_bytes()",
        'P06_WWE_STOCK_SOURCE_ONE_EXACT_ORIGINAL_PROVIDER_RESOURCE_READ')
    site.value=ast.parse('provider_source_bytes(old)',mode='eval').body
    return ast.fix_missing_locations(fn)
def factory(old,provider_root,request):
    """Construct original object; only hydrate's source read uses separate bytes."""
    old,provider_root=Path(old),Path(provider_root)
    def provider_source_bytes(actual_old):
        need(Path(actual_old)==old,'P06_WWE_STOCK_SOURCE_SAME_GENUINE_OLD_ROOT_FOR_INPUT_COLLISION_REVIEW')
        source_asset.request_binding(request)
        raw=(provider_root/'provider-source/SHARADAR_ACTIONS.zip').read_bytes()
        need(len(raw)==source_asset.ASSET_BYTES and sha(raw)==source_asset.ASSET_SHA,
            'P06_WWE_STOCK_SOURCE_ORIGINAL_PROVIDER_BYTES_AT_HYDRATION_USE')
        return raw
    namespace=dict(vars(original),provider_source_bytes=provider_source_bytes)
    exec(compile(ast.Module(body=[hydrate_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-StockCalendar-hydrate-one-explicit-provider-source-root>','exec'),namespace)
    hydrate=namespace['hydrate']
    def construct(catalog):
        obj=original.StockCalendar(catalog);obj.hydrate=MethodType(hydrate,obj)
        need(obj.__class__ is original.StockCalendar and obj.patch.__func__ is original.StockCalendar.patch
            and obj.qualify.__func__ is original.StockCalendar.qualify and obj.hydrate.__func__.__closure__ is None,
            'P06_WWE_STOCK_SOURCE_ORIGINAL_CONSTRUCTOR_PATCH_PACKET_QUALIFIER_AND_WHOLE_HYDRATOR')
        return obj
    return construct
def bound_build(old,provider_root,request):
    fn=original.build;need(fn.__closure__ is None,'P06_WWE_STOCK_SOURCE_COMPLETE_ORIGINAL_BUILD_NO_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,StockCalendar=factory(old,provider_root,request)),fn.__name__,fn.__defaults__)
    result.__kwdefaults__=fn.__kwdefaults__;need(result.__code__ is fn.__code__,'P06_WWE_STOCK_SOURCE_IDENTICAL_COMPLETE_ORIGINAL_BUILD_CODE')
    return result
def build(parent,old,out,provider_root,request,*,spec):
    preconditions.require_admitted(parent,spec,request)
    catalog=Path(facts.__file__).parent/facts.CATALOG;facts.validate(json.loads(catalog.read_bytes()))
    return bound_build(old,provider_root,request)(parent,old,out,catalog)
def source_names():return (Path(__file__).name,*source_asset.source_names(),*preconditions.source_names())
