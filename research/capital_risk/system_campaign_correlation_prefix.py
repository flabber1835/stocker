"""Byte/identity-only recovery of a committed observer prefix; no financial math."""
import gzip,hashlib,json
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import digest,sha


def checkpoint(root):return json.loads(gzip.decompress((Path(root)/'book/checkpoint.json.gz').read_bytes()))


def stream(root,name):
    path=Path(root)/('book/'+name+'.jsonl')
    return path.open('rb') if path.exists() else gzip.open(str(path)+'.gz','rb')


def financial_identities(root,cp):
    result={}
    for name in ('formation','daily'):
        c=cp['journals'][name]
        with stream(root,name) as f:raw=f.read(c['bytes'])
        need(len(raw)==c['bytes'] and sha(raw)==c['prefix_sha256'],'CORRELATION_CURRENT_COMMITTED_BYTES')
        for line in raw.splitlines():
            r=json.loads(line);need(r['session'] not in result,'CORRELATION_UNIQUE_FINANCIAL_SESSION')
            result[r['session']]=r['state_sha256']
    return result


def seed(root,cp,capture):
    financial=financial_identities(root,cp);rows=[];seen=[];chain=digest('system-optimization-002/raw-correlation/1')
    with gzip.open(capture,'rb') as f:
        for raw in f:
            r=json.loads(raw)
            if r['session']>cp['source_cursor']:break
            committed=r.pop('chain_sha256');chain=digest({'previous':chain,'record':r})
            need(committed==chain and financial.get(r['session'])==r['next_state_sha256'],'CORRELATION_SOURCE_CHAIN_STATE_IDENTITY')
            rows.append(raw);seen.append(r['session'])
    need(seen==sorted(financial),'CORRELATION_RESTORED_COMPLETE_AXIS')
    need(not rows or json.loads(rows[-1])['next_state_sha256']==cp['run']['state_sha256'],'CORRELATION_RESTORED_SELECTED_STATE')
    return rows


def restore(current,source,target,spec,expected):
    current,source,target=map(Path,(current,source,target));cp=checkpoint(current);old=checkpoint(source)
    raw=(source/'book/checkpoint.json.gz').read_bytes()
    need(sha(raw)==spec['selected_file']['sha256'] and old['sha256']==spec['outer_sha256']
         and sha((source/'source-bindings.json').read_bytes())==spec['source_binding_sha256'],'CORRELATION_EXACT_ADMITTED_ANCESTOR')
    need(old['source_cursor']==cp['source_cursor'] and old['run']['state_sha256']==cp['run']['state_sha256']
         and old['base']==cp['base'] and financial_identities(source,old)==financial_identities(current,cp),
         'CORRELATION_SAME_OWN_COMMITTED_FINANCIAL_PREFIX')
    rows=seed(current,cp,source/'correlation-inputs.jsonl.gz');raw=b''.join(rows)
    actual={'rows':len(rows),'bytes':len(raw),'sha256':sha(raw)}
    need(actual==expected,'CORRELATION_FROZEN_RAW_PREFIX_COMMITMENT')
    target.mkdir(parents=True,exist_ok=False)
    with (target/'prefix.jsonl.gz').open('xb') as out,gzip.GzipFile(filename='',fileobj=out,mode='wb',compresslevel=1,mtime=0) as f:f.write(raw)
    proof={'schema':'research.system-campaign-derived-correlation-prefix/1','source_artifact_id':spec['artifact_id'],
        'source_run_id':spec['run_id'],'source_zip_sha256':spec['zip_sha256'],'source_spec_sha256':digest(spec),
        'current_outer_sha256':cp['sha256'],'source_outer_sha256':old['sha256'],'selected_state_sha256':cp['run']['state_sha256'],
        'raw_prefix':actual,'every_original_observer_chain_and_committed_state_identity_verified':True,
        'original_capture_and_financial_evidence_unchanged':True,'new_financial_sessions':0}
    save(target/'provenance.json',proof);return proof
