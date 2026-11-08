"""Whole stock factory/build with an exact full-history ABMD collision visitor."""
import ast
from pathlib import Path
from types import FunctionType,SimpleNamespace
import system_campaign_action_preflight as collision
import system_campaign_p06_WWE_stock_source as source
import system_campaign_p06_WWE12_models as models
from system_campaign_bounded_sensor_input import SCHEMA,need,sha
COLLISION_SHA='0145e6ce84048faf80f49ae20095f29eaf8dc479be4dfd932ec648326d5cf68c'
STOCK_SOURCE_SHA='b28be292d5e3112db6ac54231d545969a2d2776a055b3b4859f83b93bf594aa6'

def collision_tree(raw):
    need(sha(raw)==COLLISION_SHA,'P06_WWE12_ENTIRE_ORIGINAL_COLLISION_READER_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='analyze_new_catalog']
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.target)=='descriptor']
    block,=[n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="document['schema'] == 'research.leadership-uncertainty-input/1'"]
    added=ast.parse("if document['schema']==TYPED_SCHEMA:\n validate_typed_input(root,cp,descriptor)\n continue\n").body[0]
    loop.body.insert(loop.body.index(block)+1,added)
    return ast.fix_missing_locations(fn)

def validate_typed_input(root,current,descriptor):
    result=models.full(root,current)
    need(result['bounded_descriptor']==descriptor==current['repairs'][9],'P06_WWE12_EXACT_ABMD_TYPED10_IN_COMPLETE_CURRENT_HISTORY')
    return True

def bound_collision(*,validator=validate_typed_input):
    scope=dict(vars(collision),TYPED_SCHEMA=SCHEMA,validate_typed_input=validator)
    exec(compile(ast.Module(body=[collision_tree(Path(collision.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-stock-collision-reader-one-exact-ABMD-history-branch>','exec'),scope)
    return scope['analyze_new_catalog']

def factory(old,provider_root,request):
    need(sha(Path(source.__file__).read_bytes())==STOCK_SOURCE_SHA,'P06_WWE12_ENTIRE_FROZEN_PROVIDER_SOURCE_FACTORY')
    facade=SimpleNamespace(**dict(vars(source.original),analyze_new_catalog=bound_collision()))
    fn=source.factory
    need(fn.__closure__ is None,'P06_WWE12_WHOLE_SOURCE_FACTORY_NO_CLOSURE')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,original=facade),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    return bound(old,provider_root,request)

def bound_build(old,provider_root,request):
    fn=source.bound_build
    need(fn.__closure__ is None,'P06_WWE12_WHOLE_BUILD_BINDER_NO_CLOSURE')
    bound=FunctionType(fn.__code__,dict(fn.__globals__,factory=factory),fn.__name__,fn.__defaults__)
    bound.__kwdefaults__=fn.__kwdefaults__
    return bound(old,provider_root,request)

def source_names():return (Path(__file__).name,*source.source_names(),'system_campaign_action_preflight.py',*models.source_names())
