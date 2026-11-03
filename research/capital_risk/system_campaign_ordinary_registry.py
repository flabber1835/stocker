"""Explicit data-driven three-reference registry for additional ordinary inputs."""
import json,re
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha

NAMESPACE='research:system-optimization-002/ordinary-catalog/'
REGISTRY='system-campaign-ordinary-catalog-registry.json'


def registrations(driver=Path('/driver')):
    x=json.loads((driver/REGISTRY).read_bytes())
    need(x['schema']=='research.ordinary-catalog-registry/1' and 1<=len(x['groups'])<=64,
         'ORDINARY_REGISTRY_EXPLICIT_BOUNDED_SCHEMA')
    stems=[]
    for e in x['groups']:
        need(set(e)=={'reference_stem','catalog_file','loader_file','private_file','overlay_file'}
             and e['reference_stem'].startswith(NAMESPACE)
             and re.fullmatch(r'[a-z0-9-]+/\d+/',e['reference_stem'][len(NAMESPACE):]) is not None,
             'ORDINARY_REGISTRY_DECLARED_REFERENCE_STEM')
        need(all(re.fullmatch(r'[a-z0-9_-]+\.(json|py)',e[k]) is not None
                 for k in ('catalog_file','loader_file','private_file','overlay_file')),
             'ORDINARY_REGISTRY_ONLY_PLAIN_FILENAMES')
        stems.append(e['reference_stem'])
    need(len(set(stems))==len(stems),'ORDINARY_REGISTRY_UNIQUE_GROUPS')
    return x['groups']


def expected(e,root,driver=Path('/driver')):
    return {e['reference_stem']+kind:sha((base/e[field]).read_bytes()) for kind,base,field in
            (('catalog',driver,'catalog_file'),('loader',driver,'loader_file'),('private',root,'private_file'))}


def committed(root,cp,driver=Path('/driver')):
    groups=registrations(driver);found=[];allrefs=[]
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'ORDINARY_REGISTRY_ALL_ORIGINAL_REPAIR_BYTES')
        doc=json.loads(raw)
        if doc['schema']=='terminal-repair/1':
            allrefs.extend(r for r in doc['source_evidence'] if r['reference'].startswith(NAMESPACE))
    known={e['reference_stem']+k for e in groups for k in ('catalog','loader','private')}
    need(all(r['reference'] in known for r in allrefs),'ORDINARY_REGISTRY_NO_UNDECLARED_REFERENCE')
    for e in groups:
        refs=[r for r in allrefs if r['reference'].startswith(e['reference_stem'])]
        if not refs:continue
        wanted=expected(e,root,driver)
        need(len(refs)==3 and {r['reference']:r['sha256'] for r in refs}==wanted,
             'ORDINARY_REGISTRY_EXACT_THREE_BYTE_COMMITMENTS')
        catalog=json.loads((driver/e['catalog_file']).read_bytes())
        payload=json.loads((root/e['private_file']).read_bytes())
        need(catalog['commitment_group']==e and catalog['loader_sha256']==wanted[e['reference_stem']+'loader']
             and payload['catalog']==catalog,'ORDINARY_REGISTRY_EXACT_BOUND_PUBLIC_AND_PRIVATE_CATALOG')
        found.append((e,wanted))
    return found


def preserve(cp,old,out):
    groups=committed(old,cp)
    for e,_ in groups:
        with (out/e['private_file']).open('xb') as target:target.write((old/e['private_file']).read_bytes())
    return len(groups)


def augment(root,cp,semantics):
    groups=committed(root,cp);refs=dict(semantics['declared_fact_compilers'])
    for _,new in groups:
        need(not set(refs)&set(new),'ORDINARY_REGISTRY_NO_REFERENCE_REDEFINITION');refs.update(new)
    return {**semantics,'declared_fact_compilers':refs}
