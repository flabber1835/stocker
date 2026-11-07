"""Initial ABMD uncertainty proof; no prior certificate or representative cash book."""
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
from system_campaign_bounded_sensor_input import Event,need,digest,require_no_position
from system_campaign_bounded_sensor_binding import verify_inherited,bind_function,basis
from system_campaign_abmd_bounded_catalog import event as exact_event,SID

def seed_reader(*,inherited_root):
    verify_inherited(inherited_root)
    import system_campaign_financial_branches as branches
    return bind_function(branches.seed,DAY='2022-12-22')

def certificate_class(event,source,codec,native,*,inherited_root):
    from full_system_core import hosted
    hosted()
    verify_inherited(inherited_root)
    import system_campaign_financial_branches as b
    import system_campaign_uncertainty_context as base
    from system_campaign_uncertainty_math import Interval,RollingWitnessBounds
    event=Event.model_validate(event).model_dump();event,source=deepcopy(event),deepcopy(source)
    need(event==exact_event(asdict(native)) and codec.event==event
         and source['session']==event['effective_session'] and source['security_id']==SID
         and source['source_quote_present'] is False and source['raw_event_row'] is None
         and source['raw_prior_row']['session']==event['prior_session']=='2022-12-21',
         'P06_ABMD_EXACT_INITIAL_EVENT_SOURCE_AND_CODEC')
    day=event['effective_session']
    material=bind_function(base.return_material,SID=SID)
    witness=bind_function(base.SensorCertificate.witness,DAY=day,return_material=material)
    recover=bind_function(b.Certificate.recover,DAY=day)
    append=bind_function(b.Certificate.append,DAY=day)

    class InitialABMDCertificate(b.Certificate):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            need(self.seed==[] and self.math is self.pending is None,
                 'P06_ABMD_INITIAL_HAS_NO_PRIOR_B19_SEED')
            self.bounded_basis=None

        def relevant(self,state,packet):
            original=self.original_relevant(state,packet)
            if packet.day!=day:return original
            return {**(original or dict(terminal=[],spinoff=[])),
                'research_bounded_contingent_sensor':dict(security_id=SID,event_contract_sha256=digest(event))}

        def values(self,*,prior,published):
            self.bounded_basis=None;self.event_bounds=None;self.event_basis=None
            if published.session!=day:return self.original_values(prior=prior,published=published)
            need(codec.objects and all(v.event.model_dump()==event for v in codec.objects),
                 'P06_ABMD_COMMITTED_TYPED_INPUT_REQUIRED')
            if SID in prior.median5['selected']:
                anchor=prior.feed['series'][SID]['signal_basis_anchor'];row=source['raw_prior_row']
                need(anchor[0]==row['session']==event['prior_session'] and anchor[1]==float(row['raw_close'])
                     and anchor[2]==float(row['signal_close']),'P06_ABMD_EXACT_FROZEN_PRIOR_RAW_SIGNAL_ANCHOR')
            self.bounded_basis,interval=basis(prior,published,event,source,native)
            self.event_basis=deepcopy(self.bounded_basis)
            if interval is None:return self.original_values(prior=prior,published=published)
            other=replace(published,terminal_events=tuple(t for t in published.terminal_events if t.security_id!=SID))
            result=self.original_values(prior=prior,published=other)
            need(SID not in result,'P06_ABMD_NO_DUPLICATE_SENSOR_CONSIDERATION')
            self.event_bounds=Interval(*interval).normal_positive();result[SID]=self.event_bounds.lo
            return result

        def witness(self,state,**kwargs):
            # The original witness starts only for a selected unresolved name.
            # This separately qualified initial point case has no affected selected name.
            if self.math is None and kwargs['session']==day and SID not in state['selected']:
                need(self.bounded_basis is not None and self.bounded_basis['selected'] is False
                     and self.bounded_basis['session']==day and self.bounded_basis['security_id']==SID
                     and self.bounded_basis['event_contract_sha256']==digest(event)
                     and self.event_bounds is None and SID not in (kwargs.get('terminal_values') or {}),
                     'P06_ABMD_UNSELECTED_POINT_INITIALIZATION_REQUIRES_ACTUAL_EVENT_BASIS')
                self.math=RollingWitnessBounds(state['witness_nav'])
            return witness(self,state,**kwargs)

        def recover(self,**kwargs):
            result=recover(self,**kwargs)
            if kwargs['state']['last_session']==day:
                need(self.bounded_basis is not None and self.pending is not None,'P06_ABMD_ACTUAL_EVENT_PROOF_REQUIRED')
                self.pending['bounded_event_basis']=deepcopy(self.bounded_basis)
            return result

        def advance(self,run,published):
            if published.session>=event['native_session']:require_no_position(run.state,SID)
            result=super().advance(run,published)
            if published.session>=event['native_session']:require_no_position(result.state,SID)
            return result

    InitialABMDCertificate.append=append
    InitialABMDCertificate.original_bound_witness=witness
    InitialABMDCertificate.original_bound_recover=recover
    InitialABMDCertificate.original_bound_material=staticmethod(material)
    need(append.__code__ is b.Certificate.append.__code__ and witness.__code__ is base.SensorCertificate.witness.__code__
         and recover.__code__ is b.Certificate.recover.__code__ and material.__code__ is base.return_material.__code__,
         'P06_ABMD_ORIGINAL_WITNESS_RECOVER_APPEND_AND_MATERIAL_CODE_OBJECTS')
    return InitialABMDCertificate
