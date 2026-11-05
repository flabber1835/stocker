"""Full-checkpoint ordinary augmentation contract and source-qualified adapters."""
import ast
from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import system_campaign_financial_additional_sensor as original

CATALOG = 'system-campaign-p07-own1196-ordinary-augmentation.json'
DIRECTORY = 'ordinary-augmentation'
RECEIPT = 'ordinary-augmentation.json'
OVERLAY = 'ordinary-augmentation-overlay.json'
ADOPTION = 'ordinary-augmentation-adoption'
SCHEMA = 'research.retained-ordinary-augmentation/1'
HERE = Path(__file__).parent
need, sha, encoded = original.need, original.sha, original.encoded


def safe(name):
    p = PurePosixPath(name)
    need(type(name) is str and not p.is_absolute() and '..' not in p.parts
         and ':' not in name and '\\' not in name and p.as_posix() == name,
         'AUGMENTATION_SAFE_INPUT_RESOURCE')
    return name


def catalog():
    value = json.loads((HERE/CATALOG).read_bytes())
    need(value['schema'] == SCHEMA and value['arm'] == 'P07'
         and value['parent_completed'] == 1196 and type(value['parent_completed']) is int
         and value['parent_cursor'] == '2022-09-30'
         and len(value['parent_descriptors']) == 22
         and value['financial_authority'] is value['canonical_financial_source_changed'] is False,
         'AUGMENTATION_EXACT_CATALOG_SCHEMA')
    need(value['expected_tickers'] == ['GBT', 'TRQ'] and len(value['literal_sources']) == 2,
         'AUGMENTATION_EXACT_ORDERED_LITERAL_SOURCES')
    for name, pin in value['source_files'].items():
        need(Path(safe(name)).name == name and sha((HERE/name).read_bytes()) == pin,
             'AUGMENTATION_EXACT_QUALIFIED_SOURCE_FILES')
    return value


def parent_scope(cp, plan):
    need((cp['sha256'], cp['completed'], cp['source_cursor']) ==
         (plan['parent_outer_sha256'], plan['parent_completed'], plan['parent_cursor'])
         and cp['repairs'] == plan['parent_descriptors'], 'AUGMENTATION_EXACT_FULL_PARENT')


def suffix(cp, plan):
    need(cp['repairs'][:22] == plan['parent_descriptors']
         and len(cp['repairs']) in (22, 23), 'AUGMENTATION_COMPLETE_UNCHANGED_ORIGIN_PREFIX')
    return cp['repairs'][22:]


def validated_receipt(root, cp, plan, *, input_hash):
    """Validate every actual descriptor and input file; never truncate a checkpoint."""
    root = Path(root)
    tail = suffix(cp, plan)
    if not tail:
        parent_scope(cp, plan)
        need(not (root/RECEIPT).exists(), 'AUGMENTATION_NO_UNCOMMITTED_RECEIPT')
        return None
    raw = (root/RECEIPT).read_bytes()
    value = json.loads(raw)
    need(value['schema'] == SCHEMA and value['passed'] is True
         and value['catalog_sha256'] == sha((HERE/CATALOG).read_bytes())
         and value['parent_root_admission_sha256'] == plan['parent_root_admission_sha256']
         and value['parent_outer_sha256'] == plan['parent_outer_sha256']
         and value['parent_descriptors'] == plan['parent_descriptors']
         and value['adopted_descriptors'] == cp['repairs']
         and value['new_descriptor'] == tail[0]
         and value['financial_state_unchanged'] is True
         and type(value['financial_sessions_advanced']) is int
         and value['financial_sessions_advanced'] == 0
         and value['canonical_financial_source_changed'] is False,
         'AUGMENTATION_EXACT_RECEIPT_AND_FULL_INPUT_LIST')
    need(cp['run']['input_sha256'] == value['adopted_input_sha256'] == input_hash(cp['base'], cp['repairs']),
         'AUGMENTATION_FULL_CANONICAL_INPUT_HASH')
    values = original.descriptors(root, cp)
    d, doc = values[-1]
    need(doc['schema'] == 'terminal-repair/1'
         and d['resume_session'] == plan['parent_cursor']
         and d['predecessor_checkpoint_sha256'] == value['parent_inner_sha256']
         and sha((root/OVERLAY).read_bytes()) == d['sha256']
         and (root/OVERLAY).read_bytes() == (root/'book/repairs'/d['filename']).read_bytes()
         and (root/OVERLAY).read_bytes() == (root/DIRECTORY/'future-financial-overlay.json').read_bytes(),
         'AUGMENTATION_EXACT_NEW_ORDINARY_DESCRIPTOR')
    need(set(value['input_files']) >= {OVERLAY, DIRECTORY+'/parent-checkpoint.json.gz',
         DIRECTORY+'/future-financial-overlay.json', DIRECTORY+'/future-input-qualification.json',
         ADOPTION+'/checkpoint.json.gz', ADOPTION+'/proof.json', ADOPTION+'-correlation-inputs.jsonl.gz'},
         'AUGMENTATION_COMPLETE_RESOURCE_INVENTORY')
    for name, pin in value['input_files'].items():
        need(name in (OVERLAY,ADOPTION+'-correlation-inputs.jsonl.gz')
             or safe(name).startswith((DIRECTORY+'/',ADOPTION+'/')),
             'AUGMENTATION_DISTINCT_RESOURCE_NAMESPACE')
        need(sha((root/name).read_bytes()) == pin, 'AUGMENTATION_AUTHENTICATED_INPUT_RESOURCE_BYTES')
    qualification = json.loads((root/DIRECTORY/'future-input-qualification.json').read_bytes())
    flags = ('passed','only_terminal_field_changed','complete_terms_and_canonical_notional_verified',
             'original_incomplete_guard_retained','wrong_predecessor_and_consumed_date_refused',
             'wrong_native_and_delivery_witness_refused')
    need(all(qualification[k] is True for k in flags)
         and type(qualification['financial_sessions_advanced']) is int
         and qualification['financial_sessions_advanced'] == 0
         and type(qualification['packet_checks']) is int and qualification['packet_checks'] == 4,
         'AUGMENTATION_EXACT_ZERO_FINANCIAL_PACKET_QUALIFICATION')
    expected = [json.loads((HERE/source['catalog_file']).read_bytes())['terms'][0]
                for source in plan['literal_sources']]
    need(doc['add'] == [t['added'] for t in expected]
         and doc['suppress'] == [dict(session=t['native_session'],security_id=t['security_id'],
                                     term_sha256=t['native_term_sha256']) for t in expected],
         'AUGMENTATION_EXACT_QUALIFIED_CASH_TERMS_AND_NATIVE_PREIMAGES')
    return value


