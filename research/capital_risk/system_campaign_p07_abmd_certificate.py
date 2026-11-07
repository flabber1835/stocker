"""A third source-bound event on the original joint Zognix/B19 machine."""
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
from system_campaign_bounded_sensor_input import Event,need,digest,require_no_position
from system_campaign_bounded_sensor_binding import basis,bind_function,verify_inherited

SID='1050970006012443443'
NATIVE='2022-12-21'
DAY='2022-12-22'

def extend_joint(Joint,event,source,codec,native,*,witness,interval_class):
    """Pure class composition; tests use explicitly noncanonical joint DTOs."""
    Event.model_validate(event)
    need((event['security_id'],event['native_session'],event['effective_session'],event['prior_session'])==
         (SID,NATIVE,DAY,NATIVE) and event['upfront_cash_per_share']=='380.00'
         and event['right_lower_per_share']=='0' and event['right_upper_per_share']=='35.00',
         'P07_ABMD_EXACT_LEGAL_CLOCK_AND_ENDPOINTS')
    need(codec.event==event and digest(asdict(native))==event['native_term_sha256']
         and source['source_quote_present'] is False and source['split_ratio']=='1'
         and source['session']==DAY and source['security_id']==SID,
         'P07_ABMD_EXACT_COMMITTED_CODEC_NATIVE_AND_ABSENT_EVENT_QUOTE')
    event,source=deepcopy(event),deepcopy(source)
    class ABMD(Joint):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            need(self.seed and self.seed[-1]['session']<NATIVE,'P07_ABMD_ORIGINAL_COMMITTED_SEED_REQUIRED')
            self.bounded_basis=None

        def relevant(self,state,packet):
            previous=super().relevant(state,packet)
            if packet.day!=DAY:return previous
            return {**(previous or dict(terminal=[],spinoff=[])),
                    'research_bounded_contingent_sensor':dict(security_id=SID,event_contract_sha256=digest(event))}

        def values(self,*,prior,published):
            self.bounded_basis=None
            if published.session!=DAY:return super().values(prior=prior,published=published)
            need(codec.objects and all(obj.event.model_dump()==event for obj in codec.objects),
                 'P07_ABMD_ACTUAL_COMMITTED_TYPED_OBJECT_REQUIRED')
            if SID in prior.median5['selected']:
                anchor=prior.feed['series'][SID]['signal_basis_anchor'];row=source['raw_prior_row']
                need(anchor[0]==NATIVE and anchor[1]==float(row['raw_close']) and anchor[2]==float(row['signal_close']),
                     'P07_ABMD_EXACT_ACTUAL_PRIOR_RAW_SIGNAL_ANCHOR')
            self.event_bounds=None
            self.bounded_basis,interval=basis(prior,published,event,source,native)
            if interval is None:return self.original_values(prior=prior,published=published)
            other=replace(published,terminal_events=tuple(t for t in published.terminal_events if t.security_id!=SID))
            result=self.original_values(prior=prior,published=other)
            need(SID not in result,'P07_ABMD_NO_DUPLICATE_SENSOR_CONSIDERATION')
            self.event_bounds=interval_class(*interval).normal_positive()
            result[SID]=self.event_bounds.lo
            return result

        def recover(self,**kwargs):
            result=super().recover(**kwargs)
            if kwargs['state']['last_session']==DAY:
                need(self.bounded_basis is not None,'P07_ABMD_ACTUAL_EVENT_BASIS_REQUIRED')
                self.pending['bounded_event_basis']=deepcopy(self.bounded_basis)
            return result

        def advance(self,run,published):
            if published.session>=NATIVE:require_no_position(run.state,SID)
            result=super().advance(run,published)
            if published.session>=NATIVE:require_no_position(result.state,SID)
            return result
    ABMD.witness=witness
    need(ABMD.__mro__[1] is Joint and ABMD.append is Joint.append,
         'P07_ABMD_ORIGINAL_JOINT_AND_APPEND_RETAINED')
    return ABMD

def certificate_class(event,source,codec,native,*,mixed,inherited_root):
    from full_system_core import hosted
    hosted()
    verify_inherited(inherited_root)
    from system_campaign_p07_abmd_models import plan
    plan()
    import system_campaign_financial_additional_sensor_runtime as legacy
    import system_campaign_uncertainty_context as base
    import system_campaign_financial_branches as branches
    from system_campaign_uncertainty_math import Interval
    Joint=legacy.joint_certificate(mixed)
    material=bind_function(base.return_material,SID=SID,growth=mixed)
    witness=bind_function(base.SensorCertificate.witness,return_material=material)
    ABMD=extend_joint(Joint,event,source,codec,native,witness=witness,interval_class=Interval)
    need(ABMD.append is branches.Certificate.append
         and ABMD.__mro__[2:5]==Joint.__mro__[1:4]
         and witness.__code__ is base.SensorCertificate.witness.__code__
         and material.__code__ is base.return_material.__code__,
         'P07_ABMD_ENTIRE_ORIGINAL_COOPERATIVE_METHOD_CODE_OBJECTS')
    return ABMD
