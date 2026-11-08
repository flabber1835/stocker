"""Bind proof-only admission to an actual immutable predecessor and public code."""
import gzip
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
from system_campaign_outcome_input import SCHEMA, MODE, LINEAGE_FIELDS, parse

HERE = Path(__file__).resolve().parent
CONTRACT = 'system-campaign-outcome-refinement-contract.json'
EVIDENCE = (('contract', CONTRACT), ('typed-codec', 'system_campaign_outcome_input.py'),
    ('complete-result-proof', 'system_campaign_outcome_proof.py'),
    ('certificate-adapter', 'system_campaign_outcome_sensor.py'),
    ('independent-reviewer', 'system_campaign_outcome_review.py'),
    ('semantic-composition', 'system_campaign_outcome_basis.py'),
    ('prefix-archive', 'system_campaign_outcome_archive.py'),
    ('boundary-binding', 'system_campaign_outcome_facts.py'),
    ('recovery-frame', 'system_campaign_outcome_frame.py'),
    ('input-integration', 'system_campaign_outcome_integration_gate.py'),
    ('canonical-qualification', 'system_campaign_outcome_gate.py'))


def evidence():
    return [dict(reference='research:system-optimization-002/controller-outcome/'+label+'/1',
        sha256=sha((HERE/name).read_bytes()),
        description='Exact proof-only controller outcome refinement contract or implementation.')
        for label, name in EVIDENCE]


def boundary(cp, raw, dates):
    """Pure hash/date bindings; canonical restoration and prefixes are separate."""
    need(json.loads(gzip.decompress(raw)) == cp
         and cp['sha256'] == digest({k: v for k, v in cp.items() if k != 'sha256'})
         and cp['run']['checkpoint_sha256'] == digest({k: v for k, v in cp['run'].items()
                                                      if k != 'checkpoint_sha256'})
         and cp['run']['state_sha256'] == digest(cp['run']['state'])
         and cp['run']['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs'])),
         'OUTCOME_FULL_PARENT_FILE_OUTER_INNER_STATE_INPUT_METADATA')
    index = dates.index(cp['source_cursor'])
    need(index + 1 < len(dates) and dates[index] < dates[index + 1],
         'OUTCOME_ACTUAL_ADJACENT_NEXT_FROZEN_SESSION')
    return dict(outer_sha256=cp['sha256'], inner_sha256=cp['run']['checkpoint_sha256'],
        input_sha256=cp['run']['input_sha256'], file_sha256=sha(raw),
        session=cp['source_cursor'], next_session=dates[index + 1])


def document(root, cp):
    need(cp['run']['input_sha256'] == digest(dict(base=cp['base'], repairs=cp['repairs'])),
         'OUTCOME_FULL_INPUT_SET_METADATA')
    found = []
    for item in cp['repairs']:
        raw = (root/'book/repairs'/item['filename']).read_bytes()
        need(item['filename'] == item['sha256']+'.json' and sha(raw) == item['sha256'],
             'OUTCOME_ALL_ACTUAL_DESCRIPTOR_BYTES')
        value = json.loads(raw)
        if value['schema'] == SCHEMA:
            found.append((item, value))
    need(len(found) <= 1, 'OUTCOME_ONE_PROOF_REFINEMENT_MODEL')
    return found


def retained(root, cp, out=None):
    hosted()
    from research.pooled_input_support.bundle import axis
    matches = document(root, cp)
    if not matches:
        return None, None
    descriptor, value = matches[0]
    name = Path('book/predecessor-checkpoints')/(value['parent_outer_sha256']+'.json.gz')
    raw = (root/name).read_bytes()
    prior = json.loads(gzip.decompress(raw))
    bound = boundary(prior, raw, axis())
    obj = parse(root/'book/repairs'/descriptor['filename'],
        resume_session=descriptor['resume_session'],
        predecessor_checkpoint_sha256=descriptor['predecessor_checkpoint_sha256'],
        expected_evidence=evidence(), boundary=bound)
    need(obj.sha256 == descriptor['sha256'], 'OUTCOME_EXACT_RETAINED_TYPED_PROOF_MODEL')
    if out is not None:
        target = out/name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            need(target.read_bytes() == raw, 'OUTCOME_EXISTING_ORIGINAL_BOUNDARY_BYTES')
        else:
            target.write_bytes(raw)
    return obj, bound


def build(cp, out, bound):
    need(cp['sha256'] == bound['outer_sha256']
         and cp['run']['checkpoint_sha256'] == bound['inner_sha256']
         and cp['run']['input_sha256'] == bound['input_sha256']
         and cp['source_cursor'] == bound['session'], 'OUTCOME_CREATE_FROM_EXACT_OWN_BOUNDARY')
    value = dict(schema=SCHEMA, predecessor_checkpoint_sha256=bound['inner_sha256'],
        parent_outer_sha256=bound['outer_sha256'], parent_file_sha256=bound['file_sha256'],
        parent_input_sha256=bound['input_sha256'], first_affected_session=bound['next_session'],
        proof_mode=MODE, max_leaves=64, max_nodes=127, max_depth=16,
        no_point_valuation=True, retained_uncertainty_models_unchanged=True,
        source_evidence=evidence())
    path = out/'controller-outcome-proof-input.json'
    save(path, value)
    return path


def common_semantics(obj):
    value = obj.model_dump(by_alias=True)
    need(set(value) >= LINEAGE_FIELDS, 'OUTCOME_EXPLICIT_LINEAGE_FIELDS_PRESENT')
    for name in LINEAGE_FIELDS:
        value.pop(name)
    return value
