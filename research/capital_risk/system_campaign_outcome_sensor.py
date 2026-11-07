"""Complete-outcome proof on the unchanged four-event interval machinery."""
from copy import deepcopy
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_uncertainty_context as inherited
import system_campaign_abiomed_sensor as abiomed
import system_campaign_chinook_sensor as chinook
from system_campaign_zogenix_sensor import isolated_function
from system_campaign_outcome_archive import SCHEMA
from system_campaign_outcome_input import MODE
from system_campaign_outcome_proof import certified_recovery, commitment
from system_campaign_outcome_frame import frame_copy


def require_parent(seed, checkpoint, certificate_raw, review_raw, spec, model=None):
    proof = json.loads(review_raw)
    need(sha(review_raw) == spec['interval_review_sha256']
         and proof['checkpoint_sha256'] == checkpoint['sha256'] == spec['outer_sha256']
         and proof['through'] == checkpoint['source_cursor'] == spec['selected_session'],
         'OUTCOME_EXACT_OWN_AUTHENTICATED_PARENT')
    flags = ('every_committed_watch_and_financial_row_bound',
             'every_discrete_controller_state_equal',
             'every_new_abiomed_before_and_after_position_and_intent_checked',
             'every_new_chinook_before_and_after_position_and_intent_checked',
             'no_owned_cvr_accounting_supported')
    need(all(proof.get(k) is True for k in flags)
         and proof.get('abiomed_event_resolution') is not None,
         'OUTCOME_ALL_ORIGINAL_PARENT_COMMITMENTS_AND_POSITION_PROOFS')
    invariant = proof.get('every_actual_comparison_invariant')
    need(type(invariant) is bool, 'OUTCOME_TRUTHFUL_PARENT_COMPARISON_FLAG')
    if model is None:
        need(invariant is True
             and proof['schema'] == 'research.joint-leadership-uncertainty-independent-review/1',
             'OUTCOME_FIRST_REFINEMENT_REQUIRES_ORIGINAL_STRICT_PARENT')
        mode = 'ORIGINAL_COMPARISON_PROOF'
    else:
        reference, = [v for v in model.source_evidence
                      if v.reference == 'research:system-optimization-002/controller-outcome/certificate-adapter/1']
        need(reference.sha256 == sha(Path(__file__).read_bytes())
             and proof['schema'] == 'research.joint-leadership-uncertainty-independent-review/2'
             and proof['every_complete_controller_result_equal'] is True
             and proof['proof_mode'] == MODE and proof['proof_input_sha256'] == model.sha256,
             'OUTCOME_RETAINED_EXACT_TYPED_COMPLETE_RESULT_PARENT')
        mode = 'EXPLICIT_COMPLETE_OUTCOME_PROOF'
    selected = [(line, json.loads(line)) for line in certificate_raw.splitlines(keepends=True)
                if json.loads(line)['session'] <= checkpoint['source_cursor']]
    prefix = b''.join(line for line, _ in selected)
    rows = [row for _, row in selected]
    need(certificate_raw.startswith(prefix) and seed == rows and seed
         and len(seed) == proof['rows'] == spec['parent_certificate_rows']
         and seed[-1]['session'] == checkpoint['source_cursor']
         and [r['session'] for r in seed] == sorted({r['session'] for r in seed}),
         'OUTCOME_EXACT_COMPLETE_PARENT_SEED_WITHOUT_UNSENT_TAIL')
    return dict(parent_checkpoint_sha256=checkpoint['sha256'], through=checkpoint['source_cursor'],
        rows=len(seed), committed_bytes=len(prefix), committed_sha256=sha(prefix),
        full_parent_certificate_sha256=sha(certificate_raw), parent_review_sha256=sha(review_raw),
        parent_proof_mode=mode, every_actual_parent_comparison_invariant=invariant,
        original_joint_math_not_reset=True)


complete_recover = isolated_function(inherited.SensorCertificate.recover,
    certified_recovery=certified_recovery, SCHEMA=SCHEMA)


class SensorCertificate(chinook.SensorCertificate):
    def __init__(self, *args, abiomed_codec, abiomed_native, abiomed_source,
                 parent_checkpoint, parent_certificate_raw, parent_review_raw,
                 parent_spec, abiomed_model, chinook_codec, chinook_native,
                 chinook_source, chinook_model, outcome_model=None, **kwargs):
        self.continuation_admission = require_parent(kwargs.get('seed'), parent_checkpoint,
            parent_certificate_raw, parent_review_raw, parent_spec, outcome_model)
        aref, = [v for v in abiomed_model.source_evidence
                 if v.reference == 'research:system-optimization-002/abiomed-sensor/sensor-adapter/1']
        cref, = [v for v in chinook_model.source_evidence
                 if v.reference == 'research:system-optimization-002/chinook-sensor/sensor-adapter/1']
        need(aref.sha256 == sha(Path(abiomed.__file__).read_bytes())
             and cref.sha256 == sha(Path(chinook.__file__).read_bytes()),
             'OUTCOME_BOTH_EXACT_ADOPTED_EVENT_ADAPTER_SOURCES')
        # Same original initializer used by the admitted spring continuation;
        # the explicit parent proof above replaces only creation-time admission.
        abiomed.PriorCertificate.__init__(self, *args, **kwargs)
        self.acodec, self.anative, self.asource = abiomed_codec, abiomed_native, abiomed_source
        self.ccodec, self.cnative, self.csource = chinook_codec, chinook_native, chinook_source
        self.abasis = self.cbasis = None
        self.proof_model = None
        self.chinook_admission = chinook.admit_parent_extension(parent_checkpoint,
            parent_review_raw, cref.sha256, sha(Path(chinook.__file__).read_bytes()))

    def recover(self, **kwargs):
        need(self.proof_model is not None and self.proof_model.proof_mode == MODE
             and kwargs['state']['last_session'] >= self.proof_model.first_affected_session,
             'OUTCOME_ACTUAL_ADMITTED_PROOF_MODEL_BEFORE_RECOVERY')
        result = complete_recover(self, **kwargs)
        need(self.pending is not None and self.pending['schema'] == SCHEMA,
             'OUTCOME_ACTUAL_COMPLETE_PROOF_CAPTURED')
        need(self.pending['comparisons']['input_sha256'] == commitment(kwargs),
             'OUTCOME_COMPLETE_ACTUAL_CALL_INPUT_COMMITMENT')
        frame_copy(kwargs['state'], result[0])
        self.pending.update(proof_mode=MODE, proof_input_sha256=self.proof_model.sha256,
                            complete_recovery_inputs=deepcopy(kwargs))
        if kwargs['state']['last_session'] == chinook.DAY:
            need(self.cbasis is not None, 'OUTCOME_ACTUAL_CHINOOK_EVENT_SELECTION_BOUND')
            self.pending['chinook_event_basis'] = deepcopy(self.cbasis)
        return result