def model_tree(raw):
    """Keep the whole visitor and full input hash; validate the separate tail first."""
    fn = original.function(raw, 'validate_models')
    found = [n for n in ast.walk(fn) if isinstance(n, ast.Subscript)
             and ast.unparse(n) == "cp['repairs'][21:]"]
    need(len(found) == 1, 'AUGMENTATION_EXACT_MODEL_ORIGIN_SLICE_SITE')
    found[0].slice.upper = ast.Constant(22)
    fn.body.insert(1, ast.parse('validate_tail(root, cp, input_hash=input_hash)').body[0])
    return ast.fix_missing_locations(fn)


def validator(plan):
    raw = Path(original.__file__).read_bytes()
    need(sha(raw) == plan['source_files'][Path(original.__file__).name],
         'AUGMENTATION_UNCHANGED_FULL_MODEL_VISITOR_SOURCE')
    fn = model_tree(raw)
    def validate_tail(root, cp, *, input_hash):
        need(input_hash is not None, 'AUGMENTATION_REQUIRED_CANONICAL_HASH_FUNCTION')
        return validated_receipt(root, cp, plan, input_hash=input_hash)
    namespace = dict(vars(original), validate_tail=validate_tail)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<full-checkpoint-ordinary-suffix-visitor>', 'exec'), namespace)
    return namespace['validate_models']


def replace_exact(fn, expression, replacement, label):
    count = 0
    class Replace(ast.NodeTransformer):
        def visit_Compare(self, node):
            nonlocal count
            if ast.unparse(node) == expression:
                count += 1
                return ast.copy_location(ast.parse(replacement, mode='eval').body, node)
            return self.generic_visit(node)
    fn = Replace().visit(fn)
    need(count == 1, label)
    return fn


