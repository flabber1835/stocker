"""Three explicit future sensor observations on the retained joint proof machine."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction

from full_system_benchmark import need
import system_campaign_uncertainty_context as original
from system_campaign_outcome_sensor import SensorCertificate as ParentCertificate
from system_campaign_remainder_input import digest, require_no_position
from system_campaign_uncertainty_math import Interval
from system_campaign_zogenix_sensor import isolated_function


class SensorCertificate(ParentCertificate):
    def __init__(self, *args, remainder_codec, remainder_payload, **kwargs):
        super().__init__(*args, **kwargs)
        self.rcodec = remainder_codec
        self.rpayload = deepcopy(remainder_payload)
        self.rcases = [v for v in self.rcodec.catalog['cases']
                       if v['treatment'] in ('CVR_RANGE', 'UNOWNED_CLOSING_DAY_CASH_SENSOR')]
        self.rbasis, self.rcase = None, None

    def relevant(self, state, packet):
        value = super().relevant(state, packet)
        cases = [v for v in self.rcodec.catalog['cases']
                 if packet.day in {v['native_session'], v['core_session'], v['sensor_session']}]
        if cases:
            return {**(value or dict(terminal=[], spinoff=[])),
                    'research_remainder_terminal': [dict(security_id=v['security_id'],
                        treatment=v['treatment']) for v in cases]}
        return value

    def values(self, *, prior, published):
        self.rbasis, self.rcase = None, None
        cases = [v for v in self.rcases if v['sensor_session'] == published.session]
        need(len(cases) <= 1, 'REMAINDER_ONLY_QUALIFIED_ONE_EVENT_PER_SESSION')
        if not cases:
            return super().values(prior=prior, published=published)
        case, = cases
        sid = case['security_id']
        require_no_position(prior, sid)
        need(self.rcodec.objects, 'REMAINDER_ACTUAL_TYPED_INPUT_BEFORE_SENSOR')
        terms = [v for v in published.terminal_events if v.security_id == sid]
        if case['treatment'] == 'CVR_RANGE':
            need(len(terms) == 1
                 and digest(asdict(self.rcodec.natives[sid])) == case['native_term_sha256']
                 and asdict(terms[0]) == asdict(replace(self.rcodec.natives[sid], session=published.session))
                 and not terms[0].completeness(0)[0], 'REMAINDER_EXACT_UNPRICED_CVR_TERM')
        else:
            need(not terms and published.session < case['core_session']
                 and case['phase'] == 'LEGAL_CLOSING_INFORMATION_BEFORE_NEXT_EXECUTION_OPEN'
                 and case['public_information_accepted_at'] == '2026-07-24T16:00:24-04:00',
                 'REMAINDER_CLOSE_ONLY_INFORMATION_NOT_EARLY_CORE_SETTLEMENT')
        other = replace(published, terminal_events=tuple(v for v in published.terminal_events
                                                        if v.security_id != sid))
        result = super().values(prior=prior, published=other)
        need(sid not in result, 'REMAINDER_NO_DUPLICATE_SENSOR_VALUE')
        self.rcase = case
        self.rbasis = dict(session=published.session, security_id=sid,
            treatment=case['treatment'], selected=sid in prior.median5['selected'],
            native_term_sha256=case['native_term_sha256'],
            phase=case['phase'], input_sha256=self.rcodec.objects[-1].sha256)
        if sid not in prior.median5['selected']:
            return result
        anchor = prior.feed['series'][sid]['signal_basis_anchor']
        need(anchor[0] == prior.last_processed_session, 'REMAINDER_ACTUAL_PRIOR_RAW_SIGNAL_ANCHOR')
        raw, signal = (Fraction(str(v)) for v in anchor[1:])
        bars = [v for v in published.bars if v.security_id == sid]
        witness = self.rpayload['event_quotes'][case['ticker']]
        need(len(bars) <= 1 and bool(bars) == witness['present']
             and (not bars or bars[0].session == published.session),
             'REMAINDER_FROZEN_EVENT_QUOTE_PRESENCE')
        split = Fraction(str(bars[0].split_ratio)) if bars else Fraction(1)
        need(split == Fraction(witness['split_ratio']) and raw > 0 and signal > 0 and split > 0,
             'REMAINDER_EXACT_POSITIVE_PRICE_AND_SPLIT_BASIS')
        lo, hi = (Fraction(v) for v in case['consideration_bounds'])
        bounds = Interval(float(lo * split * signal / raw),
                          float(hi * split * signal / raw)).normal_positive()
        result[sid] = bounds.lo  # Proof representative; never an owned valuation.
        self.event_bounds = bounds
        self.rbasis.update(prior_session=prior.last_processed_session,
            raw_anchor=str(anchor[1]), signal_anchor=str(anchor[2]), split=str(split),
            source_event_sha256=digest(witness), signal_consideration_interval=bounds.pair(),
            representative_is_not_a_valuation=True)
        return result

    def witness(self, state, **kwargs):
        if self.rcase is None:
            return super().witness(state, **kwargs)
        sid = self.rcase['security_id']
        kwargs = dict(kwargs)
        if self.rcase['treatment'] == 'UNOWNED_CLOSING_DAY_CASH_SENSOR':
            need(kwargs['session'] == self.rcase['sensor_session'], 'REMAINDER_EXACT_SENSOR_CLOSE_SESSION')
            kwargs['terminals'] = tuple(sorted(set(kwargs.get('terminals', ())) | {sid}))
        material = isolated_function(original.return_material, SID=sid)
        witness = isolated_function(original.SensorCertificate.witness, return_material=material)
        return witness(self, state, **kwargs)

    def recover(self, **kwargs):
        result = super().recover(**kwargs)
        need(self.rcodec.objects and self.pending is not None,
             'REMAINDER_EXISTING_COMPLETE_OUTCOME_PROOF_REQUIRED')
        self.pending['remainder_input_sha256'] = self.rcodec.objects[-1].sha256
        if self.rcase is not None:
            need(self.rbasis is not None and self.rbasis['session'] == kwargs['state']['last_session'],
                 'REMAINDER_ACTUAL_EVENT_BASIS_BOUND_TO_COMPLETE_CONTROLLER_CALL')
            self.pending['remainder_event_basis'] = deepcopy(self.rbasis)
        return result

    def advance(self, run, published):
        cases = [v for v in self.rcases if published.session >= v['native_session']]
        for case in cases:
            require_no_position(run.state, case['security_id'])
        result = super().advance(run, published)
        for case in cases:
            require_no_position(result.state, case['security_id'])
        if self.pending is not None:
            self.pending['remainder_unowned_unordered_unentitled'] = [v['security_id'] for v in cases]
        return result
