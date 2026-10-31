"""One declared registry extension in a private hosted worker; old bytes unchanged."""
from copy import deepcopy
import json
from pathlib import Path
import re

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_ordinary_registry as original

FILE = 'system-campaign-wwe-registry-extension.json'


class RegistryExtension:
    def __init__(self, driver=Path('/driver')):
        self.driver = Path(driver)
        self.value = json.loads((self.driver / FILE).read_bytes())
        need(set(self.value) == {'schema', 'base_registry_sha256', 'groups'}
             and self.value['schema'] == 'research.ordinary-catalog-registry-extension/1'
             and sha((self.driver / original.REGISTRY).read_bytes()) == self.value['base_registry_sha256']
             and len(self.value['groups']) == 1,
             'REGISTRY_EXTENSION_EXACT_UNCHANGED_BASE_AND_ONE_GROUP')
        self.old = original.registrations
        groups = self.registrations(self.driver)
        need(len(groups) <= 64, 'REGISTRY_EXTENSION_ORIGINAL_BOUNDED_GROUP_COUNT')

    def registrations(self, driver=Path('/driver')):
        driver = Path(driver)
        need(driver.resolve() == self.driver.resolve()
             and sha((driver / original.REGISTRY).read_bytes()) == self.value['base_registry_sha256'],
             'REGISTRY_EXTENSION_EXACT_ORIGINAL_DRIVER_AND_BYTES')
        old = self.old(driver)
        new, = self.value['groups']
        need(set(new) == {'reference_stem', 'catalog_file', 'loader_file', 'private_file', 'overlay_file'}
             and new['reference_stem'] == original.NAMESPACE + 'wwe-tko/1/'
             and all(re.fullmatch(r'[a-z0-9_-]+\.(json|py)', new[k]) is not None
                     for k in ('catalog_file', 'loader_file', 'private_file', 'overlay_file')),
             'REGISTRY_EXTENSION_DECLARED_SINGLE_WWE_GROUP_AND_SAFE_FILES')
        need(new['reference_stem'] not in {v['reference_stem'] for v in old},
             'REGISTRY_EXTENSION_NO_REDEFINITION_OF_ANY_OLD_GROUP')
        return [*old, deepcopy(new)]

    def __enter__(self):
        from full_system_core import hosted
        from system_campaign_outcome_basis import require_sources
        hosted()
        require_sources()
        need(original.registrations is self.old, 'REGISTRY_EXTENSION_EXPECTED_ORIGINAL_READER')
        original.registrations = self.registrations
        return self

    def __exit__(self, *args):
        original.registrations = self.old
