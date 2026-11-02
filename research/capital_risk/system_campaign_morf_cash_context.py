"""Append one MORF factual registration; preserve all admitted ordinary groups."""
from copy import deepcopy
import json
from pathlib import Path
import re

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_unconsumed_cash_context import CashRegistry as PriorRegistry,CashPreflight
import system_campaign_ordinary_registry as registry

FILE='system-campaign-morf-cash-registry-extension.json'
STEM=registry.NAMESPACE+'cash-calendar-morf-preopen/1/'


class CashRegistry:
    def __init__(self,driver=Path('/driver')):
        self.driver=Path(driver);self.prior=PriorRegistry(self.driver)
        self.value=json.loads((self.driver/FILE).read_bytes())
        need(set(self.value)=={'schema','required_unconsumed_extension_sha256','groups'}
             and self.value['schema']=='research.ordinary-catalog-registry-extension/1'
             and self.value['required_unconsumed_extension_sha256']==sha(
                 (self.driver/'system-campaign-unconsumed2024-cash-registry-extension.json').read_bytes())
             and len(self.value['groups'])==1,'MORF_EXACT_PRIOR_REGISTRY_AND_ONE_FACTUAL_GROUP')
        self.registrations(self.driver)

    def registrations(self,driver=Path('/driver')):
        need(Path(driver).resolve()==self.driver.resolve(),'MORF_EXACT_REGISTRY_DRIVER_ROOT')
        groups=self.prior.registrations(driver);new,=self.value['groups']
        need(set(new)=={'reference_stem','catalog_file','loader_file','private_file','overlay_file'}
             and new['reference_stem']==STEM and new['loader_file']=='system_campaign_cash_calendar.py'
             and all(re.fullmatch(r'[a-z0-9_-]+\.(json|py)',new[k]) is not None
                     for k in ('catalog_file','loader_file','private_file','overlay_file')),
             'MORF_EXACT_ORIGINAL_CASH_LOADER_AND_SAFE_FILES')
        need(not any(g['reference_stem']==new['reference_stem'] for g in groups),
             'MORF_NO_PRIOR_REGISTRATION_OVERRIDE')
        return [*groups,deepcopy(new)]

    def __enter__(self):
        self.prior.__enter__()
        try:
            need(registry.registrations==self.prior.registrations,'MORF_ACTUAL_PRIOR_REGISTRY_ACTIVE')
            registry.registrations=self.registrations
        except BaseException:
            self.prior.__exit__(None,None,None);raise
        return self

    def __exit__(self,*args):
        registry.registrations=self.prior.registrations
        self.prior.__exit__(*args)
