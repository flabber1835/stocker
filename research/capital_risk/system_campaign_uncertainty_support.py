"""Restore the already bound packet contexts, without creating a new book."""
import json
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import FactualInputs, sha
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_alder_date_v2 import AlderDateV2
from system_campaign_p02_continue_run import COMPONENTS, retained_components


def retained(cp, old, out):
    from research.pooled_vacancy_funding.repair import load_repair
    refs = [];descriptor = None
    for item in cp['repairs']:
        path = old / 'book/repairs' / item['filename']
        need(sha(path.read_bytes()) == item['sha256'], 'UNCERTAINTY_EXACT_RETAINED_REPAIR_BYTES')
        value = json.loads(path.read_bytes());refs.extend(value['source_evidence'])
        if any(v['reference'] == 'research:system-optimization-002/alder-terminal-catalog/1'
               for v in value['source_evidence']):
            need(descriptor is None, 'UNCERTAINTY_UNIQUE_ORIGINAL_ALDER_COMPONENT')
            descriptor = item, value
    need(descriptor is not None, 'UNCERTAINTY_ORIGINAL_ALDER_COMPONENT_REQUIRED')
    retained_components(refs, old, out, len(COMPONENTS))
    v1 = FactualInputs('/driver/system-campaign-factual-catalog.json')
    v1.hydrate(out / 'independent-v1-hydration.json')
    spin = DistributionFacts('/driver/system-campaign-distribution-facts.json')
    spin.hydrate(out / 'independent-distribution-hydration.json')
    alder = AlderDateV2('/driver/system-campaign-alder-unresolved-date.json')
    alder.hydrate(out / 'independent-alder-hydration.json')
    for a, b in (('independent-v1-hydration.json', 'hydrated-factual-catalog.json'),
                 ('independent-distribution-hydration.json', 'hydrated-distribution-catalog.json'),
                 ('independent-alder-hydration.json', 'hydrated-alder-unresolved-date.json')):
        need(sha((out / a).read_bytes()) == sha((out / b).read_bytes()),
             'UNCERTAINTY_IDENTICAL_RETAINED_PACKET_HYDRATION')
    item, value = descriptor
    loaded = load_repair(old / 'book/repairs' / item['filename'], resume_session=cp['source_cursor'],
                         predecessor_checkpoint_sha256=value['predecessor_checkpoint_sha256'])
    return v1, spin, alder, loaded