def runtime_tree(raw):
    """Explicit adoption/observer/review boundaries; original financial calls intact."""
    nodes = [deepcopy(n) for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)]
    by_name = {n.name:n for n in nodes}
    fn = by_name['verify_qualification']
    replace_exact(fn, "second['repairs'] == cp['repairs']", "second['repairs'] == cp['repairs'][:22]",
                  'AUGMENTATION_EXACT_ORIGIN_BOUNDARY_DESCRIPTOR_SITE')
    replace_exact(fn, "second['run']['input_sha256'] == cp['run']['input_sha256']",
                  'original_boundary_hash(second, cp)', 'AUGMENTATION_EXACT_ORIGIN_BOUNDARY_HASH_SITE')
    fn = by_name['run_retained']
    site, = [i for i,n in enumerate(fn.body) if isinstance(n, ast.Assign)
             and ast.unparse(n.targets[0]) == 'alder']
    fn.body.insert(site, ast.parse('adopted = adopt_ordinary(cp, out, args, rows, spec, old, p)').body[0])
    replace_exact(fn, "actual['repairs'] == cp['repairs']", "actual['repairs'] == adopted['repairs']",
                  'AUGMENTATION_EXACT_FINAL_DESCRIPTOR_SITE')
    replace_exact(fn, "actual['run']['input_sha256'] == cp['run']['input_sha256']",
                  "actual['run']['input_sha256'] == adopted['run']['input_sha256']",
                  'AUGMENTATION_EXACT_FINAL_FULL_INPUT_HASH_SITE')
    fn = by_name['review']
    replace_exact(fn, "parent['repairs'] == current['repairs']",
                  'review_ordinary(parent, current, evidence, out, spec)',
                  'AUGMENTATION_EXACT_REVIEW_ADOPTION_SITE')
    # Freeze the old observer manager under its own name before adding a new cash observer.
    observer = by_name['ordinary_observers']
    observer.name = 'inherited_ordinary_observers'
    return ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))


def remaining_tree(raw):
    fn = original.function(raw, 'remaining_ordinary_terms')
    block, = [n for n in ast.walk(fn) if isinstance(n, ast.If)
              and ast.unparse(n.test) == "doc['schema'] != 'terminal-repair/1'"]
    need(len(block.body) == 3 and isinstance(block.body[-1], ast.Continue),
         'AUGMENTATION_EXACT_INHERITED_TYPED_VISITOR_BLOCK')
    block.body = ast.parse("need(typed_input_valid(root, cp, entry), 'AUGMENTATION_FULL_TYPED_INPUT_VISITOR')\ncontinue").body
    return ast.fix_missing_locations(fn)


def pause_tree(raw):
    fn = original.legacy_function(raw, 'paused_own_adoption', 'pause')
    assignment, = [n for n in fn.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'names']
    need(isinstance(assignment.value, ast.Dict), 'AUGMENTATION_ORIGINAL_PAUSE_WHITELIST')
    assignment.value.keys.append(ast.Constant(ADOPTION))
    assignment.value.values.append(ast.Constant(OVERLAY))
    return ast.fix_missing_locations(fn)


def cash_tree(raw):
    fn = original.function(raw,'verify_event')
    assignment, = [n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == 'amount']
    need(ast.unparse(assignment.value) == 'D(quantity) * price', 'AUGMENTATION_ORIGINAL_CASH_AMOUNT_SITE')
    assignment.value = ast.parse("D(str(sum(e['current_shares'] * term['added']['cash_per_share'] for e in held)))",mode='eval').body
    replace_exact(fn,"sum((D(str(e['cash_delta'])) for e in paid), D(0)) == amount",
        "D(str(sum(e['cash_delta'] for e in paid))) == amount",'AUGMENTATION_ORIGINAL_CASH_SUM_SITE')
    replace_exact(fn,"D(str(e['cash_delta'])) == -D(str(e['shares_delta'])) * price",
        "D(str(e['cash_delta'])) == D(str(-e['shares_delta'] * term['added']['cash_per_share']))",
        'AUGMENTATION_ORIGINAL_CASH_SINGLE_PAYMENT_SITE')
    return ast.fix_missing_locations(fn)


def verify_cash_events(rows,events,observed,terms,through,plan):
    name='system_campaign_ordinary_augmentation_cash_v1.py';raw=(HERE/name).read_bytes()
    need(sha(raw) == plan['source_files'][name], 'AUGMENTATION_ORIGINAL_INDEPENDENT_CASH_REVIEW_SOURCE')
    namespace=dict(D=D,need=need)
    exec(compile(ast.Module(body=[cash_tree(raw)],type_ignores=[]),'<original-cash-review-canonical-float-operation-order>','exec'),namespace)
    expected={t['added']['session']:t for t in terms if t['added']['session'] <= through}
    need(len(expected) == sum(t['added']['session'] <= through for t in terms)
         and set(observed) == set(expected), 'AUGMENTATION_COMPLETE_COMMITTED_CASH_EVENT_AXIS')
    checked=[]
    for day,term in expected.items():
        index, = [i for i,r in enumerate(rows) if r['session'] == day]
        need(index > 0, 'AUGMENTATION_CASH_PRIOR_CLOSING_ACCOUNTING_REQUIRED')
        before=rows[index-1]['evidence']['research_entry_audit']['closing_accounting']
        opened=rows[index]['evidence']['research_entry_audit']['opening_accounting']
        checked.append(namespace['verify_event'](observed[day],term,before,opened,events))
    return checked
