"""Exact common action semantics independent of own predecessor identities."""
import hashlib,json
from pathlib import Path
from system_campaign_facts import digest,CATALOG_REF,COMPILER_REF,HYDRATED_REF
from full_system_benchmark import need
from system_campaign_winter_facts import CATALOG as WINTER,COMPILER as WINTER_COMPILER,HYDRATED as WINTER_HYDRATED

ADDITIONAL='research:system-optimization-002/additional-terminal-catalog/1'
ADDITIONAL_COMPILER='research:system-optimization-002/additional-terminal-compiler/1'
ADDITIONAL_HYDRATED='research:system-optimization-002/additional-private-terminal-catalog/1'
SPRING='research:system-optimization-002/spring-terminal-catalog/1'
SPRING_COMPILER='research:system-optimization-002/spring-terminal-compiler/1'
SPRING_HYDRATED='research:system-optimization-002/spring-private-terminal-catalog/1'
FOLLOWUP='research:system-optimization-002/followup-terminal-catalog/1'
FOLLOWUP_COMPILER='research:system-optimization-002/followup-terminal-compiler/1'
FOLLOWUP_HYDRATED='research:system-optimization-002/followup-private-terminal-catalog/1'
TGI='research:system-optimization-002/tgi-cash-catalog/1'
TGI_COMPILER='research:system-optimization-002/tgi-cash-compiler/1'
TGI_HYDRATED='research:system-optimization-002/tgi-private-cash-catalog/1'
MIDYEAR='research:system-optimization-002/midyear-terminal-catalog/1'
MIDYEAR_COMPILER='research:system-optimization-002/midyear-terminal-compiler/1'
MIDYEAR_HYDRATED='research:system-optimization-002/midyear-private-terminal-catalog/1'
LATE='research:system-optimization-002/late-terminal-catalog/1'
LATE_COMPILER='research:system-optimization-002/late-terminal-compiler/1'
LATE_HYDRATED='research:system-optimization-002/late-private-terminal-catalog/1'
YEAREND='research:system-optimization-002/yearend-terminal-catalog/1'
YEAREND_COMPILER='research:system-optimization-002/yearend-terminal-compiler/1'
YEAREND_HYDRATED='research:system-optimization-002/yearend-private-terminal-catalog/1'
FOLLOWON='research:system-optimization-002/followon-terminal-catalog/1'
FOLLOWON_COMPILER='research:system-optimization-002/followon-terminal-compiler/1'
FOLLOWON_HYDRATED='research:system-optimization-002/followon-private-terminal-catalog/1'


def semantics(base,documents,expected):
    found={};terms={'suppress':{},'add':{}}
    for document in documents:
        need(document['schema']=='terminal-repair/1','COMMON_BASIS_ORDINARY_TERMINAL_SCHEMA')
        for value in document['source_evidence']:
            reference=value['reference']
            if reference not in expected:continue
            need(value['sha256']==expected[reference],'COMMON_BASIS_DECLARED_FACT_COMPILER')
            found[reference]=value['sha256']
        for name in terms:
            for value in document[name]:
                key=value['session'],value['security_id']
                need(key not in terms[name] or terms[name][key]==value,'COMMON_BASIS_NO_CONFLICTING_TERM')
                terms[name][key]=value
    need(set(found)==set(expected),'COMMON_BASIS_ALL_FACTS_PRESENT')
    value={'schema':'research.system-campaign-common-semantic-basis/1',
        'frozen_bundle_sha256':base['bundle_sha256'],'frozen_archive_sha256':base['archive_sha256'],
        'declared_fact_compilers':found,
        **{name:[rows[k] for k in sorted(rows)] for name,rows in terms.items()}}
    return value


def basis(evidence,cp):
    names={CATALOG_REF:Path('/driver/system-campaign-factual-catalog.json'),
        COMPILER_REF:Path('/driver/system_campaign_facts.py'),
        HYDRATED_REF:evidence/'hydrated-factual-catalog.json',
        ADDITIONAL:Path('/driver/system-campaign-additional-terminal-facts.json'),
        ADDITIONAL_COMPILER:Path('/driver/system_campaign_terminal_facts.py'),
        ADDITIONAL_HYDRATED:evidence/'hydrated-additional-terminal-catalog.json',
        WINTER:Path('/driver/system-campaign-corrected-winter-facts.json'),
        WINTER_COMPILER:Path('/driver/system_campaign_winter_facts.py'),
        WINTER_HYDRATED:evidence/'hydrated-corrected-winter-cash-catalog.json',
        SPRING:Path('/driver/system-campaign-spring-terminal-facts.json'),
        SPRING_COMPILER:Path('/driver/system_campaign_spring_facts.py'),
        SPRING_HYDRATED:evidence/'hydrated-spring-terminal-catalog.json',
        FOLLOWUP:Path('/driver/system-campaign-followup-terminal-facts.json'),
        FOLLOWUP_COMPILER:Path('/driver/system_campaign_followup_facts.py'),
        FOLLOWUP_HYDRATED:evidence/'hydrated-followup-terminal-catalog.json',
        TGI:Path('/driver/system-campaign-tgi-cash-facts.json'),
        TGI_COMPILER:Path('/driver/system_campaign_tgi_facts.py'),
        TGI_HYDRATED:evidence/'hydrated-tgi-cash-catalog.json',
        MIDYEAR:Path('/driver/system-campaign-midyear-terminal-facts.json'),
        MIDYEAR_COMPILER:Path('/driver/system_campaign_midyear_facts.py'),
        MIDYEAR_HYDRATED:evidence/'hydrated-midyear-terminal-catalog.json',
        LATE:Path('/driver/system-campaign-late-terminal-facts.json'),
        LATE_COMPILER:Path('/driver/system_campaign_late_facts.py'),
        LATE_HYDRATED:evidence/'hydrated-late-terminal-catalog.json',
        YEAREND:Path('/driver/system-campaign-yearend-terminal-facts.json'),
        YEAREND_COMPILER:Path('/driver/system_campaign_yearend_facts.py'),
        YEAREND_HYDRATED:evidence/'hydrated-yearend-terminal-catalog.json',
        FOLLOWON:Path('/driver/system-campaign-followon-terminal-facts.json'),
        FOLLOWON_COMPILER:Path('/driver/system_campaign_followon_facts.py'),
        FOLLOWON_HYDRATED:evidence/'hydrated-followon-terminal-catalog.json'}
    need(all(p.is_file() for p in names.values()),'COMMON_BASIS_ACTUAL_COMPLETE_FACT_FILES')
    expected={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in names.items()};documents=[]
    for spec in cp['repairs']:
        raw=(evidence/'book/repairs'/spec['filename']).read_bytes()
        need(hashlib.sha256(raw).hexdigest()==spec['sha256'],'COMMON_BASIS_EXACT_REPAIR_ARCHIVE')
        documents.append(json.loads(raw))
    value=semantics(cp['base'],documents,expected)
    return digest(value),value
