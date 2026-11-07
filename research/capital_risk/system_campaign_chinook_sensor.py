"""Fourth unowned event on the unchanged, seeded joint interval machine."""
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
import system_campaign_uncertainty_context as inherited
from system_campaign_uncertainty_math import Interval
from system_campaign_spring2023_sensor import SensorCertificate as PriorCertificate
from system_campaign_zogenix_sensor import isolated_function
from system_campaign_chinook_input import SID, NATIVE, DAY, require_no_position
from system_campaign_chinook_facts import CONTRACT


def check_inherited():
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name, expected in contract['inherited_sources'].items():
        need(hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() == expected,
             'CHINOOK_UNCHANGED_QUALIFIED_INHERITED_SOURCE')


def admit_parent_extension(checkpoint, parent_review_raw, model_source_sha256, source_sha256):
    """Additional metadata admission after the exact inherited seed admission."""
    proof = json.loads(parent_review_raw)
    need(proof['checkpoint_sha256'] == checkpoint['sha256']
         and proof['through'] == checkpoint['source_cursor'],
         'CHINOOK_EXACT_PARENT_EXTENSION_PROOF')
    resolution = proof.get('chinook_event_resolution')
    if model_source_sha256 is None:
        need(checkpoint['source_cursor'] < NATIVE and resolution is None,
             'CHINOOK_NEW_INPUT_REQUIRES_UNCONSUMED_CREATION_PARENT')
        mode = 'FIRST_TYPED_INPUT'
    else:
        need(model_source_sha256 == source_sha256
             and proof['every_new_chinook_before_and_after_position_and_intent_checked'] is True
             and (checkpoint['source_cursor'] < DAY or resolution is not None),
             'CHINOOK_EXACT_ADMITTED_POST_EVENT_CONTINUATION')
        mode = 'RETAINED_TYPED_INPUT'
    return dict(mode=mode, parent_checkpoint_sha256=checkpoint['sha256'],
        through=checkpoint['source_cursor'], prior_event_resolution=resolution,
        original_joint_math_not_reset=True)


material = isolated_function(inherited.return_material, SID=SID)
inherited_witness = isolated_function(inherited.SensorCertificate.witness, return_material=material)


class SensorCertificate(PriorCertificate):
    witness = inherited_witness

    def __init__(self, *args, chinook_codec, chinook_native, chinook_source,
                 chinook_model=None, **kwargs):
        checkpoint = kwargs['parent_checkpoint']
        parent_raw = kwargs['parent_review_raw']
        super().__init__(*args, **kwargs)
        reference_sha = None
        if chinook_model is not None:
            reference, = [v for v in chinook_model.source_evidence
                          if v.reference == 'research:system-optimization-002/chinook-sensor/sensor-adapter/1']
            reference_sha = reference.sha256
        self.chinook_admission = admit_parent_extension(checkpoint, parent_raw,
            reference_sha, hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        self.ccodec, self.cnative, self.csource = chinook_codec, chinook_native, chinook_source
        self.cbasis = None

    def __enter__(self):
        check_inherited()
        super().__enter__()
        need(self.math is not None, 'CHINOOK_OLDER_UNCERTAINTIES_NOT_RESET')
        return self

    def relevant(self, state, packet):
        value = super().relevant(state, packet)
        if packet.day == DAY:
            return {**(value or dict(terminal=[], spinoff=[])),
                    'research_chinook_sensor': dict(security_id=SID, range=[40., 44.])}
        return value

    def values(self, *, prior, published):
        self.cbasis = None
        if published.session != DAY:
            return super().values(prior=prior, published=published)
        self.event_bounds = None
        require_no_position(prior)
        need(self.ccodec.objects, 'CHINOOK_COMMITTED_TYPED_INPUT_REQUIRED')
        terms = [term for term in published.terminal_events if term.security_id == SID]
        need(len(terms) == 1 and asdict(terms[0]) == asdict(replace(self.cnative, session=DAY))
             and not terms[0].completeness(0)[0], 'CHINOOK_ACTUAL_INCOMPLETE_EFFECTIVE_TERM')
        if SID not in prior.median5['selected']:
            self.cbasis = dict(session=DAY, security_id=SID, selected=False)
            return self.original_values(prior=prior, published=published)
        anchor = prior.feed['series'][SID]['signal_basis_anchor']
        need(anchor[0] == prior.last_processed_session, 'CHINOOK_EXACT_PRIOR_PRICE_ANCHOR')
        raw, signal = map(lambda value: Fraction(str(value)), anchor[1:])
        bars = [bar for bar in published.bars if bar.security_id == SID]
        need(not bars and self.csource['session'] == DAY and self.csource['security_id'] == SID
             and self.csource['source_quote_present'] is False and self.csource['split_ratio'] == '1',
             'CHINOOK_EXACT_EVENT_SOURCE_QUOTE_ABSENCE_AND_SPLIT')
        need(raw > 0 and signal > 0, 'CHINOOK_POSITIVE_PRICE_ANCHOR')
        bounds = Interval(float(40 * signal / raw), float(44 * signal / raw)).normal_positive()
        other = replace(published, terminal_events=tuple(term for term in published.terminal_events
                                                        if term.security_id != SID))
        result = self.original_values(prior=prior, published=other)
        need(SID not in result, 'CHINOOK_NO_DUPLICATE_SENSOR_CONSIDERATION')
        result[SID] = bounds.lo
        self.event_bounds = bounds
        self.cbasis = dict(session=DAY, security_id=SID, selected=True,
            prior_session=prior.last_processed_session, raw_anchor=str(anchor[1]),
            signal_anchor=str(anchor[2]), split='1',
            source_term_sha256=inherited.digest(asdict(terms[0])),
            source_event_sha256=inherited.digest(self.csource), signal_consideration_interval=bounds.pair())
        return result

    def recover(self, **kwargs):
        result = super().recover(**kwargs)
        if kwargs['state']['last_session'] == DAY:
            need(self.cbasis is not None, 'CHINOOK_ACTUAL_EVENT_SELECTION_BOUND')
            self.pending['chinook_event_basis'] = self.cbasis
        return result

    def advance(self, run, published):
        if published.session >= NATIVE:
            require_no_position(run.state)
        result = super().advance(run, published)
        if published.session >= NATIVE:
            require_no_position(result.state)
        return result
