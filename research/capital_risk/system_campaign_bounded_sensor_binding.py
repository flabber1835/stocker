"""Event data binding to the original B19 interval certificate and cloud oracle."""
from copy import deepcopy
from dataclasses import asdict, replace
from fractions import Fraction
import hashlib
from math import isfinite
from pathlib import Path
from types import FunctionType

from system_campaign_bounded_sensor_input import Event, need, digest, require_no_position

INHERITED = {
    'system_campaign_financial_branches.py': 'b19a93be7b6887c1b92a5a676fefecc5477addfaf99efcf1f18f45eafb6140ef',
    'system_campaign_uncertainty_context.py': 'b9a51977d6456c5684564f74927d2a5585db2208156269c077b9d35eb8373610',
    'system_campaign_uncertainty_math.py': 'a53a3a7b463659eb3788923d504c402a2edd183a3922f20abe51c55dcd303213',
}


def verify_inherited(root):
    for name, expected in INHERITED.items():
        need(hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() == expected,
             'UNCHANGED_INHERITED_SOURCE:' + name)


def bind_function(function, **bindings):
    need(function.__closure__ is None, 'NO_HIDDEN_INHERITED_CLOSURE')
    result = FunctionType(function.__code__, dict(function.__globals__, **bindings),
                          function.__name__, function.__defaults__)
    result.__kwdefaults__ = function.__kwdefaults__
    need(result.__code__ is function.__code__, 'EXACT_INHERITED_CODE_OBJECT')
    return result


def basis(prior, published, event, source, native):
    """Bind legal endpoints to actual raw/signal/split inputs, never a cash book."""
    Event.model_validate(event)
    sid, day = event['security_id'], event['effective_session']
    need(published.session == day and prior.last_processed_session == event['prior_session'], 'ACTUAL_EVENT_CLOCK')
    require_no_position(prior, sid)
    terms = [t for t in published.terminal_events if t.security_id == sid]
    need(len(terms) == 1 and asdict(terms[0]) == asdict(replace(native, session=day))
         and not terms[0].completeness(0)[0] and terms[0].cash_per_share is None,
         'ACTUAL_INCOMPLETE_EVENT_TERM')
    bars = [b for b in published.bars if b.security_id == sid]
    need(len(bars) <= 1 and (not bars or bars[0].session == day), 'ACTUAL_EVENT_SOURCE_BAR')
    split = Fraction(str(bars[0].split_ratio)) if bars else Fraction(1)
    need(source['session'] == day and source['security_id'] == sid
         and type(source['source_quote_present']) is bool and bool(bars) is source['source_quote_present']
         and split == Fraction(source['split_ratio']) and split > 0, 'EXACT_SOURCE_QUOTE_AND_SPLIT')
    selected = sid in prior.median5['selected']
    result = dict(session=day, security_id=sid, selected=selected,
                  event_contract_sha256=digest(event), source_term_sha256=digest(asdict(terms[0])),
                  source_event_sha256=digest(source))
    if not selected:
        return result, None
    anchor = prior.feed['series'][sid]['signal_basis_anchor']
    need(anchor[0] == prior.last_processed_session, 'EXACT_PRIOR_RAW_SIGNAL_ANCHOR')
    raw, signal = (Fraction(str(v)) for v in anchor[1:])
    need(raw > 0 and signal > 0, 'POSITIVE_RAW_SIGNAL_ANCHOR')
    cash = Fraction(event['upfront_cash_per_share'])
    endpoints = [(cash + Fraction(event[k])) * split * signal / raw
                 for k in ('right_lower_per_share', 'right_upper_per_share')]
    interval = [float(v) for v in endpoints]
    need(all(isfinite(v) for v in interval) and 0 < interval[0] < interval[1], 'FINITE_ORDERED_SIGNAL_BOUNDS')
    result.update(prior_session=prior.last_processed_session, raw_anchor=str(anchor[1]),
                  signal_anchor=str(anchor[2]), split=str(split), signal_consideration_interval=interval)
    return result, interval


def certificate_class(event, source, codec, native, *, inherited_root):
    """Hosted-only adapter; B19 retains recovery, seed, append and proof identity."""
    from full_system_core import hosted
    hosted()
    verify_inherited(inherited_root)
    import system_campaign_financial_branches as b
    import system_campaign_uncertainty_context as base
    from system_campaign_uncertainty_math import Interval

    Event.model_validate(event)
    need(codec.event == event and digest(asdict(native)) == event['native_term_sha256'], 'EXACT_TYPED_CODEC_AND_NATIVE')
    event, source = deepcopy(event), deepcopy(source)
    sid, day = event['security_id'], event['effective_session']
    material = bind_function(base.return_material, SID=sid)
    witness = bind_function(base.SensorCertificate.witness, return_material=material)

    class BoundedCertificate(b.Certificate):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            need(self.seed and self.seed[-1]['session'] < event['native_session'], 'PRIOR_COMMITTED_B19_SEED')
            self.bounded_basis = None

        def relevant(self, state, packet):
            original = super().relevant(state, packet)
            if packet.day != day:
                return original
            return {**(original or dict(terminal=[], spinoff=[])),
                    'research_bounded_contingent_sensor': dict(security_id=sid, event_contract_sha256=digest(event))}

        def values(self, *, prior, published):
            self.bounded_basis = None
            if published.session != day:
                return super().values(prior=prior, published=published)
            need(codec.objects and all(v.event.model_dump() == event for v in codec.objects), 'COMMITTED_TYPED_INPUT_REQUIRED')
            self.event_bounds = None
            self.bounded_basis, interval = basis(prior, published, event, source, native)
            if interval is None:
                return self.original_values(prior=prior, published=published)
            other = replace(published, terminal_events=tuple(t for t in published.terminal_events if t.security_id != sid))
            result = self.original_values(prior=prior, published=other)
            need(sid not in result, 'NO_DUPLICATE_SENSOR_CONSIDERATION')
            self.event_bounds = Interval(*interval).normal_positive()
            result[sid] = self.event_bounds.lo
            return result

        def recover(self, **kwargs):
            result = super().recover(**kwargs)
            if kwargs['state']['last_session'] == day:
                need(self.bounded_basis is not None, 'ACTUAL_EVENT_BASIS_REQUIRED')
                self.pending['bounded_event_basis'] = deepcopy(self.bounded_basis)
            return result

        def advance(self, run, published):
            if published.session >= event['native_session']:
                require_no_position(run.state, sid)
            result = super().advance(run, published)
            if published.session >= event['native_session']:
                require_no_position(result.state, sid)
            return result

    BoundedCertificate.witness = witness
    need(BoundedCertificate.recover.__closure__ is not None
         and BoundedCertificate.append is b.Certificate.append
         and witness.__code__ is base.SensorCertificate.witness.__code__
         and material.__code__ is base.return_material.__code__, 'ORIGINAL_B19_METHOD_COMPOSITION')
    return BoundedCertificate
