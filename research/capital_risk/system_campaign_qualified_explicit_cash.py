"""Original cash predicates with explicit schema2 source evidence; no book runtime."""
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib,json
from pathlib import Path
from types import FunctionType
from typing import Literal
from pydantic import Field
import system_campaign_qualified_cash_batch as original

HERE=Path(__file__).parent
ORIGINAL_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
PRIMARY='system-campaign-msp-common-cash-primary-fact.json'
PRIMARY_SHA='50dfe8b4abe77fdb2b9679698fa95d1dd8b9792b575052a38c54d82d25dfbf3b'
SCHEMA='research.qualified-explicit-own-cash-input/1'
need,sha,digest,encoded=original.need,original.sha,original.digest,original.encoded

class ExplicitCashInput(original.CashInputBatch):
    schema_id:Literal['research.qualified-explicit-own-cash-input/1']=Field(alias='schema')

def original_source():
    raw=Path(original.__file__).read_bytes();need(sha(raw)==ORIGINAL_SHA,'EXPLICIT_CASH_ORIGINAL_VALIDATOR_BYTES')
    return raw

def source_binding_tree():
    fn=next(n for n in ast.parse(original_source()).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding')
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future']
    need(len(imports)==1 and [n.name for n in imports[0].names]==['registered_scope'],'EXPLICIT_CASH_EXACT_SCOPE_IMPORT')
    fn.body.remove(imports[0])
    class Adapter(ast.NodeTransformer):
        schemas=rows=0
        def visit_Constant(self,node):
            if node.value=='research.own-parent-frozen-source-witnesses/1':
                self.schemas+=1;return ast.copy_location(ast.Constant('research.own-parent-frozen-source-witnesses/2'),node)
            return node
        def visit_Compare(self,node):
            if ast.unparse(node)=="payload.get('additional_rows', []) == review['additional_rows'] == []":
                self.rows+=1;return ast.copy_location(ast.parse('additional_rows_match(payload, review)',mode='eval').body,node)
            return self.generic_visit(node)
    adapter=Adapter();fn=adapter.visit(fn)
    need(adapter.schemas==adapter.rows==1,'EXPLICIT_CASH_EXACT_TWO_SOURCE_VERSION_SITES')
    return ast.fix_missing_locations(fn)

def explicit_scope(catalog,key):
    from system_campaign_explicit_source_queries import registry
    matches=[q for q in registry().queries if q.arm==catalog['arm'] and q.root_admission_sha256==catalog['parent_root_admission_sha256']]
    need(len(matches)==1,'EXPLICIT_CASH_ONE_EXACT_REGISTERED_OWN_ROOT_QUERY')
    scope=matches[0].scope.model_dump()
    need(digest(scope)==key and scope['parent_outer_sha256']==catalog['parent_outer_sha256']
         and scope['parent_cursor']==catalog['parent_cursor'],'EXPLICIT_CASH_EXACT_FULL_REGISTERED_SOURCE_SCOPE')
    return scope

def additional_rows_match(payload,review):
    rows=payload.get('additional_rows');declared=payload['scope']['additional_rows']
    if not isinstance(rows,list) or len(rows)!=1 or len(declared)!=1:return False
    if rows!=review['additional_rows']:return False
    value=rows[0];q=declared[0];row=value['source_row']
    witness={k:row[k] for k in ('session','security_id','ticker','issuer_id','listing_first_session','security_type_eligible')}
    witness['source_observation_sha256']=digest(row)
    return (value==dict(source_row=row,identity_witness=witness,parent_positions=q['parent_positions'])
        and row['session']==q['session'] and row['security_id']==q['security_id'] and row['ticker']==q['ticker']
        and digest(row)==q['source_observation_sha256'] and row['security_type_eligible']=='1')

def source_binding(catalog):
    fn=source_binding_tree();namespace=dict(vars(original),registered_scope=lambda key:explicit_scope(catalog,key),
        additional_rows_match=additional_rows_match)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<unchanged-cash-source-binding-exact-schema2-and-full-additional-row>','exec'),namespace)
    return namespace['source_binding'](catalog)

def primary_fact():
    raw=(HERE/PRIMARY).read_bytes();need(sha(raw)==PRIMARY_SHA,'EXPLICIT_CASH_EXACT_INDEPENDENT_PRIMARY_FACT')
    value=json.loads(raw)
    need(value['mandatory_eligible_common_cash'] is True and value['preopen_completion_confirmed'] is True
         and value['common_consideration_components']==[dict(kind='CASH',currency='USD',amount_per_share='35.50')]
         and value['stock_or_contingent_rights_in_common_consideration']==[]
         and value['actual_broker_settlement_asserted'] is value['financial_input_selected'] is False,
         'EXPLICIT_CASH_ONLY_QUALIFIED_COMMON_SHARE_CONSIDERATION')
    return value

def validate_primary(catalog):
    fact=primary_fact();need(len(catalog['terms'])==1,'EXPLICIT_CASH_ONE_QUALIFIED_PRIMARY_TERM')
    term,=catalog['terms'];extraction=term['primary_extraction']
    need((term['ticker'],term['security_id'],term['primary_source'],term['actual_completion_date'])==
         (fact['ticker'],fact['security_id'],fact['source'],fact['completion_date'])
         and Decimal(str(term['added']['cash_per_share']))==Decimal(fact['cash_per_eligible_common_share'])
         and term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION'
         and term['preopen_completion_confirmed'] is True
         and extraction['qualified_cash_only_primary_fact_sha256']==PRIMARY_SHA
         and extraction['no_stock_or_contingent_rights_in_common_consideration'] is True,
         'EXPLICIT_CASH_NEW_PRIMARY_FACT_NOT_UNHELD_RECORD_UPGRADE')
    return True

def validate(catalog):
    original_source()
    namespace=dict(original.validate.__globals__,__file__=__file__,CashInputBatch=ExplicitCashInput,source_binding=source_binding)
    fn=FunctionType(original.validate.__code__,namespace,original.validate.__name__,original.validate.__defaults__)
    need(fn.__code__ is original.validate.__code__,'EXPLICIT_CASH_WHOLE_ORIGINAL_VALIDATE_CODE')
    result=fn(catalog);validate_primary(catalog);return result

class QualifiedExplicitCash:
    def __init__(self,catalog):
        if isinstance(catalog,Path):
            raw=catalog.read_bytes();catalog=json.loads(raw)
            need(raw==encoded(catalog),'EXPLICIT_CASH_EXACT_CANONICAL_INPUT_CATALOG_BYTES')
        self._dict_init(catalog)
        self.catalog_sha=sha(encoded(catalog))
        self.compiler_sha=sha(Path(__file__).read_bytes())

need(original.QualifiedCashBatch.__init__.__closure__ is None,'EXPLICIT_CASH_CONSTRUCTOR_NO_HIDDEN_CLOSURE')
QualifiedExplicitCash._dict_init=FunctionType(original.QualifiedCashBatch.__init__.__code__,
    dict(original.QualifiedCashBatch.__init__.__globals__,__file__=__file__,validate=validate),
    original.QualifiedCashBatch.__init__.__name__,original.QualifiedCashBatch.__init__.__defaults__)
