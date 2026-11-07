"""Whole original cash records plus exact new own-parent source identity."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictInt
import system_campaign_qualified_cash_batch as original

ORIGINAL_SHA = '96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'
REFERENCE = 'retained_qualified_legal_term'
FRESH = frozenset({'arm','parent_cursor','parent_outer_sha256','parent_root_admission_sha256',
                   'parent_positions','identity_witness','native','source_capture'})


class OriginalCashLiterals(original.CashInputBatch):
    schema_id: Literal['research.qualified-own-original-cash-literals/1'] = Field(alias='schema')
    selected_source_indices: Annotated[list[StrictInt], Field(min_length=1, max_length=128)]


def selected_members(catalog, payload, review):
    indices = catalog['selected_source_indices']
    original.need(indices == sorted(set(indices)) and len(indices) == len(catalog['terms'])
                  and all(type(i) is int and 0 <= i < len(payload['terms']) for i in indices),
                  'ORIGINAL_CASH_LITERALS_SORTED_UNIQUE_EXACT_SOURCE_MEMBERS')
    return ([payload['terms'][i] for i in indices], [payload['scope']['terms'][i] for i in indices],
            [review['terms'][i] for i in indices])


def existing_cash_policy(term):
    from system_campaign_cash_calendar import PREOPEN, NEXT
    return term['recognition_rule'] in (PREOPEN, NEXT) and REFERENCE in term


def validate_original_literal(term):
    reference = term[REFERENCE]
    name = reference['catalog_file']
    original.need(Path(name).name == name and name.endswith('.json'), 'ORIGINAL_CASH_LITERALS_SAFE_CATALOG_NAME')
    raw = (Path(original.__file__).parent/name).read_bytes()
    from system_campaign_financial_future import OWN_CASH_CATALOG, OWN_CASH_SHA, OWN_CASH_PHASES, CLOSED_CASH_GENERATIONS
    if name == OWN_CASH_CATALOG:
        original.need(original.sha(raw) == OWN_CASH_SHA, 'ORIGINAL_CASH_LITERALS_CURRENT_QUALIFIED_OWN_CATALOG')
        value = json.loads(raw)
        count = len(value['terms']) if reference['catalog_sha256'] == OWN_CASH_SHA else CLOSED_CASH_GENERATIONS.get(reference['catalog_sha256'])
        original.need(type(count) is int and 0 < count <= len(value['terms']),
                      'ORIGINAL_CASH_LITERALS_ONLY_REGISTERED_CLOSED_GENERATION')
        raw = original.encoded(dict(value, terms=value['terms'][:count]))
    else:
        raw_prior = (Path(original.__file__).parent/'system-campaign-parallel-discovery-request-001.json').read_bytes()
        original.need(original.sha(raw_prior) == '863f6c7983fc2cdc1a86bd58a9c4987744d180e8bb56568608eda77d29f85fcd'
                      and json.loads(raw_prior)['sources'].get(name) == reference['catalog_sha256'],
                      'ORIGINAL_CASH_LITERALS_REGISTERED_FROZEN_ORIGINAL_CATALOG')
    original.need(original.sha(raw) == reference['catalog_sha256'], 'ORIGINAL_CASH_LITERALS_EXACT_CATALOG_BYTES')
    records = [v for v in json.loads(raw)['terms'] if original.digest(v) == reference['term_sha256']]
    original.need(len(records) == 1, 'ORIGINAL_CASH_LITERALS_ONE_EXACT_QUALIFIED_RECORD')
    prior, = records
    if name == OWN_CASH_CATALOG:
        original.need(OWN_CASH_PHASES.get((prior['arm'],prior['parent_cursor'])) == prior['ticker'],
                      'ORIGINAL_CASH_LITERALS_REGISTERED_QUALIFIED_OWN_PHASE')
    original.need(set(term) == set(prior)|FRESH|{REFERENCE}
                  and all(term[k] == v for k,v in prior.items() if k not in FRESH)
                  and prior.get('portfolio_completion_authorized', True) is True
                  and not prior.get('require_unowned_and_unordered', False)
                  and not prior.get('require_never_held', False),
                  'ORIGINAL_CASH_LITERALS_ALL_ORIGINAL_FIELDS_AND_HELD_AUTHORITY')


def validator_tree():
    raw = Path(original.__file__).read_bytes()
    original.need(original.sha(raw) == ORIGINAL_SHA, 'ORIGINAL_CASH_LITERALS_UNCHANGED_BASE_VALIDATOR')
    fn, = [n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name == 'validate']
    site, = [i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
             and ast.unparse(n.targets[0]) == '(terms, captured, declared)']
    fn.body.insert(site+1, ast.parse('captured, declared, checked_members = selected_members(catalog, payload, review)').body[0])
    class Bind(ast.NodeTransformer):
        members = policy = 0
        def visit_Subscript(self,node):
            if ast.unparse(node) == "review['terms']":
                self.members += 1
                return ast.copy_location(ast.Name(id='checked_members',ctx=ast.Load()),node)
            return self.generic_visit(node)
        def visit_Call(self,node):
            node = self.generic_visit(node)
            if any(isinstance(v,ast.Constant) and v.value == 'CASH_BATCH_ONLY_EXISTING_CASH_POLICIES' for v in node.args):
                self.policy += 1
                node.args[0] = ast.parse('existing_cash_policy(term)',mode='eval').body
            return node
    binder = Bind(); fn = binder.visit(fn)
    original.need(binder.members == 2 and binder.policy == 1, 'ORIGINAL_CASH_LITERALS_EXACT_MEMBER_AND_POLICY_SITES')
    loop, = [n for n in fn.body if isinstance(n,ast.For)]
    site, = [i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == 'extraction']
    original.need('CASH_BATCH_EXACT_PRIMARY_AMOUNT_AND_DATE_EXTRACTION' in ast.unparse(loop.body[site+1]),
                  'ORIGINAL_CASH_LITERALS_ONE_EXACT_NEW_PRIMARY_EXTRACTION_BLOCK')
    loop.body[site:site+2] = ast.parse('validate_original_literal(term)').body
    return ast.fix_missing_locations(fn)


def validate(catalog):
    namespace = dict(vars(original), __file__=__file__, CashInputBatch=OriginalCashLiterals,
        selected_members=selected_members, existing_cash_policy=existing_cash_policy,
        validate_original_literal=validate_original_literal)
    exec(compile(ast.Module(body=[validator_tree()],type_ignores=[]),
                 '<unchanged-own-source-predicates-and-whole-original-cash-literals>', 'exec'),namespace)
    return namespace['validate'](catalog)


class QualifiedOriginalCashLiterals:
    def __init__(self,catalog):
        if isinstance(catalog,Path):
            raw = catalog.read_bytes(); catalog = json.loads(raw)
        else: raw = original.encoded(catalog)
        validate(catalog)
        self.catalog = deepcopy(catalog)
        self.catalog_sha = original.sha(raw)
        self.compiler_sha = original.sha(Path(__file__).read_bytes())
