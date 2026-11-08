"""Whole original B19/ZOG/ABMD visitors with one genuine ordinary25 boundary."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import system_campaign_p07_abmd_models as original
import system_campaign_p07_abmd_origin as origin_original
import system_campaign_p07_vivo_boundary as boundary
import system_campaign_p07_vivo_data as data

MODELS_SHA='1364500287d8962e836368db3269d6c1dddea0512421087df1ab796a49d091bf'
ORIGIN_SHA='126e183249185e5c85aa88899eaae4e0cbaef1a0d6131856acf94228f7fdc486'

def replace_count(tree,old,new,expected,label):
    count=0
    class Bind(ast.NodeTransformer):
        def visit(self,node):
            nonlocal count
            if ast.unparse(node)==old:
                count+=1;return ast.copy_location(ast.parse(new,mode='eval').body,node)
            return super().visit(node)
    result=Bind().visit(tree);data.need(count==expected,label);return result

def model_tree(raw):
    data.need(data.sha(raw)==MODELS_SHA,'VIVO_COMPLETE_ORIGINAL_FULL24_MODEL_SOURCE')
    tree=ast.parse(raw)
    for fn in tree.body:
        if isinstance(fn,ast.FunctionDef) and fn.name in ('typed_descriptor','receipt_reader'):
            replace_count(fn,'(23, 24)','(23, 24, 25)',1,'VIVO_ONE_FULL25_COUNT_SITE:'+fn.name)
        if isinstance(fn,ast.FunctionDef) and fn.name=='typed_descriptor':
            site,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='d']
            fn.body[site:site]=ast.parse("if len(cp['repairs'])==25:\n validate_vivo_tail(root,cp,input_hash=input_hash)").body
    return ast.fix_missing_locations(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]))

def origin_tree(raw):
    data.need(data.sha(raw)==ORIGIN_SHA,'VIVO_COMPLETE_ORIGINAL_ABMD_ORIGIN_SOURCE')
    tree=ast.parse(raw)
    for fn in tree.body:
        if isinstance(fn,ast.FunctionDef) and fn.name=='validate':
            replace_count(fn,"current['repairs'] == adopted['repairs']", "current['repairs'][:24] == adopted['repairs']",1,'VIVO_ONE_ABMD_ORIGIN_FULL_PREFIX_SITE')
            replace_count(fn,"len(current['repairs']) == 24", "len(current['repairs']) in (24, 25)",1,'VIVO_ONE_ABMD_ORIGIN_FULL_COUNT_SITE')
            replace_count(fn,"current['run']['input_sha256'] == adopted['run']['input_sha256'] == input_hash(current['base'], current['repairs'])",
                "adopted['run']['input_sha256'] == input_hash(adopted['base'], adopted['repairs']) and current['run']['input_sha256'] == input_hash(current['base'], current['repairs'])",1,'VIVO_OLD24_AND_CURRENT25_INDEPENDENT_FULL_HASHES')
            site,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Return)]
            fn.body[site:site]=ast.parse("if len(current['repairs'])==25:\n validate_vivo_members(current,member,input_hash=input_hash)").body
    return ast.fix_missing_locations(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef)],type_ignores=[]))

def models():
    namespace=dict(vars(original),validate_vivo_tail=boundary.validate)
    exec(compile(model_tree(Path(original.__file__).read_bytes()),'<whole-original-full24-model-functions-genuine-ordinary25>','exec'),namespace)
    return SimpleNamespace(**namespace)

def origin():
    namespace=dict(vars(origin_original),models=models(),validate_vivo_members=boundary.validate_members)
    exec(compile(origin_tree(Path(origin_original.__file__).read_bytes()),'<whole-original-ABMD-origin-independent-current25-hash>','exec'),namespace)
    return SimpleNamespace(**namespace)

def source_names():return (Path(__file__).name,Path(boundary.__file__).name)
