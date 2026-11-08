"""Explicit CAP staging closure for the independently selected ABMD preparation."""
from system_campaign_abmd_bounded_catalog import CASES,COMMON,PRIMARY,PREPARATION

def source_names(arms=('P06','P07')):
    names=set(COMMON)|{PRIMARY,PREPARATION,'system_campaign_abmd_bounded_preparation.py',
        'system_campaign_abmd_bounded_sources.py','system_campaign_bounded_sensor_preparation.py',
        'system-campaign-uncertainty-integration-request.json'}
    for arm in arms:
        if arm not in CASES:raise ValueError('ABMD_ONLY_QUALIFIED_PREPARATION_ARMS')
        names.update(CASES[arm]['bindings']);names.add(arm+'-own1238-ABMD-bounded-catalog-v2.json')
    return tuple(sorted(names))
