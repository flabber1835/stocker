"""Source-bound consumed-native cash input; canonical arithmetic unchanged."""
import ast,json
from decimal import Decimal
from pathlib import Path
from types import FunctionType
from typing import Literal
from pydantic import Field
import system_campaign_qualified_cash_batch as original

HERE=Path(__file__).parent
ORIGINAL_SHA='96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
PRIMARY='SRRA-primary-cash-preparation.json'
PRIMARY_SHA='5dc40ed7d97e3ea88bd966cb49b80a91f9220aed9371431b66db5126e90ce218'
SCHEMA='research.qualified-pending-own-cash-input/1'
need,sha,digest,encoded=original.need,original.sha,original.digest,original.encoded
ROOT='fbc6821ce4ae8beb5e24805d8f2b10a2b5f0941b6f9c15e21c1ae7b3ce121add'
OUTER='070a7fe026589bc0692f86ceff56d579ef9e0ec79672013f2260039a56c22099'
SID='324793693976033682'
NATIVE='26d8fb32c525f9eaa9e9a2b57203b7afef13f60ca3cc99c864b140d25f66bcc6'

class PendingCashInput(original.CashInputBatch):
    schema_id:Literal['research.qualified-pending-own-cash-input/1']=Field(alias='schema')

def original_source():
    raw=Path(original.__file__).read_bytes();need(sha(raw)==ORIGINAL_SHA,'PENDING_CASH_EXACT_ORIGINAL_VALIDATOR_BYTES');return raw

def registered_scope(catalog,key):
    from system_campaign_pending_native_source_queries_v2 import registry
    q,=registry().queries;scope=q.scope.model_dump()
    need(catalog['arm']==q.arm=='P05' and catalog['parent_root_admission_sha256']==q.root_admission_sha256==ROOT
         and catalog['parent_outer_sha256']==scope['parent_outer_sha256']==OUTER
         and catalog['parent_cursor']==scope['parent_cursor']=='2022-06-30'
         and digest(scope)==key,'PENDING_CASH_EXACT_SEPARATE_REGISTERED_SOURCE_SCOPE')
    return scope

