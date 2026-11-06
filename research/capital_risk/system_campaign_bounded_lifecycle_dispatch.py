"""Explicit bounded-input routes around complete legacy hosted worker entries."""
from contextlib import contextmanager,ExitStack
from types import SimpleNamespace
from pathlib import Path
import json

from full_system_benchmark import need
from seal import sha256_file

HERE=Path(__file__).parent

def source_names():
    import system_campaign_bounded_sensor_runtime_v2 as dova
    import system_campaign_p06_abmd_lifecycle_data as p06
    import system_campaign_p07_abmd_lifecycle as p07
    import system_campaign_p05_batch_runtime as p05
    import system_campaign_p06_abmd_reporting as reporting
    return tuple(sorted(set((Path(__file__).name,*dova.source_names(),*p06.source_names(),*p07.source_names(),*p05.source_names(),*reporting.source_names()))))

def p06_declaration(spec):
    import system_campaign_p06_abmd_lifecycle_data as data
    from system_campaign_financial_partial import validate_root_spec
    validate_root_spec(spec)
    need(data.selected(spec) and spec['measured_closes']==1238 and spec['selected_session']=='2022-11-30'
         and len(spec['repairs'])==8,'BOUNDED_DISPATCH_EXACT_P06_INITIAL_SOURCE_ROOT')
    catalog=data.catalog()
    need(spec['outer_sha256']==catalog['parent_outer_sha256'] and spec['repairs']==catalog['parent_descriptors'],
         'BOUNDED_DISPATCH_P06_FULL_ORIGINAL_INPUT_HISTORY')
    return dict(schema='research.abmd-initial-bounded-runtime-declaration/1',arm='P06',
        root_admission_sha256=spec['root_admission_sha256'],catalog_file=data.CATALOG,catalog_sha256=data.CATALOG_SHA,
        prior_seed_rows=0,original_TRQ_cash_per_share='31.575855485386988',
        original_controller_source_unchanged=True,actual_owned_or_ordered_right_valuation_authorized=False,
        every_reachable_canonical_decision_must_match=True)

def expected_request(original,*,execution_mode,selected_arms):
    import system_campaign_bounded_sensor_runtime_v2 as dova
    import system_campaign_p06_abmd_lifecycle_data as p06
    import system_campaign_p07_abmd_lifecycle as p07
    import system_campaign_abmd_preflight_dispatch as prep
    import system_campaign_bounded_sensor_preparation as dova_prep
    import system_campaign_p05_batch_runtime as p05
    from system_campaign_financial_partial import root_spec
    proxy=SimpleNamespace(expected_request=original,EXECUTION_MODE=execution_mode,SELECTED_ARMS=selected_arms)
    with dova.request_context(proxy):result=proxy.expected_request()
    financial=execution_mode=='OWN_ADMITTED_FINANCIAL_CONTINUATION'
    declarations={}
    for arm in selected_arms:
        spec=root_spec(arm)
        if financial and p06.selected(spec):declarations[arm]=p06_declaration(spec)
        elif financial and arm=='P07' and p07.selected(spec,dict(execution_mode=execution_mode,selected_abmd_bounded_inputs={'P07':p07.declaration(spec)})):
            declarations[arm]=p07.declaration(spec)
        if financial and arm in declarations:
            preparation=prep.declaration(spec)
            if preparation is not None:result['selected_abmd_preparations'][arm]=preparation
        if financial and dova.initial(spec):
            result['selected_bounded_preparations'][arm]=dict(catalog_sha256=dova_prep.CATALOG_SHA,financial_sessions_advanced=0,checkpoint_adopted=False)
        if financial and (arm in declarations or dova.selected(spec)):
            result['arm_inputs'][arm]['new_factual_overlay']=(dova.initial(spec) or p06.selected(spec)
                or (arm=='P07' and spec.get('root_admission_sha256')==p07.INITIAL_ROOT))
    result['selected_abmd_bounded_inputs']=declarations
    result['selected_neutral_cash_batches']={}
    for arm in selected_arms:
        spec=root_spec(arm)
        if financial and p05.family(spec):
            need(p05.initial(spec),'BOUNDED_DISPATCH_NEW_P05_RETAINED_FINANCIAL_PHASE_REQUIRES_SEPARATE_QUALIFICATION')
            result['selected_neutral_cash_batches'][arm]=p05.declaration(spec)
    for name in source_names():
        pin=sha256_file(HERE/name)
        need(name not in result['sources'] or result['sources'][name]==pin,'BOUNDED_DISPATCH_NO_SOURCE_PIN_REPLACEMENT')
        result['sources'][name]=pin
    import system_campaign_p06_abmd_reporting as reporting
    return reporting.expected_request(lambda:result,execution_mode=execution_mode,selected_arms=selected_arms,
        target_lookup=lambda arm:json.loads((HERE/'system-campaign-financial-partials.json').read_bytes())['arms'][arm])

@contextmanager
def entry(module,spec,*,mode,evidence=None,out=None):
    from full_system_core import hosted
    hosted()
    import system_campaign_bounded_sensor_runtime_v2 as dova
    import system_campaign_p06_abmd_lifecycle as p06
    import system_campaign_p06_abmd_lifecycle_data as p06_data
    import system_campaign_p07_abmd_lifecycle as p07
    import system_campaign_p05_batch_runtime as p05
    import system_campaign_p06_abmd_reporting as reporting
    need(mode in ('preflight','economic','review'),'BOUNDED_DISPATCH_EXPLICIT_LEGACY_MODE')
    with ExitStack() as stack:
        if dova.selected(spec):stack.enter_context(dova.entry_context(module,spec))
        if p06_data.selected(spec):
            stack.enter_context(p06.entry_context(spec,evidence_root=evidence if mode=='review' else None,
                out=out if mode=='review' else None))
        if p07.selected(spec):stack.enter_context(p07.entry(spec))
        if p05.family(spec):stack.enter_context(p05.entry_context(module,spec))
        if mode=='preflight' and reporting.selected(spec):
            stack.enter_context(reporting.entry_context(spec,old=Path('/old'),out=out or Path('/out'),
                request=json.loads((HERE/'system-campaign-factual-request.json').read_bytes())))
        old_overlay=module.factual_overlay_needed
        selected=dova.selected(spec) or p06_data.selected(spec) or p07.selected(spec)
        if selected:
            initial=(dova.initial(spec) or p06_data.selected(spec)
                or (spec.get('arm')=='P07' and spec.get('root_admission_sha256')==p07.INITIAL_ROOT))
            module.factual_overlay_needed=lambda target:initial if target==spec else old_overlay(target)
        try:yield
        finally:module.factual_overlay_needed=old_overlay
