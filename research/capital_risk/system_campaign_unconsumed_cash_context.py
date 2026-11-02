"""One appended ordinary cash registration; all eight retained models stay active."""
from copy import deepcopy
import json
from pathlib import Path
import re

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_q4_cash_context import CashRegistry as PriorRegistry
from system_campaign_pxd_basis import EightModelPreflight
import system_campaign_cash_calendar as cash
import system_campaign_action_preflight as ordinary
import system_campaign_ordinary_registry as registry

FILE = 'system-campaign-unconsumed2024-cash-registry-extension.json'
STEM = registry.NAMESPACE + 'cash-calendar-unconsumed2024/1/'


class CashRegistry:
    def __init__(self, driver=Path('/driver')):
        self.driver = Path(driver)
        self.prior = PriorRegistry(self.driver)
        self.value = json.loads((self.driver / FILE).read_bytes())
        need(set(self.value) == {'schema', 'required_q4_extension_sha256', 'groups'}
             and self.value['schema'] == 'research.ordinary-catalog-registry-extension/1'
             and self.value['required_q4_extension_sha256']
                 == sha((self.driver / 'system-campaign-q4-cash-registry-extension.json').read_bytes())
             and len(self.value['groups']) == 1, 'UNCONSUMED_CASH_EXACT_PRIOR_REGISTRY_AND_ONE_GROUP')
        self.registrations(self.driver)

    def registrations(self, driver=Path('/driver')):
        driver = Path(driver)
        need(driver.resolve() == self.driver.resolve(), 'UNCONSUMED_CASH_EXACT_DRIVER_ROOT')
        groups = self.prior.registrations(driver)
        new, = self.value['groups']
        need(set(new) == {'reference_stem', 'catalog_file', 'loader_file', 'private_file', 'overlay_file'}
             and new['reference_stem'] == STEM and new['loader_file'] == 'system_campaign_cash_calendar.py'
             and all(re.fullmatch(r'[a-z0-9_-]+\.(json|py)', new[k]) is not None
                     for k in ('catalog_file', 'loader_file', 'private_file', 'overlay_file')),
             'UNCONSUMED_CASH_EXACT_ORIGINAL_LOADER_AND_SAFE_FILES')
        need(len(groups) < 64 and new['reference_stem'] not in {v['reference_stem'] for v in groups},
             'UNCONSUMED_CASH_NO_EXISTING_REGISTRY_OVERRIDE')
        return [*groups, deepcopy(new)]

    def __enter__(self):
        self.prior.__enter__()
        try:
            need(registry.registrations == self.prior.registrations,
                 'UNCONSUMED_CASH_EXPECTED_ACTUAL_PRIOR_REGISTRY')
            registry.registrations = self.registrations
        except BaseException:
            self.prior.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        registry.registrations = self.prior.registrations
        self.prior.__exit__(*args)


class CashPreflight(EightModelPreflight):
    def __enter__(self):
        from full_system_core import hosted
        hosted()
        need(cash.analyze_new_catalog is ordinary.analyze_new_catalog,
             'UNCONSUMED_CASH_EXPECTED_ORIGINAL_COLLISION_ENTRY')
        self.cash_original = cash.analyze_new_catalog
        cash.analyze_new_catalog = self.analyze
        return self

    def __exit__(self, *args):
        cash.analyze_new_catalog = self.cash_original
