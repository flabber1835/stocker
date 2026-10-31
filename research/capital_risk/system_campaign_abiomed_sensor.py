"""Third unowned event on the unchanged, seeded joint interval machine."""
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
import system_campaign_uncertainty_context as inherited
from system_campaign_uncertainty_math import Interval
from system_campaign_zogenix_sensor import SensorCertificate as PriorCertificate, isolated_function
from system_campaign_abiomed_input import SID, NATIVE, DAY, require_no_position
from system_campaign_abiomed_facts import CONTRACT


def check_inherited():
    contract = json.loads((Path(__file__).parent / CONTRACT).read_bytes())
    for name, expected in contract['inherited_sources'].items():
        need(hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() == expected,
             'ABIOMED_UNCHANGED_QUALIFIED_INHERITED_SOURCE')


material = isolated_function(inherited.return_material, SID=SID)
inherited_witness = isolated_function(inherited.SensorCertificate.witness, return_material=material)


class SensorCertificate(PriorCertificate):
    witness = inherited_witness

    def __init__(self, *args, abiomed_codec, abiomed_native, abiomed_source, **kwargs):
        super().__init__(*args, **kwargs)
        need(self.seed and self.seed[-1]['session'] < NATIVE,
             'ABIOMED_PRIOR_COMMITTED_PROOF_SEED_REQUIRED')
        self.acodec, self.anative, self.asource = abiomed_codec, abiomed_native, abiomed_source
        self.abasis = None

    def __enter__(self):
        check_inherited()
        super().__enter__()
        need(self.math is not None, 'ABIOMED_OLDER_UNCERTAINTIES_NOT_RESET')
        return self

    def relevant(self, state, packet):
        value = super().relevant(state, packet)
        if packet.day == DAY:
            return {**(value or dict(terminal=[], spinoff=[])),
                    'research_abiomed_sensor': dict(security_id=SID, range=[380., 415.])}
        return value

    def values(self, *, prior, published):
        self.abasis = None
        if published.session != DAY:
            return super().values(prior=prior, published=published)
        self.event_bounds = None
        require_no_position(prior)
        need(self.acodec.objects, 'ABIOMED_COMMITTED_TYPED_INPUT_REQUIRED')
        terms = [term for term in published.terminal_events if term.security_id == SID]
        need(len(terms) == 1 and asdict(terms[0]) == asdict(replace(self.anative, session=DAY))
             and not terms[0].completeness(0)[0], 'ABIOMED_ACTUAL_INCOMPLETE_EFFECTIVE_TERM')
        if SID not in prior.median5['selected']:
            self.abasis = dict(session=DAY, security_id=SID, selected=False)
            return self.original_values(prior=prior, published=published)
        anchor = prior.feed['series'][SID]['signal_basis_anchor']
        need(anchor[0] == prior.last_processed_session, 'ABIOMED_EXACT_PRIOR_PRICE_ANCHOR')
        raw, signal = map(lambda value: Fraction(str(value)), anchor[1:])
        bars = [bar for bar in published.bars if bar.security_id == SID]
        need(not bars and self.asource['session'] == DAY and self.asource['security_id'] == SID
             and self.asource['source_quote_present'] is False and self.asource['split_ratio'] == '1',
             'ABIOMED_EXACT_EVENT_SOURCE_QUOTE_ABSENCE_AND_SPLIT')
        need(raw > 0 and signal > 0, 'ABIOMED_POSITIVE_PRICE_ANCHOR')
        bounds = Interval(float(380 * signal / raw), float(415 * signal / raw)).normal_positive()
        other = replace(published, terminal_events=tuple(term for term in published.terminal_events
                                                        if term.security_id != SID))
        result = self.original_values(prior=prior, published=other)
        need(SID not in result, 'ABIOMED_NO_DUPLICATE_SENSOR_CONSIDERATION')
        result[SID] = bounds.lo
        self.event_bounds = bounds
        self.abasis = dict(session=DAY, security_id=SID, selected=True,
            prior_session=prior.last_processed_session, raw_anchor=str(anchor[1]),
            signal_anchor=str(anchor[2]), split='1',
            source_term_sha256=inherited.digest(asdict(terms[0])),
            source_event_sha256=inherited.digest(self.asource), signal_consideration_interval=bounds.pair())
        return result

    def recover(self, **kwargs):
        result = super().recover(**kwargs)
        if kwargs['state']['last_session'] == DAY:
            need(self.abasis is not None, 'ABIOMED_ACTUAL_EVENT_SELECTION_BOUND')
            self.pending['abiomed_event_basis'] = self.abasis
        return result

    def advance(self, run, published):
        if published.session >= NATIVE:
            require_no_position(run.state)
        result = super().advance(run, published)
        if published.session >= NATIVE:
            require_no_position(result.state)
        return result
