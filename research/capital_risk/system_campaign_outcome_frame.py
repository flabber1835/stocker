"""Source-bound recovery dependencies and unchanged non-recovery state frame."""
import ast
from copy import deepcopy
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_uncertainty_context import DISCRETE, discrete
from system_campaign_outcome_proof import certified_recovery, exact_equal

READS = frozenset(('previous_native', 'effective_native', 'episode', 'latched',
                   'full_streak', 'recent_positive_streak', 'champion_audit'))


def frame_copy(before, after):
    need(set(before) == set(after), 'OUTCOME_COMPLETE_CONTROLLER_FRAME_FIELDS')
    need(exact_equal({k: v for k, v in before.items() if k not in DISCRETE},
                     {k: v for k, v in after.items() if k not in DISCRETE}),
         'OUTCOME_ALL_NONRECOVERY_FRAME_FIELDS_COPIED_UNCHANGED')
    return True


def recover_dependencies(raw):
    function, = [node for node in ast.parse(raw).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'recover']
    keys = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'state':
            need(isinstance(node.slice, ast.Constant) and type(node.slice.value) is str,
                 'OUTCOME_NO_DYNAMIC_RECOVERY_FRAME_READ')
            keys.add(node.slice.value)
        if isinstance(node, ast.Call):
            for arg in (*node.args, *(v.value for v in node.keywords)):
                if isinstance(arg, ast.Name) and arg.id == 'state':
                    need(ast.unparse(node.func) in ('validate', 'validate_recovery'),
                         'OUTCOME_FRAME_ONLY_PASSED_TO_PINNED_VALIDATORS')
    need(keys == READS, 'OUTCOME_RECOVERY_READS_ONLY_DECLARED_LOGICAL_FIELDS')
    return dict(recover_ast_sha256=digest(ast.dump(function, include_attributes=False)),
                direct_state_reads=sorted(keys), whole_state_calls=['validate', 'validate_recovery'])


def qualify(source_hashes, out, kwargs, bounds):
    from full_system_core import hosted
    hosted()
    from sentinel.controller import champion_config
    from system_campaign_outcome_facts import CONTRACT
    from full_system_benchmark import save
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name, expected in source_hashes.items():
        need(sha((Path('/variant') / name).read_bytes()) == expected,
             'OUTCOME_FRAME_ACTUAL_FROZEN_SOURCE_IDENTITY')
    dependencies = recover_dependencies((Path('/variant') / 'sentinel/controller/champion.py').read_bytes())
    need(dependencies == contract['frame_dependencies'], 'OUTCOME_EXACT_AUDITED_FRAME_DEPENDENCIES')
    original, proof = certified_recovery(champion_config.recover, kwargs, bounds)
    frame_copy(kwargs['state'], original[0])
    changed = deepcopy(kwargs)
    changed['state']['witness_nav'] = [2. + i / 100 for i in range(41)]
    changed['state']['selected'] = ['synthetic-frame-only']
    changed['state']['selected_closes'] = {'synthetic-frame-only': 3.}
    changed['state']['peer_keys'] = {'synthetic-frame-only': ['SYNTHETIC', '', 'synthetic-frame-only']}
    alternative, other = certified_recovery(champion_config.recover, changed, bounds)
    frame_copy(changed['state'], alternative[0])
    need(discrete(original[0]) == discrete(alternative[0]) and original[1] == alternative[1]
         and not exact_equal(original[0], alternative[0]),
         'OUTCOME_VALID_FRAME_CHANGE_PRESERVES_ONLY_LOGICAL_STATE_AND_DECISION')
    save(out, dict(status='ACTUAL_CANONICAL_RECOVERY_FRAME_DEPENDENCY_QUALIFIED',
        dependencies=dependencies, actual_frame_copied=True, alternative_valid_frame_copied=True,
        alternative_frame_has_same_recovery_and_decision=True,
        complete_alternative_frames_not_claimed_identical=True,
        ordinary_complete_result_sha256=proof['ordinary_result_sha256'],
        alternative_complete_result_sha256=other['ordinary_result_sha256'],
        financial_sessions_advanced=0, production_contacted=False))
    return dependencies
