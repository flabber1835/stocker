"""Private metadata contexts; original registry and all six inputs stay intact."""
from copy import deepcopy
import json
from pathlib import Path
import re

from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_registry_extension import RegistryExtension as WWERegistry
from system_campaign_six_model_preflight import SixModelPreflight
import system_campaign_ordinary_registry as registry
import system_campaign_cash_calendar as cash
import system_campaign_action_preflight as ordinary

FILE = 'system-campaign-q4-cash-registry-extension.json'
STEM = registry.NAMESPACE + 'cash-calendar-q4-2023-q1-2024/1/'


class CashRegistry:
    def __init__(self, driver=Path('/driver')):
        self.driver = Path(driver)
        self.wwe = WWERegistry(self.driver)
        self.value = json.loads((self.driver / FILE).read_bytes())
        need(set(self.value) == {'schema', 'base_registry_sha256', 'required_wwe_extension_sha256', 'groups'}
             and self.value['schema'] == 'research.ordinary-catalog-registry-extension/1'
             and self.value['base_registry_sha256'] == self.wwe.value['base_registry_sha256']
             and sha((self.driver / 'system-campaign-wwe-registry-extension.json').read_bytes())
                 == self.value['required_wwe_extension_sha256']
             and len(self.value['groups']) == 1,
             'Q4_REGISTRY_EXACT_ORIGINAL_AND_WWE_PARENT_GROUPS')
        self.registrations(self.driver)

    def registrations(self, driver=Path('/driver')):
        driver = Path(driver)
        need(driver.resolve() == self.driver.resolve(), 'Q4_REGISTRY_EXACT_DRIVER_ROOT')
        groups = self.wwe.registrations(driver)
        new, = self.value['groups']
        need(set(new) == {'reference_stem', 'catalog_file', 'loader_file', 'private_file', 'overlay_file'}
             and new['reference_stem'] == STEM and new['loader_file'] == 'system_campaign_cash_calendar.py'
             and all(re.fullmatch(r'[a-z0-9_-]+\.(json|py)', new[k]) is not None
                     for k in ('catalog_file', 'loader_file', 'private_file', 'overlay_file')),
             'Q4_REGISTRY_EXACT_SINGLE_CASH_GROUP_AND_SAFE_FILES')
        need(len(groups) < 64 and new['reference_stem'] not in {v['reference_stem'] for v in groups},
             'Q4_REGISTRY_NO_PRIOR_GROUP_OVERRIDE')
        return [*groups, deepcopy(new)]

    def __enter__(self):
        self.wwe.__enter__()
        try:
            need(registry.registrations == self.wwe.registrations,
                 'Q4_REGISTRY_EXPECTED_ACTUAL_WWE_READER')
            registry.registrations = self.registrations
        except BaseException:
            self.wwe.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *args):
        registry.registrations = self.wwe.registrations
        self.wwe.__exit__(*args)


class CashPreflight(SixModelPreflight):
    def __enter__(self):
        from full_system_core import hosted
        hosted()
        need(cash.analyze_new_catalog is ordinary.analyze_new_catalog,
             'Q4_EXPECTED_ORIGINAL_CASH_COLLISION_ENTRY')
        self.cash_original = cash.analyze_new_catalog
        cash.analyze_new_catalog = self.analyze
        return self

    def __exit__(self, *args):
        cash.analyze_new_catalog = self.cash_original
