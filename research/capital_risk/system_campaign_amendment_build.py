"""Build the new canonical ordinary commitment; no circular payload hashes."""
from copy import deepcopy
import json
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import sha
from system_campaign_cash_batch import CashBatch
from system_campaign_future_amendment import (
    CATALOG,COMPILER,HYDRATED,INNER,CUTOVER,documents,projection,
    PAYLOAD_NAME,OVERLAY_NAME,PROJECTION_NAME,FutureProjection)


def build(cp,old,out):
    catalog_path=Path('/driver/system-campaign-future-input-amendment-catalog.json')
    raw=catalog_path.read_bytes();catalog=json.loads(raw);cash=CashBatch(catalog)
    refs={CATALOG:sha(raw),COMPILER:sha(Path('/driver/system_campaign_future_amendment.py').read_bytes())}
    policy,view=projection(cp,documents(old,cp),refs)
    following=json.loads((old/'hydrated-following-completions-terminal-catalog.json').read_bytes())
    apha,=[t for t in following['terms'] if t['ticker']=='APHA']
    witness=cash.hydrate(cp,old,out,extra_witnesses=(apha['delivered_identity_witness'],))
    payload=dict(schema='research.future-input-amendment-private-payload/1',policy=policy,
        projection_evidence=refs,derived_projection=view,new_patch=cash.patch(),cash_witnesses=witness,
        catalog=catalog,financial_state_changed=False,production_contacted=False)
    save(out/PAYLOAD_NAME,payload);save(out/PROJECTION_NAME,view)
    evidence=[dict(reference=r,sha256=h,description='Exact explicit future input amendment and primary-confirmed cash batch.')
              for r,h in (*refs.items(),(HYDRATED,sha((out/PAYLOAD_NAME).read_bytes())))]
    for t in catalog['terms']:
        evidence.extend([dict(reference=t['primary_source'],sha256=None,description=t['description']),
                         dict(reference=t['timing_source'],sha256=None,description='Actual preopen completion and preserved last trading day.')])
    save(out/OVERLAY_NAME,dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=INNER,
        source_evidence=evidence,**cash.patch()))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded=load_repair(out/OVERLAY_NAME,resume_session=CUTOVER,predecessor_checkpoint_sha256=INNER)
    return cash,loaded,FutureProjection(out,cp)


def preserve_following(cp,old,out):
    from system_campaign_following_completions_facts import CATALOG as C,COMPILER as P,HYDRATED as H
    name='hydrated-following-completions-terminal-catalog.json'
    expected={C:sha(Path('/driver/system-campaign-following-completions-terminal-facts.json').read_bytes()),
        P:sha(Path('/driver/system_campaign_following_completions_facts.py').read_bytes()),H:sha((old/name).read_bytes())}
    found=[]
    for doc in documents(old,cp).values():found.extend(v for v in doc['source_evidence'] if v['reference'] in expected)
    need(len(found)==3 and {v['reference']:v['sha256'] for v in found}==expected,
         'AMENDMENT_SUPERSEDED_ORIGINAL_FOLLOWING_BYTES_PRESERVED')
    with (out/name).open('xb') as target:target.write((old/name).read_bytes())
    save(out/'superseded-following-input-audit.json',dict(original_source_evidence=expected,
        original_bytes_preserved=True,original_basis_was_refused=True,
        original_descriptor_retained=True,future_APHA_pair_retired_only_by_new_explicit_commitment=True))
