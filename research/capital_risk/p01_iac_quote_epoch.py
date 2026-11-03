"""Authenticate each context; retain one exact immutable canonical quote binding."""
import ast
import json
from pathlib import Path

from p01_iac_unit_contract import need,sha,digest

QUOTE_SOURCE_SHA='9a346d56d6c5487c31964f0eb66150fdfda5b5ff1ab4bc4fd407557d5943c99e'
EPOCH_SOURCE_SHA='6378c454efb9721f53b42ab9049b8f93ed1e4fbd160a9871d600564b99312074'
MARKET_SOURCE_SHA='732a1bd6f14cef54a215e48d594e5287b7a034a8c71254d5897530da12d17dca'
UNBOUND='REFUSED_CELG_COMPONENT_ACTUAL_MARKET_INPUT_REQUIRED_NO_SYNTHETIC_FALLBACK'


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def bind_or_require_exact(module,value):
    """Use only the frozen public API; never reset or replace its registry."""
    need(sha(Path(module.__file__).read_bytes())==MARKET_SOURCE_SHA,
         'QUOTE_LIFECYCLE_ACTUAL516_MARKET_MODULE_SOURCE')
    need(type(value) is dict,'QUOTE_LIFECYCLE_AUTHENTICATED_MAPPING')
    try:
        existing=module.quote()
    except ValueError as error:
        if str(error)!=UNBOUND:raise
        module.bind_market_quote(value,expected_sha256=digest(value))
        existing=module.quote()
    need(type(existing) is dict and encoded(existing)==encoded(value) and digest(existing)==digest(value),
         'QUOTE_LIFECYCLE_ENTIRE_TYPED_REGISTRATION_EQUALS_FRESH_AUTHENTICATED_INPUT')


def _quote_body():
    import p01_epoch_resume as original
    raw=Path(original.__file__).read_bytes();need(sha(raw)==QUOTE_SOURCE_SHA,'QUOTE_LIFECYCLE_FROZEN_AUTHENTICATION_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='_quote']
    changes=[]
    class Lifecycle(ast.NodeTransformer):
        def visit_Expr(self,item):
            if isinstance(item.value,ast.Call) and isinstance(item.value.func,ast.Attribute) \
                    and ast.unparse(item.value.func)=='merger_rights.bind_market_quote':
                need(ast.unparse(item.value)=='merger_rights.bind_market_quote(value, expected_sha256=digest(value))',
                     'QUOTE_LIFECYCLE_ONE_EXACT_BIND_CALLSITE')
                changes.append(item)
                return ast.copy_location(ast.parse('bind_or_require_exact(merger_rights,value)').body[0],item)
            return self.generic_visit(item)
    node=Lifecycle().visit(node);need(len(changes)==1,'QUOTE_LIFECYCLE_ONLY_SINGLE_BIND_SITE_CHANGED')
    namespace=dict(vars(original),bind_or_require_exact=bind_or_require_exact)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<source-bound-every-context-quote-authentication>','exec'),namespace)
    return namespace['_quote']


def authenticated_quote(quote_root,descriptor_path):
    # The source-pinned loader performs all descriptor/capsule checks BEFORE
    # reaching bind_or_require_exact on every call, including cache reuse.
    return _quote_body()(quote_root,descriptor_path)


def historical_epoch(old,out,spec,*,quote_root=Path('/celg-input'),
                     quote_descriptor_path=Path('/celg-input-descriptor.json'),checkpoint_path=None):
    """Same own628 context, with its actual imported quote alias replaced."""
    import p01_iac_unit_epoch as original
    raw=Path(original.__file__).read_bytes();need(sha(raw)==EPOCH_SOURCE_SHA,'QUOTE_LIFECYCLE_FROZEN_OWN628_EPOCH_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='historical_epoch']
    namespace=dict(vars(original),_quote=authenticated_quote)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                 '<source-bound-own628-quote-lifecycle-context>','exec'),namespace)
    return namespace['historical_epoch'](old,out,spec,quote_root=quote_root,
        quote_descriptor_path=quote_descriptor_path,checkpoint_path=checkpoint_path)
