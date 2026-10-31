"""A second unowned sensor event on the unchanged, seeded interval machine."""
from dataclasses import asdict,replace
from fractions import Fraction
import hashlib,json
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
import system_campaign_uncertainty_context as inherited
from system_campaign_uncertainty_math import Interval
from system_campaign_zogenix_input import SID,NATIVE,DAY,require_no_position
from system_campaign_zogenix_facts import CONTRACT


def check_inherited():
    c=json.loads((Path(__file__).parent/CONTRACT).read_bytes())
    for name,expected in c['inherited_sources'].items():
        need(hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()==expected,
             'ZOGENIX_UNCHANGED_QUALIFIED_INHERITED_SOURCE')


def isolated_function(fn,**bindings):
    """Reuse identical code in a private namespace, with no module mutation."""
    need(fn.__closure__ is None,'ZOGENIX_NO_HIDDEN_INHERITED_CLOSURE')
    result=FunctionType(fn.__code__,dict(fn.__globals__,**bindings),fn.__name__,fn.__defaults__)
    result.__kwdefaults__=fn.__kwdefaults__
    need(result.__code__ is fn.__code__,'ZOGENIX_EXACT_INHERITED_CODE_OBJECT')
    return result


material=isolated_function(inherited.return_material,SID=SID)
inherited_witness=isolated_function(inherited.SensorCertificate.witness,return_material=material)


class SensorCertificate(inherited.SensorCertificate):
    witness=inherited_witness

    def __init__(self,*args,zogenix_codec,zogenix_native,zogenix_source,**kwargs):
        super().__init__(*args,**kwargs)
        need(self.seed and self.seed[-1]['session']>='2022-02-28','ZOGENIX_EXACT_PRIOR_PROOF_SEED_REQUIRED')
        self.zcodec,self.znative,self.zsource=zogenix_codec,zogenix_native,zogenix_source
        self.zbasis=None

    def __enter__(self):
        check_inherited();super().__enter__()
        need(self.math is not None,'ZOGENIX_OLD_UNCERTAINTY_NOT_RESET')
        return self

    def relevant(self,state,packet):
        value=super().relevant(state,packet)
        if packet.day==DAY:
            return {**(value or dict(terminal=[],spinoff=[])),
                    'research_zogenix_sensor':dict(security_id=SID,range=[26.,28.])}
        return value

    def values(self,*,prior,published):
        self.zbasis=None
        if published.session!=DAY:return super().values(prior=prior,published=published)
        self.event_bounds=None;require_no_position(prior)
        need(self.zcodec.objects,'ZOGENIX_COMMITTED_TYPED_INPUT_REQUIRED')
        terms=[t for t in published.terminal_events if t.security_id==SID]
        need(len(terms)==1 and asdict(terms[0])==asdict(replace(self.znative,session=DAY))
             and not terms[0].completeness(0)[0],'ZOGENIX_ACTUAL_INCOMPLETE_EFFECTIVE_TERM')
        if SID not in prior.median5['selected']:
            self.zbasis=dict(session=DAY,security_id=SID,selected=False)
            return self.original_values(prior=prior,published=published)
        anchor=prior.feed['series'][SID]['signal_basis_anchor']
        need(anchor[0]==prior.last_processed_session,'ZOGENIX_EXACT_PRIOR_PRICE_ANCHOR')
        raw,signal=map(lambda v:Fraction(str(v)),anchor[1:])
        bars=[b for b in published.bars if b.security_id==SID]
        need(not bars and self.zsource['session']==DAY and self.zsource['security_id']==SID
             and self.zsource['source_quote_present'] is False and self.zsource['split_ratio']=='1',
             'ZOGENIX_EXACT_EVENT_SOURCE_QUOTE_ABSENCE_AND_SPLIT')
        need(raw>0 and signal>0,'ZOGENIX_POSITIVE_PRICE_ANCHOR')
        bounds=Interval(float(26*signal/raw),float(28*signal/raw)).normal_positive()
        other=replace(published,terminal_events=tuple(t for t in published.terminal_events if t.security_id!=SID))
        result=self.original_values(prior=prior,published=other)
        need(SID not in result,'ZOGENIX_NO_DUPLICATE_SENSOR_CONSIDERATION')
        result[SID]=bounds.lo;self.event_bounds=bounds
        self.zbasis=dict(session=DAY,security_id=SID,selected=True,prior_session=prior.last_processed_session,
            raw_anchor=str(anchor[1]),signal_anchor=str(anchor[2]),split='1',
            source_term_sha256=inherited.digest(asdict(terms[0])),source_event_sha256=inherited.digest(self.zsource),
            signal_consideration_interval=bounds.pair())
        return result

    def recover(self,**kwargs):
        result=super().recover(**kwargs)
        if kwargs['state']['last_session']==DAY:
            need(self.zbasis is not None,'ZOGENIX_ACTUAL_EVENT_SELECTION_BOUND')
            self.pending['additional_event_basis']=self.zbasis
        return result

    def advance(self,run,published):
        if published.session>=NATIVE:require_no_position(run.state)
        result=super().advance(run,published)
        if published.session>=NATIVE:require_no_position(result.state)
        return result