def source_binding_tree():
    fn=next(n for n in ast.parse(original_source()).body if isinstance(n,ast.FunctionDef) and n.name=='source_binding')
    imports=[n for n in fn.body if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_financial_future']
    need(len(imports)==1 and [x.name for x in imports[0].names]==['registered_scope'],'PENDING_CASH_EXACT_SCOPE_IMPORT')
    fn.body.remove(imports[0])
    class Schema(ast.NodeTransformer):
        count=0
        def visit_Constant(self,node):
            if node.value=='research.own-parent-frozen-source-witnesses/1':
                self.count+=1;return ast.copy_location(ast.Constant('research.own-parent-frozen-source-witnesses/2'),node)
            return node
    adapter=Schema();fn=adapter.visit(fn);need(adapter.count==1,'PENDING_CASH_ONE_SOURCE_SCHEMA_SITE')
    return ast.fix_missing_locations(fn)

def source_binding(catalog):
    namespace=dict(vars(original),registered_scope=lambda key:registered_scope(catalog,key))
    exec(compile(ast.Module(body=[source_binding_tree()],type_ignores=[]),'<original-source-binding-schema2-pending-registry>','exec'),namespace)
    return namespace['source_binding'](catalog)

def pending_clock(catalog,term,actual,scope,checked):
    if catalog['parent_cursor']<term['native_session']:return True
    context=dict(pending_sessions=0,stale_at_event=0,native_term_sha256=NATIVE,unresolved=False)
    roles=[dict(slot_id=8,ticker='SRRA',quantity=35,entry_date='2022-06-27')]
    values=[actual.get('pending_context'),scope.get('pending_at_parent'),checked.get('pending_context')]
    return (catalog['arm']==term['arm']=='P05' and catalog['parent_root_admission_sha256']==ROOT
        and catalog['parent_outer_sha256']==OUTER and catalog['parent_cursor']==term['native_session']=='2022-06-30'
        and term['ticker']=='SRRA' and term['security_id']==SID and term['native_term_sha256']==NATIVE
        and term['added']['session']=='2022-07-01' and term['added']['cash_per_share']==55.
        and term['parent_positions']==roles and all(v==context and type(v['pending_sessions']) is type(v['stale_at_event']) is int
            and v['unresolved'] is False for v in values))

def validate_tree():
    fn=next(n for n in ast.parse(original_source()).body if isinstance(n,ast.FunctionDef) and n.name=='validate')
    class Clock(ast.NodeTransformer):
        count=0
        def visit_Compare(self,node):
            if ast.unparse(node)=="catalog['parent_cursor'] < term['native_session']":
                self.count+=1;return ast.copy_location(ast.parse('pending_clock(catalog,term,actual,scope,checked)',mode='eval').body,node)
            return self.generic_visit(node)
    adapter=Clock();fn=adapter.visit(fn);need(adapter.count==1,'PENDING_CASH_ONE_EXACT_NATIVE_CLOCK_SITE')
    return ast.fix_missing_locations(fn)

def primary_fact():
    raw=(HERE/PRIMARY).read_bytes();need(sha(raw)==PRIMARY_SHA,'PENDING_CASH_EXACT_SEPARATE_PRIMARY_BYTES')
    fact=json.loads(raw)
    need(fact['ticker']=='SRRA' and fact['security_id']==SID and fact['currency']=='USD'
        and fact['eligible_common_consideration_components']==[dict(kind='CASH',currency='USD',amount_per_share='55.00')]
        and fact['common_stock_or_contingent_right_components']==[] and fact['preopen_completion_confirmed'] is True
        and fact['actual_broker_settlement_asserted'] is fact['financial_input_selected'] is fact['financial_authority'] is False
        and fact['past_native_suppression_proposed'] is fact['existing_checkpoint_rewrite_proposed'] is False,
        'PENDING_CASH_ONLY_SEPARATE_COMMON_SHARE_PRIMARY_FACT')
    return fact

def validate_primary(catalog):
    fact=primary_fact();need(len(catalog['terms'])==1,'PENDING_CASH_ONE_PRIMARY_TERM');term,=catalog['terms'];x=term['primary_extraction']
    need(term['primary_source']==fact['primary_source'] and term['actual_completion_date']==fact['completion_date']=='2022-07-01'
         and Decimal(str(term['added']['cash_per_share']))==Decimal(fact['cash_per_eligible_common_share'])==Decimal('55.00')
         and term['last_trading_session']==fact['last_trading_session']=='2022-06-30'
         and term['recognition_rule']=='CONFIRMED_PREOPEN_COMPLETION' and term['preopen_completion_confirmed'] is True
         and x['qualified_cash_only_primary_fact_sha256']==PRIMARY_SHA
         and x['no_stock_or_contingent_rights_in_common_consideration'] is True,
         'PENDING_CASH_EXACT_AMOUNT_CALENDAR_SEPARATE_PRIMARY')

def validate(catalog):
    namespace=dict(vars(original),__file__=__file__,CashInputBatch=PendingCashInput,
                   source_binding=source_binding,pending_clock=pending_clock)
    exec(compile(ast.Module(body=[validate_tree()],type_ignores=[]),'<original-validator-one-qualified-pending-clock>','exec'),namespace)
    result=namespace['validate'](catalog);validate_primary(catalog);return result

class QualifiedPendingCash:
    def __init__(self,catalog):
        if isinstance(catalog,Path):
            raw=catalog.read_bytes();catalog=json.loads(raw);need(raw==encoded(catalog),'PENDING_CASH_CANONICAL_CATALOG_BYTES')
        self._dict_init(catalog)
        self.catalog_sha=sha(encoded(catalog));self.compiler_sha=sha(Path(__file__).read_bytes())

need(original.QualifiedCashBatch.__init__.__closure__ is None,'PENDING_CASH_ORIGINAL_CONSTRUCTOR_NO_CLOSURE')
QualifiedPendingCash._dict_init=FunctionType(original.QualifiedCashBatch.__init__.__code__,
    dict(original.QualifiedCashBatch.__init__.__globals__,__file__=__file__,validate=validate),
    original.QualifiedCashBatch.__init__.__name__,original.QualifiedCashBatch.__init__.__defaults__)
