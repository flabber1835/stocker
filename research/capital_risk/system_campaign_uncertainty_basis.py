"""Compose exact ordinary action semantics with one validated interval model."""
import json
from copy import deepcopy
from pathlib import Path

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_basis import basis as ordinary_basis
from system_campaign_uncertainty_review import validate_input_commitment


def basis(root, cp):
    validate_input_commitment(root, cp)
    ordinary = [];uncertainty = [];additional=[]
    for descriptor in cp['repairs']:
        raw = (root / 'book/repairs' / descriptor['filename']).read_bytes()
        need(sha(raw) == descriptor['sha256'], 'UNCERTAINTY_BASIS_ALL_RETAINED_BYTES')
        document = json.loads(raw)
        if document['schema'] == 'terminal-repair/1':
            ordinary.append(descriptor)
            additional.extend(v for v in document['source_evidence'] if v['reference'].startswith('research:system-optimization-002/medicines-'))
        elif document['schema'] == 'research.leadership-uncertainty-input/1':uncertainty.append(document)
        else:raise ValueError('REFUSED_UNCERTAINTY_BASIS_UNDECLARED_SCHEMA')
    need(len(uncertainty) == 1, 'UNCERTAINTY_BASIS_EXACTLY_ONE_MODEL')
    view = {**cp, 'repairs':ordinary}
    factual_hash, factual = ordinary_basis(root, view)
    if additional:
        from system_campaign_medicines_facts import CATALOG,COMPILER,HYDRATED
        expected={CATALOG:sha((Path('/driver')/'system-campaign-medicines-terminal-facts.json').read_bytes()),
            COMPILER:sha((Path('/driver')/'system_campaign_medicines_facts.py').read_bytes()),
            HYDRATED:sha((root/'hydrated-medicines-terminal-catalog.json').read_bytes())}
        need(len(additional)==3 and {v['reference']:v['sha256'] for v in additional}==expected,
             'UNCERTAINTY_BASIS_EXPLICIT_MEDICINES_FACTUAL_COMMITMENTS')
        factual={**factual,'declared_fact_compilers':{**factual['declared_fact_compilers'],**expected}}
        factual_hash=digest(factual)
    model_document = deepcopy(uncertainty[0])
    model_document.pop('predecessor_checkpoint_sha256')
    value = dict(schema='research.system-campaign-common-factual-and-uncertainty-basis/1',
        factual_semantics_sha256=factual_hash, factual_semantics=factual,
        model_semantics=model_document, price_or_probability_estimate_selected=False)
    return digest(value), value
