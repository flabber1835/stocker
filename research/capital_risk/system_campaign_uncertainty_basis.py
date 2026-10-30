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
            additional.extend(v for v in document['source_evidence'] if v['reference'].startswith(('research:system-optimization-002/medicines-','research:system-optimization-002/arqule-','research:system-optimization-002/sprint-','research:system-optimization-002/spring2020-cash-','research:system-optimization-002/autumn2020-cash-')))
        elif document['schema'] == 'research.leadership-uncertainty-input/1':uncertainty.append(document)
        else:raise ValueError('REFUSED_UNCERTAINTY_BASIS_UNDECLARED_SCHEMA')
    need(len(uncertainty) == 1, 'UNCERTAINTY_BASIS_EXACTLY_ONE_MODEL')
    view = {**cp, 'repairs':ordinary}
    factual_hash, factual = ordinary_basis(root, view)
    if additional:
        from system_campaign_medicines_facts import CATALOG as MC,COMPILER as MP,HYDRATED as MH
        from system_campaign_arqule_facts import CATALOG as AC,COMPILER as AP,HYDRATED as AH
        from system_campaign_sprint_facts import CATALOG as SC,COMPILER as SP,HYDRATED as SH
        from system_campaign_spring2020_cash_facts import CATALOG as CC,COMPILER as CP,HYDRATED as CH
        from system_campaign_autumn2020_cash_facts import CATALOG as FC,COMPILER as FP,HYDRATED as FH
        need(all(v['reference'] in {MC,MP,MH,AC,AP,AH,SC,SP,SH,CC,CP,CH,FC,FP,FH} for v in additional),
             'UNCERTAINTY_BASIS_EXPLICIT_KNOWN_ADDITIONAL_FACTUAL_COMMITMENTS')
        for label,refs,stem in (('MEDICINES',(MC,MP,MH),'medicines'),('ARQULE',(AC,AP,AH),'arqule'),('SPRINT',(SC,SP,SH),'sprint'),('SPRING2020_CASH',(CC,CP,CH),'spring2020-cash'),('AUTUMN2020_CASH',(FC,FP,FH),'autumn2020-cash')):
            selected=[v for v in additional if v['reference'] in refs]
            if not selected:continue
            expected={refs[0]:sha((Path('/driver')/('system-campaign-'+stem+'-terminal-facts.json')).read_bytes()),
                refs[1]:sha((Path('/driver')/('system_campaign_'+stem.replace('-','_')+'_facts.py')).read_bytes()),
                refs[2]:sha((root/('hydrated-'+stem+'-terminal-catalog.json')).read_bytes())}
            need(len(selected)==3 and {v['reference']:v['sha256'] for v in selected}==expected,
                 'UNCERTAINTY_BASIS_EXPLICIT_'+label+'_FACTUAL_COMMITMENTS')
            factual={**factual,'declared_fact_compilers':{**factual['declared_fact_compilers'],**expected}}
        factual_hash=digest(factual)
    model_document = deepcopy(uncertainty[0])
    model_document.pop('predecessor_checkpoint_sha256')
    value = dict(schema='research.system-campaign-common-factual-and-uncertainty-basis/1',
        factual_semantics_sha256=factual_hash, factual_semantics=factual,
        model_semantics=model_document, price_or_probability_estimate_selected=False)
    return digest(value), value
