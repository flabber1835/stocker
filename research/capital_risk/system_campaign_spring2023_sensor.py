"""Admit an already resolved, exact parent seed; all numerical methods inherited."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_abiomed_sensor as original

REFERENCE = 'research:system-optimization-002/abiomed-sensor/sensor-adapter/1'


def require_committed_parent(seed, checkpoint, certificate_raw, review_raw, spec):
    proof = json.loads(review_raw)
    need(sha(review_raw) == spec['interval_review_sha256']
         and proof['checkpoint_sha256'] == checkpoint['sha256'] == spec['outer_sha256']
         and proof['through'] == checkpoint['source_cursor'] == spec['selected_session']
         and checkpoint['source_cursor'] >= original.DAY,
         'SPRING2023_EXACT_AUTHENTICATED_POST_EVENT_PARENT')
    flags = ('every_actual_comparison_invariant', 'every_committed_watch_and_financial_row_bound',
             'every_discrete_controller_state_equal', 'every_new_abiomed_before_and_after_position_and_intent_checked')
    need(all(proof[k] is True for k in flags) and proof['abiomed_event_resolution'] is not None,
         'SPRING2023_ADMITTED_PARENT_HAS_ALL_INVARIANTS_AND_ABIOMED_RESOLUTION')
    lines = certificate_raw.splitlines(keepends=True)
    values = [json.loads(line) for line in lines]
    selected = [(line, value) for line, value in zip(lines, values)
                if value['session'] <= checkpoint['source_cursor']]
    prefix = b''.join(line for line, _ in selected)
    committed = [value for _, value in selected]
    need(certificate_raw.startswith(prefix) and seed == committed and seed
         and len(seed) == proof['rows'] == spec['parent_certificate_rows']
         and seed[-1]['session'] == checkpoint['source_cursor'],
         'SPRING2023_EXACT_COMPLETE_COMMITTED_PARENT_SEED_NO_UNSENT_ROWS')
    dates = [row['session'] for row in seed]
    need(dates == sorted(set(dates)), 'SPRING2023_PARENT_SEED_ORDER_AND_UNIQUENESS')
    return dict(parent_checkpoint_sha256=checkpoint['sha256'], through=checkpoint['source_cursor'],
                rows=len(seed), committed_bytes=len(prefix), committed_sha256=sha(prefix),
                full_parent_certificate_sha256=sha(certificate_raw),
                parent_review_sha256=sha(review_raw), original_math_not_reset=True)


class SensorCertificate(original.SensorCertificate):
    def __init__(self, *args, abiomed_codec, abiomed_native, abiomed_source,
                 parent_checkpoint, parent_certificate_raw, parent_review_raw,
                 parent_spec, abiomed_model, **kwargs):
        self.continuation_admission = require_committed_parent(kwargs.get('seed'), parent_checkpoint,
            parent_certificate_raw, parent_review_raw, parent_spec)
        reference, = [v for v in abiomed_model.source_evidence if v.reference == REFERENCE]
        need(sha(Path(original.__file__).read_bytes()) == reference.sha256,
             'SPRING2023_EXACT_ADOPTED_ORIGINAL_SENSOR_CLASS_SOURCE')
        # The original ABMD initializer calls this exact prior initializer;
        # only its pre-event creation admission is replaced by the explicit
        # post-event parent proof above. No numeric/controller method changes.
        original.PriorCertificate.__init__(self, *args, **kwargs)
        need(self.seed == kwargs['seed'], 'SPRING2023_ORIGINAL_PRIOR_RETAINS_EXACT_SEED')
        self.acodec, self.anative, self.asource = abiomed_codec, abiomed_native, abiomed_source
        self.abasis = None
