"""Current request metadata with unchanged single-save financial validation."""
import ast
from pathlib import Path

import p01_iac_reference_review as published
from p01_iac_unit_contract import need,sha

PUBLISHED_SHA='9a047c86526c3b147d41490733c4d962c44250a4ebc15b5cd81e9075f8411cdd'
REQUEST='p01_iac_namespace_request.json'


def _raw():
    raw=Path(published.__file__).read_bytes()
    need(sha(raw)==PUBLISHED_SHA,'NAMESPACE_REVIEW_EXACT_PUBLISHED509_METADATA_ADAPTER')
    return raw


def _namespace():
    _raw()
    return dict(vars(published),**{k:v for k,v in globals().items() if not k.startswith('__')},__file__=__file__)


def _node(name):
    need(name in ('review','review_loaded'),'NAMESPACE_REVIEW_ONLY_TWO_UNCHANGED_FINANCIAL_VALIDATORS')
    _raw();node=published._node(name);changes=[]
    class Scope(ast.NodeTransformer):
        def visit_ImportFrom(self,item):
            if item.module=='p01_iac_reference_review':
                need(name=='review_loaded' and [(n.name,n.asname) for n in item.names]==[('save_review','save')],
                     'NAMESPACE_REVIEW_ONE_EXACT_SINGLE_SAVE_METADATA_IMPORT')
                item.module='p01_iac_namespace_review';changes.append('single_save')
            if item.module=='p01_iac_reference_export':
                need(name=='review_loaded' and [(n.name,n.asname) for n in item.names]==[('qualification',None)],
                     'NAMESPACE_REVIEW_ONE_EXACT_NEW_QUALIFICATION_GATE_IMPORT')
                item.module='p01_iac_namespace_export';changes.append('q_gate')
            return item
    node=Scope().visit(node)
    need(changes==(['single_save','q_gate'] if name=='review_loaded' else []),
         'NAMESPACE_REVIEW_ONLY_TWO_METADATA_IMPORT_TARGETS')
    return node


def _body(name):
    node=_node(name);values=published._body(name).__globals__.copy();values.update(_namespace())
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-namespace-financial-review:'+name+'>','exec'),values)
    return values[name]


def _metadata(name):
    need(name in ('validate_reuse','save_review'),'NAMESPACE_REVIEW_ONLY_CURRENT_REQUEST_AND_SAVE_METADATA')
    node,=[n for n in ast.parse(_raw()).body if isinstance(n,ast.FunctionDef) and n.name==name];changes=[]
    class Scope(ast.NodeTransformer):
        def visit_Constant(self,item):
            if item.value=='p01_iac_reference_request.json':
                need(name=='validate_reuse','NAMESPACE_REVIEW_REQUEST_LITERAL_ONLY_IN_PROVENANCE')
                item.value=REQUEST;changes.append('request_name')
            return item
    node=Scope().visit(node)
    need(changes==(['request_name'] if name=='validate_reuse' else []),
         'NAMESPACE_REVIEW_ONLY_ONE_NEW_REQUEST_FILENAME')
    values=_namespace()
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
        '<source-bound-namespace-review-metadata:'+name+'>','exec'),values)
    return values[name]


def validate_reuse(*a,**k):return _metadata('validate_reuse')(*a,**k)
def save_review(*a,**k):return _metadata('save_review')(*a,**k)
def review(*a,**k):return _body('review')(*a,**k)
def review_loaded(*a,**k):return _body('review_loaded')(*a,**k)
main=review
