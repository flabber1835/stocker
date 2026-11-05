"""Retain the original certificate chain while admitting explicitly typed rows."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_outcome_input import MODE
from system_campaign_outcome_facts import CONTRACT, retained
import system_campaign_uncertainty_review as original

SCHEMA = 'research.leadership-uncertainty-certificate/2'


def require_sources():
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name in ('system_campaign_uncertainty_review.py',
                 'system_campaign_uncertainty_context.py'):
        need(sha((Path(__file__).parent / name).read_bytes()) == contract['inherited_sources'][name],
             'OUTCOME_EXACT_ORIGINAL_CHAIN_AND_PREFIX_IMPLEMENTATIONS')


def row_schema(row, model):
    if row['schema'] == original.SCHEMA:
        need('complete_recovery_inputs' not in row and 'proof_input_sha256' not in row,
             'OUTCOME_ORIGINAL_CERTIFICATE_NOT_RELABELED')
        return True
    need(row['schema'] == SCHEMA and model is not None
         and row['session'] >= model.first_affected_session
         and row['proof_mode'] == MODE and row['proof_input_sha256'] == model.sha256
         and row['comparisons']['schema'] == 'research.complete-controller-outcome-proof/1'
         and row['comparisons']['all_complete_results_equal'] is True
         and isinstance(row['complete_recovery_inputs'], dict),
         'OUTCOME_ONLY_EXPLICIT_TYPED_COMPLETE_RESULT_CERTIFICATES')
    return True


def seed(root, cp):
    """Original exact bytes, chain seed, financial/watch joins; one schema site."""
    require_sources()
    model, _ = retained(root, cp)
    function, = [n for n in ast.parse(Path(original.__file__).read_bytes()).body
                 if isinstance(n, ast.FunctionDef) and n.name == 'seed']
    sites = [n for n in ast.walk(function) if isinstance(n, ast.Compare)
             and ast.unparse(n) == "row['schema'] == SCHEMA"]
    need(len(sites) == 1, 'OUTCOME_ONE_EXACT_ORIGINAL_CERTIFICATE_SCHEMA_SITE')

    class SchemaSite(ast.NodeTransformer):
        def visit_Compare(self, node):
            if ast.unparse(node) == "row['schema'] == SCHEMA":
                return ast.copy_location(ast.parse('row_schema(row, model)', mode='eval').body, node)
            return self.generic_visit(node)

    adapted = SchemaSite().visit(deepcopy(function))
    namespace = dict(vars(original), row_schema=row_schema, model=model)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[adapted], type_ignores=[])),
                 '<original-chain-with-explicit-typed-outcome-schema>', 'exec'), namespace)
    return namespace['seed'](root, cp)


def preserve_and_seed(old, out, cp):
    require_sources()
    function = original.preserve_and_seed
    need(function.__closure__ is None, 'OUTCOME_ORIGINAL_ARCHIVE_WITHOUT_HIDDEN_CLOSURE')
    preserved = FunctionType(function.__code__, dict(function.__globals__, seed=seed),
                             function.__name__, function.__defaults__)
    need(preserved.__code__ is function.__code__, 'OUTCOME_UNCHANGED_FULL_STREAM_AND_TAIL_ARCHIVE')
    return preserved(old, out, cp)
