"""Independent full-input outcome proof; original interval/account guards retained."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import shutil

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import sha
from system_campaign_uncertainty_context import discrete
from system_campaign_outcome_archive import seed
from system_campaign_outcome_input import MODE
from system_campaign_outcome_facts import retained
from system_campaign_outcome_basis import require_sources
from system_campaign_outcome_sensor import require_parent
from system_campaign_outcome_proof import certified_recovery, commitment
from system_campaign_outcome_frame import frame_copy
import system_campaign_chinook_review as original


def recovery_inputs(row):
    kwargs = deepcopy(row['complete_recovery_inputs'])
    need(set(kwargs) == {'state', 'native', 'wc_drawdown', 'spy_r20', 'wc_r20', 'recent_r20', 'recent_r40'}
         and discrete(kwargs['state']) == row['before']
         and kwargs['state']['last_session'] == row['session']
         and {k: v for k, v in kwargs.items() if k != 'state'} == row['scalar_inputs']
         and commitment(kwargs) == row['comparisons']['input_sha256'],
         'OUTCOME_REVIEW_EXACT_COMPLETE_ACTUAL_RECOVERY_INPUTS')
    return kwargs


def checked_recovery(function, kwargs, bounds):
    result, proof = certified_recovery(function, kwargs, bounds)
    frame_copy(kwargs['state'], result[0])
    return result, proof


def comparison_count(proof):
    return sum(len(leaf['comparisons']) for leaf in proof['leaves'])


def comparison_invariance(prior, rows):
    return prior['every_actual_comparison_invariant'] and all(
        row['comparisons']['all_individual_comparisons_invariant'] for row in rows)


def compile_review(model, parent_summary):
    """Adapt only full-frame proof, parent admission and truthful summary sites."""
    require_sources()
    function, = [node for node in ast.parse(Path(original.__file__).read_bytes()).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'review']
    changes = dict(parent=0, fresh=0, update=0, cursor=0, inputs=0, count=0, summary=0)

    class ProofSites(ast.NodeTransformer):
        def visit_Subscript(self, node):
            if ast.unparse(node) == "prior['every_actual_comparison_invariant']":
                changes['parent'] += 1
                return ast.copy_location(ast.parse('parent_admitted(prior)', mode='eval').body, node)
            return self.generic_visit(node)

        def visit_Assign(self, node):
            text = ast.unparse(node)
            if text == 'state = median5.fresh(champion=True)':
                changes['fresh'] += 1
                return ast.copy_location(ast.Pass(), node)
            if text == "state['last_session'] = row['session']":
                changes['cursor'] += 1
                return ast.copy_location(ast.Pass(), node)
            if text == "kwargs = dict(row['scalar_inputs'], state=state)":
                changes['inputs'] += 1
                return ast.copy_location(ast.parse('kwargs = recovery_inputs(row)').body[0], node)
            return self.generic_visit(node)

        def visit_Expr(self, node):
            if ast.unparse(node) == "state.update(row['before'])":
                changes['update'] += 1
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

        def visit_AugAssign(self, node):
            if ast.unparse(node) == 'checks_count += len(checks)':
                changes['count'] += 1
                return ast.copy_location(ast.parse('checks_count += comparison_count(checks)').body[0], node)
            return self.generic_visit(node)

        def visit_Call(self, node):
            if (isinstance(node.func, ast.Name) and node.func.id == 'save'
                    and len(node.args) == 2 and ast.unparse(node.args[0]) == 'output'):
                changes['summary'] += 1
                summary = node.args[1]
                need(isinstance(summary, ast.Call) and ast.unparse(summary.func) == 'dict',
                     'OUTCOME_EXACT_ORIGINAL_REVIEW_SUMMARY')
                replacements = {
                    'schema': "'research.joint-leadership-uncertainty-independent-review/2'",
                    'status': "'COMMITTED_PREFIX_COMPLETE_CONTROLLER_OUTCOME_INVARIANT'",
                    'every_actual_comparison_invariant': 'comparison_invariance(prior, rows[n:])'}
                for key, expression in replacements.items():
                    item, = [value for value in summary.keywords if value.arg == key]
                    item.value = ast.parse(expression, mode='eval').body
                additions = dict(every_complete_controller_result_equal='True', proof_mode='MODE',
                    proof_input_sha256='model.sha256', every_actual_complete_input_frame_checked='True',
                    nonrecovery_frame_copied_unchanged='True', whole_witness_valuation_not_claimed_unique='True')
                need(not set(additions) & {v.arg for v in summary.keywords},
                     'OUTCOME_SUMMARY_ADDITIONS_NOT_OVERRIDES')
                summary.keywords.extend(ast.keyword(arg=key, value=ast.parse(value, mode='eval').body)
                                        for key, value in additions.items())
            return self.generic_visit(node)

    adapted = ProofSites().visit(function)
    need(all(v == 1 for v in changes.values()), 'OUTCOME_EXACT_DECLARED_REVIEW_ADAPTATION_SITES')

    def parent_admitted(value):
        need(value == parent_summary, 'OUTCOME_EXACT_PREVALIDATED_PARENT_SUMMARY')
        return True

    namespace = dict(vars(original), seed=seed, certified_recovery=checked_recovery,
        recovery_inputs=recovery_inputs, comparison_count=comparison_count,
        comparison_invariance=comparison_invariance, parent_admitted=parent_admitted,
        model=model, MODE=MODE)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[adapted], type_ignores=[])),
                 '<original-four-event-review-with-complete-actual-frame-proof>', 'exec'), namespace)
    return namespace['review']


def parent_admission(old, parent, spec):
    model, _ = retained(old, parent)
    raw = (old / 'uncertainty-certificate-review.json').read_bytes()
    admission = require_parent(seed(old, parent), parent,
        (old / 'uncertainty-certificate.jsonl').read_bytes(), raw, spec, model)
    return admission, json.loads(raw)


def review(root, old, spec, output):
    hosted()
    from research.pooled_vacancy_funding import journal
    parent = journal.read_checkpoint(old / spec['selected_checkpoint'])
    current = journal.read_checkpoint(root / 'book/checkpoint.json.gz')
    _, summary = parent_admission(old, parent, spec)
    model, _ = retained(root, current)
    need(model is not None, 'OUTCOME_REVIEW_EXACT_TYPED_PROOF_INPUT_REQUIRED')
    compile_review(model, summary)(root, old, spec, output)


def preserve_parent(old, out, cp, spec):
    """Copy exact prior review, guards and all four archived event predecessors."""
    hosted()
    require_sources()
    from research.pooled_vacancy_funding import journal
    _, proof = parent_admission(old, cp, spec)
    events = [proof['event_resolution'], *proof['guarded_completion_events'],
              proof['abiomed_event_resolution']]
    if proof.get('chinook_event_resolution') is not None:
        events.append(proof['chinook_event_resolution'])
    names = []
    for event in events:
        path = Path(event.get('path', event.get('actual_predecessor')))
        need(not path.is_absolute() and '..' not in path.parts
             and path.parts[:2] == ('book', 'pre-event'), 'OUTCOME_SAFE_RETAINED_EVENT_PATH')
        raw = (old / path).read_bytes()
        value = journal.read_checkpoint(old / path)
        need(sha(raw) == event['file_sha256'] and value['sha256'] == event['outer_sha256'],
             'OUTCOME_EXACT_CANONICAL_PARENT_EVENT_BYTES')
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            need(target.read_bytes() == raw, 'OUTCOME_EXISTING_EVENT_ARCHIVE_NOT_OVERWRITTEN')
        else:
            shutil.copyfile(old / path, target)
        names.append(path.as_posix())
    need(len(names) == len(set(names)), 'OUTCOME_EACH_ORIGINAL_EVENT_ARCHIVE_PRESERVED_ONCE')
    (out / 'parent-three-sensor-certificate-review.json').write_bytes(
        (old / 'uncertainty-certificate-review.json').read_bytes())
    guard = (old / 'completion-position-guard-review.json').read_bytes()
    need(sha(guard) == spec['completion_guard_review_sha256'], 'OUTCOME_EXACT_PARENT_POSITION_GUARD_BYTES')
    (out / 'parent-completion-position-guard-review.json').write_bytes(guard)
    save(out / 'outcome-parent-certificate-admission.json', dict(
        checkpoint_sha256=cp['sha256'], through=cp['source_cursor'], rows=proof['rows'],
        archived_events=names, all_original_certificate_claims_preserved=True,
        parent_comparison_invariance=proof['every_actual_comparison_invariant'], production_contacted=False))
    return proof
