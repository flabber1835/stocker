"""Explicit source member selection for the unchanged qualified cash predicates."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictInt
import system_campaign_qualified_cash_batch as original

ORIGINAL_SHA = '96c9763e021c72c784b04c7033dd32940b9809cff6b56ba0e394287e0cdd3f36'


class CashInputSubset(original.CashInputBatch):
    schema_id: Literal['research.qualified-own-cash-input-subset/1'] = Field(alias='schema')
    selected_source_indices: Annotated[list[StrictInt], Field(min_length=1, max_length=128)]
    retained_source_indices: Annotated[list[StrictInt], Field(max_length=128)] = Field(default_factory=list)


def selected_members(catalog, payload, review):
    indices = catalog['selected_source_indices']
    original.need(all(type(i) is int and 0 <= i < len(payload['terms']) for i in indices)
                  and indices == sorted(set(indices)) and len(indices) == len(catalog['terms']),
                  'CASH_SUBSET_EXACT_SORTED_UNIQUE_SOURCE_INDICES')
    return ([payload['terms'][i] for i in indices], [payload['scope']['terms'][i] for i in indices],
            [review['terms'][i] for i in indices])


def validator():
    raw = Path(original.__file__).read_bytes()
    original.need(hashlib.sha256(raw).hexdigest() == ORIGINAL_SHA, 'CASH_SUBSET_ORIGINAL_VALIDATOR_BYTES')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'validate']
    site, = [i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
             and ast.unparse(n.targets[0]) == '(terms, captured, declared)']
    fn.body.insert(site + 1, ast.parse('captured, declared, checked_members = selected_members(catalog, payload, review)').body[0])

    class SelectedReview(ast.NodeTransformer):
        replacements = 0

        def visit_Subscript(self, node):
            if ast.unparse(node) == "review['terms']":
                self.replacements += 1
                return ast.copy_location(ast.Name(id='checked_members', ctx=ast.Load()), node)
            return self.generic_visit(node)

    adapter = SelectedReview()
    fn = adapter.visit(fn)
    original.need(adapter.replacements == 2, 'CASH_SUBSET_EXACT_TWO_REVIEW_MEMBER_SITES')
    namespace = dict(vars(original), __file__=__file__, CashInputBatch=CashInputSubset, selected_members=selected_members)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<unchanged-qualified-cash-validator-with-explicit-source-subset>', 'exec'), namespace)
    return namespace['validate']


def validate(catalog):
    result = validator()(catalog)
    retained_indices = catalog.get('retained_source_indices', [])
    original.need(retained_indices == sorted(set(retained_indices))
                  and set(retained_indices).issubset(catalog['selected_source_indices'])
                  and retained_indices == [i for i,t in zip(catalog['selected_source_indices'], catalog['terms'], strict=True)
                                           if 'retained_qualified_legal_term' in t],
                  'CASH_SUBSET_EXACT_DECLARED_RETAINED_SOURCE_MODES')
    for term in catalog['terms']:
        retained = term.get('retained_qualified_legal_term')
        if retained is None:
            continue
        name = retained['catalog_file']
        original.need(Path(name).name == name and name.endswith('.json'), 'CASH_SUBSET_SAFE_ORIGINAL_CATALOG')
        raw = (Path(__file__).parent / name).read_bytes()
        original.need(original.sha(raw) == retained['catalog_sha256'], 'CASH_SUBSET_EXACT_ORIGINAL_CATALOG')
        matches = [v for v in json.loads(raw)['terms'] if original.digest(v) == retained['term_sha256']]
        original.need(len(matches) == 1, 'CASH_SUBSET_ONE_EXACT_ORIGINAL_TERM')
        prior, = matches
        fields = ('ticker', 'security_id', 'native_session', 'native_term_sha256', 'last_trading_session',
                  'actual_completion_date', 'mandatory_common_share_completion_confirmed',
                  'preopen_completion_confirmed', 'recognition_rule', 'primary_source', 'description', 'added')
        original.need(all(term[k] == prior[k] for k in fields)
                      and term.get('research_assumption') == prior.get('research_assumption')
                      and prior.get('portfolio_completion_authorized', True) is True
                      and not prior.get('require_unowned_and_unordered', False),
                      'CASH_SUBSET_ALL_ORIGINAL_ECONOMIC_FIELDS_AND_HELD_AUTHORITY')
    return result


class QualifiedCashSubset:
    def __init__(self, catalog):
        if isinstance(catalog, Path):
            raw = catalog.read_bytes()
            catalog = json.loads(raw)
        else:
            raw = original.encoded(catalog)
        validate(catalog)
        self.catalog = deepcopy(catalog)
        self.catalog_sha = original.sha(raw)
        self.compiler_sha = original.sha(Path(__file__).read_bytes())
