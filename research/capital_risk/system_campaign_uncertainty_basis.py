"""Compose exact ordinary action semantics with one validated interval model."""
import json
from copy import deepcopy

from full_system_benchmark import need
from system_campaign_facts import digest, sha
from system_campaign_basis import basis as ordinary_basis
from system_campaign_uncertainty_review import validate_input_commitment


def basis(root, cp):
    validate_input_commitment(root, cp)
    ordinary = [];uncertainty = []
    for descriptor in cp['repairs']:
        raw = (root / 'book/repairs' / descriptor['filename']).read_bytes()
        need(sha(raw) == descriptor['sha256'], 'UNCERTAINTY_BASIS_ALL_RETAINED_BYTES')
        document = json.loads(raw)
        if document['schema'] == 'terminal-repair/1':ordinary.append(descriptor)
        elif document['schema'] == 'research.leadership-uncertainty-input/1':uncertainty.append(document)
        else:raise ValueError('REFUSED_UNCERTAINTY_BASIS_UNDECLARED_SCHEMA')
    need(len(uncertainty) == 1, 'UNCERTAINTY_BASIS_EXACTLY_ONE_MODEL')
    view = {**cp, 'repairs':ordinary}
    factual_hash, factual = ordinary_basis(root, view)
    model_document = deepcopy(uncertainty[0])
    model_document.pop('predecessor_checkpoint_sha256')
    value = dict(schema='research.system-campaign-common-factual-and-uncertainty-basis/1',
        factual_semantics_sha256=factual_hash, factual_semantics=factual,
        model_semantics=model_document, price_or_probability_estimate_selected=False)
    return digest(value), value
