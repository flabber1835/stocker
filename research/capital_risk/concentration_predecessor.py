"""Exact authenticated predecessor admission, never policy/state conversion."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from core_recovery_job import inspect_stopped
from seal import decrypt,extract_verified,sha256_file
from stage import PROTOCOL

def need(v,code):
    if not v:raise ValueError(code)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def validate_book(root,spec,policy):
    path=root/'checkpoint.json.gz'
    need(sha256_file(path)==spec['checkpoint_file_sha256'],'REFUSED_C_OWN_CHECKPOINT_BYTES')
    with gzip.open(path,'rt') as stream:c=json.load(stream)
    need(c['sha256']==spec['outer_sha256']==digest({k:v for k,v in c.items() if k!='sha256'}),'REFUSED_C_OWN_OUTER_CHECKPOINT')
    r=c['run'];need(r['checkpoint_sha256']==spec['inner_sha256']==digest({k:v for k,v in r.items() if k!='checkpoint_sha256'}),'REFUSED_C_OWN_INNER_CHECKPOINT')
    need(r['state_sha256']==spec['state_sha256']==digest(r['state']) and r['input_sha256']==spec['input_sha256']
        and r['input_sha256']==digest(dict(base=c['base'],repairs=c['repairs'])),'REFUSED_C_OWN_STATE_INPUT')
    need(c['base']['policy']==r['policy']==policy and c['source_cursor']==spec['cursor']
        and c['completed']==spec['measured_closes']==0 and c['journals']==spec['journals'],'REFUSED_C_OWN_POLICY_CURSOR')
    for name,commitment in c['journals'].items():
        p=root/(name+'.jsonl');raw=p.read_bytes()
        need(len(raw)==commitment['bytes'] and hashlib.sha256(raw).hexdigest()==commitment['prefix_sha256'],'REFUSED_C_OWN_JOURNAL_PREFIX')
        lines=raw.splitlines(keepends=True);last=hashlib.sha256(lines[-1]).hexdigest() if lines else None
        need(last==commitment['last_record_sha256'],'REFUSED_C_OWN_JOURNAL_LAST_RECORD')
    need(len((root/'formation.jsonl').read_bytes().splitlines())==spec['formation_closes'],'REFUSED_C_OWN_FORMATION_COUNT')
    return c

def admit(download,private,spec,key,contract):
    receipt_path=download/'concentration-quarter.json'
    need(sha256_file(receipt_path)==spec['receipt_sha256'],'REFUSED_C_PREDECESSOR_RECEIPT_BYTES')
    receipt=json.loads(receipt_path.read_bytes())
    need(receipt['schema']=='research.concentration-quarter-receipt/1' and receipt['run_id']==str(spec['run_id'])
        and receipt['source_commit']==spec['head'] and receipt['status']=='C_QUARTER_INCOMPLETE_PRESERVED'
        and receipt['protocol_sha256']==contract and receipt['production_contacted'] is False
        and not receipt['unknown_arms'] and not receipt['qualification_unknown']
        and receipt['encrypted_outputs']==spec['encrypted_outputs'],'REFUSED_C_PREDECESSOR_RECEIPT_SCOPE')
    admitted=private/'admitted-predecessor';admitted.mkdir()
    manifests={}
    for asset in receipt['encrypted_outputs']:
        arm=asset['arm'];need(arm in ('QUAL','B','B0','C') and asset['name']=='concentration-quarter-'+arm+'.tar.crseal','REFUSED_C_PREDECESSOR_ASSET')
        cipher=download/asset['name'];need(cipher.stat().st_size==asset['bytes'] and sha256_file(cipher)==asset['sha256'],'REFUSED_C_PREDECESSOR_CIPHER')
        plain=private/('prior-'+arm+'.authenticated.tar');decrypt(cipher,plain,key,asset['sha256'])
        with tarfile.open(plain,'r|') as tar:
            first=tar.next();need(first is not None and first.name=='manifest.json' and first.isfile() and first.size<=2*1024**2,'REFUSED_C_PREDECESSOR_MANIFEST')
            raw=tar.extractfile(first).read()
        need(hashlib.sha256(raw).hexdigest()==spec['output_manifests'][arm]['sha256'],'REFUSED_C_PREDECESSOR_MANIFEST_DIGEST')
        m=json.loads(raw);need(m['schema']=='research.capital-risk-output/1' and m['arm']==arm and m['stage']=='short-core-window'
            and m['protocol_sha256']==PROTOCOL and m['screen_protocol_sha256']==contract,'REFUSED_C_PREDECESSOR_MANIFEST_SCOPE')
        need(len(m['members'])==spec['output_manifests'][arm]['members'],'REFUSED_C_PREDECESSOR_INVENTORY_COUNT')
        extract_verified(plain,admitted/arm,hashlib.sha256(raw).hexdigest(),expected_schema='research.capital-risk-output/1')
        manifests[arm]=hashlib.sha256(raw).hexdigest()
    need(set(manifests)=={'QUAL','B','B0','C'},'REFUSED_C_PREDECESSOR_ARM_SET')
    for name,expected in spec['qualified_files'].items():need(sha256_file(admitted/'QUAL'/name)==expected,'REFUSED_C_QUALIFIED_FILE_'+name)
    gate=json.loads((admitted/'QUAL/canonical-gate.json').read_bytes())
    need(gate['status']=='CANONICAL_CORE_GATE_PASSED' and gate['cases']==15,'REFUSED_C_ACTUAL_PRIOR_GATE')
    for arm,details in spec['arms'].items():
        prior=admitted/arm;need(sha256_file(prior/'independent-review.json')==details['review_sha256'],'REFUSED_C_PRIOR_REVIEW')
        for name,expected in details['inspections'].items():
            inspected=inspect_stopped(prior/name,expected)
            need(inspected['exit_code']==0 and inspected['stopped'] and not inspected['oom'],'REFUSED_C_PRIOR_STOP')
        validate_book(prior/'run-001',details,details['policy'])
    return admitted,manifests

def copy_for_resume(prior,destination,spec,policy):
    need(not destination.exists(),'REFUSED_C_RESUME_OVERWRITE')
    c=validate_book(prior,spec,policy);shutil.copytree(prior,destination)
    need(validate_book(destination,spec,policy)==c,'REFUSED_C_RESUME_COPY')
    archive=destination/'predecessor-checkpoints';archive.mkdir(exist_ok=True)
    target=archive/(c['sha256']+'.json.gz');need(not target.exists(),'REFUSED_C_PREDECESSOR_ARCHIVE_COLLISION')
    shutil.copyfile(prior/'checkpoint.json.gz',target)
    need(sha256_file(target)==spec['checkpoint_file_sha256'],'REFUSED_C_ARCHIVED_PREDECESSOR')
    return dict(predecessor_outer_sha256=c['sha256'],predecessor_state_sha256=c['run']['state_sha256'],
        predecessor_input_sha256=c['run']['input_sha256'],unchanged_through=c['source_cursor'],policy=policy,
        financial_state_unchanged=True,all_old_prefixes_and_zero_tails_verified=True)

def preserved_prefixes(root,spec):
    archive=root/'predecessor-checkpoints'/(spec['outer_sha256']+'.json.gz')
    need(sha256_file(archive)==spec['checkpoint_file_sha256'],'REFUSED_C_PREDECESSOR_BYTES_CHANGED')
    for name,commitment in spec['journals'].items():
        with (root/(name+'.jsonl')).open('rb') as stream:prefix=stream.read(commitment['bytes'])
        need(len(prefix)==commitment['bytes'] and hashlib.sha256(prefix).hexdigest()==commitment['prefix_sha256'],'REFUSED_C_PRESERVED_OLD_PREFIX_'+name)
    return dict(predecessor_checkpoint_bytes_unchanged=True,all_four_old_prefixes_preserved=True,
        original_unsent_tail_bytes=0)
