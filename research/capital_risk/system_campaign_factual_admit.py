"""GitHub-hosted ONLY: authenticate an encrypted branch, never a local replay."""
import gzip,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from full_system_benchmark import need
from probe import check_context
from seal import MAGIC,safe_name,sha256_file


def hosted_destination(root):
    # This guard runs before any filesystem creation, credential or network use.
    check_context(os.environ)
    root=Path(root).resolve();temp=Path(os.environ['RUNNER_TEMP']).resolve()
    need(os.name=='posix' and str(temp)=='/home/runner/work/_temp'
         and root.parent==temp and root.name.startswith('campaign-factual-transfer-')
         and shutil.disk_usage(temp).free>=12*1024**3,'HOSTED_FACTUAL_DESTINATION_CAPACITY')
    return root


def authenticate(z,asset,key):
    h=hashlib.sha256();size=0;tail=b''
    with z.open(asset['name']) as source:
        header=source.read(20);need(header.startswith(MAGIC) and len(header)==20,'FACTUAL_CIPHER_HEADER')
        h.update(header);size=20
        dec=Cipher(algorithms.AES256(key),modes.GCM(header[-12:])).decryptor();dec.authenticate_additional_data(header)
        while chunk:=source.read(1024**2):
            h.update(chunk);size+=len(chunk);raw=tail+chunk
            if len(raw)>16:dec.update(raw[:-16]);tail=raw[-16:]
            else:tail=raw
        dec.finalize_with_tag(tail)
    need(size==asset['bytes'] and h.hexdigest()==asset['sha256'],'FACTUAL_CIPHER_LENGTH_HASH_GCM')
    return header,tail


class AuthenticatedStream:
    def __init__(self,source,asset,key,header,tag):
        need(source.read(20)==header,'FACTUAL_CIPHER_SAME_HEADER')
        self.source,self.left,self.tag,self.done=source,asset['bytes']-36,tag,False
        self.dec=Cipher(algorithms.AES256(key),modes.GCM(header[-12:],tag)).decryptor()
        self.dec.authenticate_additional_data(header)
    def read(self,n=-1):
        if n==0 or self.done:return b''
        if self.left:
            raw=self.source.read(min(self.left,n if n>0 else 1024**2));need(bool(raw),'FACTUAL_CIPHER_NOT_TRUNCATED')
            self.left-=len(raw);return self.dec.update(raw)
        need(self.source.read(16)==self.tag and self.source.read(1)==b'','FACTUAL_CIPHER_FOOTER')
        self.dec.finalize();self.done=True;return b''


def archive_bound(spec,limit):
    need(type(limit) is int and limit in (256*1024**2,512*1024**2,1024**3),
         'FACTUAL_DECLARED_ARCHIVE_LIMIT')
    need(type(spec['zip_bytes']) is int and 0<spec['zip_bytes']<limit,'FACTUAL_ENCRYPTED_DOWNLOAD_BOUND')


def admit(spec,root,key,*,max_zip_bytes=256*1024**2):
    root=hosted_destination(root);archive_bound(spec,max_zip_bytes);root.mkdir(mode=0o700)
    archive=root/'predecessor.zip'
    with archive.open('xb') as out:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=out,check=True,timeout=180)
    need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'FACTUAL_OLD_ZIP')
    with zipfile.ZipFile(archive) as z:
        raw=z.read(spec['receipt_name']);need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'FACTUAL_OLD_RECEIPT')
        r=json.loads(raw);asset=r['encrypted_output']
        need(r['schema']==spec['receipt_schema'] and int(r['run_id'])==spec['run_id'] and r['head']==spec['head']
             and r['arm']==spec['arm'] and asset==spec['encrypted_output'] and not r['production_contacted']
             and r['protocol_sha256']==spec['protocol_sha256'] and r['request_sha256']==spec['request_sha256'],'FACTUAL_OLD_SCOPE')
        need(set(z.namelist())=={spec['receipt_name'],'full-core-staging.json',asset['name']}
             and z.getinfo(asset['name']).file_size==asset['bytes'],'FACTUAL_OLD_ZIP_MEMBERS')
        header,tag=authenticate(z,asset,key)  # Authenticate before parsing plaintext.
        dest=root/'admitted';dest.mkdir(mode=0o700)
        with z.open(asset['name']) as source:
            plain=AuthenticatedStream(source,asset,key,header,tag)
            with tarfile.open(fileobj=plain,mode='r|gz') as tar:
                first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'FACTUAL_OLD_MANIFEST')
                raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'FACTUAL_OLD_MANIFEST_HASH')
                m=json.loads(raw)
                need(m['schema']=='research.full-system-output/1' and m['stage']==spec['stage'] and m['arm']==spec['arm']
                     and int(m['run_id'])==spec['run_id'] and m['head']==spec['head']
                     and m['request_sha256']==spec['request_sha256'] and m['protocol_sha256']==spec['protocol_sha256'],'FACTUAL_OLD_MANIFEST_BINDINGS')
                inventory=m['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,'FACTUAL_PLAINTEXT_BOUND')
                seen=set()
                while item:=tar.next():
                    safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'FACTUAL_OLD_MEMBER')
                    seen.add(item.name);expected=inventory[item.name];need(item.size==expected['bytes'],'FACTUAL_OLD_MEMBER_LENGTH')
                    target=dest/item.name;need(target.resolve().is_relative_to(dest),'FACTUAL_HOSTED_EXTRACTION_BOUNDARY')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(item) as src,target.open('xb') as out:shutil.copyfileobj(src,out,length=1024**2)
                    os.chmod(target,0o600);need(sha256_file(target)==expected['sha256'],'FACTUAL_OLD_MEMBER_HASH')
                need(seen==set(inventory),'FACTUAL_OLD_COMPLETE_INVENTORY')
            while plain.read(1024**2):pass
    for n,e in spec['inspections'].items():
        need(sha256_file(dest/n)==(e['sha256'] or inventory[n]['sha256']),'FACTUAL_OLD_STOP_BYTES');v=json.loads((dest/n).read_bytes());h=v['HostConfig']
        need(v['Name']==e['name'] and re.fullmatch('[a-f0-9]{64}',v['Id']) is not None and (e['id'] is None or v['Id']==e['id']) and not v['State']['Running'] and not v['State']['OOMKilled']
             and v['State']['ExitCode']==e['exit_code'],'FACTUAL_OLD_ACTUAL_STOP')
        need(v['Image']=='sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
             and h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3 and h['NanoCpus']==2000000000
             and h['ReadonlyRootfs'] and h['PidsLimit']==64 and h['CapDrop']==['ALL']
             and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),'FACTUAL_OLD_FENCES')
        mounts={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
        need(mounts['/out']['RW'] and all(not x['RW'] for k,x in mounts.items() if k!='/out'),'FACTUAL_OLD_INPUT_MOUNTS')
    need(sha256_file(dest/'source-bindings.json')==spec['source_binding_sha256'],'FACTUAL_OLD_SOURCE_REVIEW')
    if spec.get('unadvanced_qualification_failure'):
        prove_unadvanced(spec,inventory,dest)
    elif spec.get('review_refusal'):
        # Admission of the immutable evidence is not financial admission.
        # The corrected hosted preflight must independently review its entire
        # current committed branch before choosing or advancing a predecessor.
        prove_review_refusal(spec,inventory,dest)
    else:
        need(sha256_file(dest/'core-review.json')==spec['review_sha256'],'FACTUAL_OLD_REVIEW_BYTES')
    p=dest/spec['selected_checkpoint'];need(sha256_file(p)==spec['selected_file']['sha256'],'FACTUAL_SELECTED_GZIP')
    cp=json.loads(gzip.decompress(p.read_bytes()))
    need(cp['sha256']==spec['outer_sha256'] and cp['run']['checkpoint_sha256']==spec['inner_sha256']
         and cp['run']['state_sha256']==spec['state_sha256'] and cp['run']['input_sha256']==spec['input_sha256']
         and cp['base']==spec['base'] and cp['source_cursor']==spec['selected_session']
         and cp['journals']==spec['journals'] and cp['repairs']==spec['repairs'],'FACTUAL_SELECTED_BINDINGS')
    for n,c in cp['journals'].items():
        with (dest/f'book/{n}.jsonl').open('rb') as f:raw=f.read(c['bytes'])
        need(len(raw)==c['bytes'] and hashlib.sha256(raw).hexdigest()==c['prefix_sha256'],'FACTUAL_SELECTED_PREFIX')
    return dest


def prove_review_refusal(spec,inventory,root):
    if spec['review_refusal']=='UNCERTAINTY_ARCHIVE_NAME':
        need(spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
             and spec['arm']=='P02' and spec['run_id']==41069193936
             and spec['selected_session']=='2019-12-31'
             and spec['outer_sha256']=='994874c1abcbb5bb406d1ea76c9f0c6c751a5e500b073bf0134c6b00bc7912cb',
             'UNCERTAINTY_EXACT_ARCHIVE_REVIEW_FAILURE_SCOPE')
        log=root/'independent-review-stop/worker.log'
        need(sha256_file(log)==spec['review_log_sha256']
             and "FileNotFoundError: [Errno 2] No such file or directory: '/evidence/book/pre-event/2019-10-22.json.gz'" in log.read_text()
             and 'core-review.json' not in inventory,'UNCERTAINTY_EXACT_ORIGINAL_ARCHIVE_REVIEW_REFUSAL')
        name='independent-review-stop/core-review.json'
        need(sha256_file(root/name)==spec['review_sha256'],'UNCERTAINTY_RETAINED_FINANCIAL_REVIEW_BYTES')
        proof=json.loads((root/name).read_bytes())
        need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
             and proof['checkpoint_sha256']==spec['outer_sha256']
             and proof['counts']=={'formation':126,'daily':503} and proof['accounting_snapshots']==1258
             and not proof['complete'],'UNCERTAINTY_ACTUAL_PASSED_COMMITTED_FINANCIAL_PREFIX')
        need(spec['inspections']['economic-worker-inspect.json']['exit_code']==1
             and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==1,
             'UNCERTAINTY_ORIGINAL_FAILED_STOPS_NOT_RELABELED')
        return
    if spec['review_refusal']=='CORRELATION_COMMITTED_AXIS':
        need(spec['receipt_schema']=='research.system-campaign-factual-suffix-receipt/1'
             and sha256_file(root/'independent-review-stop/worker.log')==spec['review_log_sha256']
             and 'REFUSED_FULL_SYSTEM_FACTUAL_CORRELATION_COMMITTED_AXIS' in (root/'independent-review-stop/worker.log').read_text()
             and 'core-review.json' not in inventory,'P02_EXACT_NONFINANCIAL_REVIEW_REFUSAL')
        name='independent-review-stop/core-review.json';need(sha256_file(root/name)==spec['review_sha256'],'P02_RETAINED_HOSTED_FINANCIAL_REVIEW_BYTES')
        proof=json.loads((root/name).read_bytes())
        need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
             and proof['checkpoint_sha256']==spec['outer_sha256'],'P02_RETAINED_HOSTED_FINANCIAL_REVIEW_PASSED')
        name='independent-review-stop/reviewed-recovered-tail-proof.json'
        need(sha256_file(root/name)==spec['reviewed_tail_proof_sha256'],'P02_RETAINED_EXACT_RECOVERED_TAIL_REVIEW')
        return
    need(spec['review_refusal']=='CONVERSION_IDENTITY_REVIEW' and
         spec['receipt_schema']=='research.system-campaign-factual-suffix-receipt/1',
         'FACTUAL_DECLARED_REVIEW_ONLY_REFUSAL')
    log=root/'independent-review-stop/worker.log'
    need(sha256_file(log)==spec['review_log_sha256'] and
         'ValueError: REFUSED_LEDGER_SHARES' in log.read_text() and
         'core-review.json' not in inventory,'FACTUAL_EXACT_REVIEW_REFUSAL_BYTES')
    need(spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==1,
         'FACTUAL_ACTUAL_FAILED_REVIEW_STOP')


def prove_unadvanced(spec,inventory,root):
    """Refuse any unexpected progress instead of adopting an earlier checkpoint."""
    kind=spec.get('unadvanced_failure_kind','QUALIFIER_PARTIAL_PACKET')
    if kind=='COMPLETIONS2021_NULL_CONVERSION_CASH_SCHEMA':
        prove_unadvanced_completions_schema(spec,inventory,root);return
    if kind in ('SPRINT_PACKET_DAY_FIELD','SPRINT_RETAINED_BASIS_FILE','SPRINT_VARIANT_PACKET_SOURCE'):
        prove_unadvanced_sprint_packet(spec,inventory,root);return
    if kind=='ALDER_PACKET_DAY_FIELD':
        prove_unadvanced_alder_packet(spec,inventory,root);return
    if kind=='PROOF_BUFFER_CONSTRUCTOR':
        prove_unadvanced_buffer_constructor(spec,inventory,root);return
    need(kind in ('QUALIFIER_PARTIAL_PACKET','RESUME_REPAIR_PERMISSION'),'FACTUAL_DECLARED_UNADVANCED_FAILURE')
    prefix=spec.get('immutable_old_branch_prefix','lineage/old-branch/')
    need(prefix in ('lineage/old-branch/','lineage/old-branch/lineage/old-branch/'),'FACTUAL_DECLARED_IMMUTABLE_BRANCH')
    nested={n[len(prefix):]:v for n,v in inventory.items() if n.startswith(prefix)}
    digest=hashlib.sha256(json.dumps(nested,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    need(digest==spec['immutable_old_branch_inventory_sha256'],'FACTUAL_IMMUTABLE_WHOLE_OLD_BRANCH')
    for n in ('formation','daily','monthly','watch'):
        need(inventory[f'book/{n}.jsonl']==nested[f'book/{n}.jsonl'],'FACTUAL_NO_NEW_FINANCIAL_OR_TAIL_BYTES')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file'],'FACTUAL_NO_CHECKPOINT_ADVANCEMENT')
    if kind=='QUALIFIER_PARTIAL_PACKET':
        need('book/status.json' not in inventory and 'factual-input-qualification.json' not in inventory,
             'FACTUAL_QUALIFIER_NEVER_REACHED_FINANCIAL_ENTRY')
        log=(root/'economic-worker.log').read_text()
        need('in qualify_inputs' in log and 'ValueError: suppressed original spinoff differs' in log
             and '"status": "VERIFYING_INPUTS"' not in log,'FACTUAL_ACTUAL_PRE_FINANCIAL_REFUSAL')
    else:
        result=json.loads((root/'book/result.json').read_bytes());qualified=json.loads((root/'factual-input-qualification.json').read_bytes())
        error=result.get('error','')
        need(result.get('status')=='REFUSED' and 'in run_backtest' in error and 'path.write_bytes(args.repair_overlay.read_bytes())' in error
             and re.search(r"PermissionError: \[Errno 13\] Permission denied: '/out/book/repairs/[a-f0-9]{64}\.json'",error) is not None
             and 'recovered-tail-proof.json' not in inventory,'FACTUAL_EXACT_PRE_RECOVERY_PERMISSION_REFUSAL')
        need(qualified['financial_sessions_advanced']==0 and qualified['actual_fnf_source_rows_and_bars']
             and qualified['typed_spin_and_cash_proxy_suppression'] and qualified['source_row_and_quote_falsifiers']
             and qualified['original_packet_unchanged'],'FACTUAL_ACTUAL_FULL_INPUT_QUALIFICATION')
    proof=json.loads((root/'old-branch-canonical-review.json').read_bytes())
    need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified'] and not proof['complete'],
         'FACTUAL_UNADVANCED_CANONICAL_PREFIX_REVIEW')


def prove_unadvanced_alder_packet(spec,inventory,root):
    need(spec['receipt_schema']=='research.system-campaign-factual-suffix-receipt/1'
         and spec['unadvanced_receipt_status']=='STOPPED_FACTUAL_PREFIX_PRESERVED',
         'ALDER_PACKET_FAILURE_DECLARED_SCOPE')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file']==spec['unadvanced_original_selected_file']
         and all(inventory['book/'+n+'.jsonl']==spec['unadvanced_original_journals'][n]
                 for n in ('formation','daily','monthly','watch')),'ALDER_PACKET_FAILURE_NO_FINANCIAL_ADVANCEMENT')
    need(not any(n in inventory for n in ('book/status.json','book/result.json','alder-input-qualification.json',
         'acceleration-proof.json','correlation-capture-proof.json','recovered-tail-proof.json')),
         'ALDER_PACKET_FAILURE_BEFORE_FINANCIAL_ENTRY')
    ancestor=json.loads((root/'lineage/ancestor.json').read_bytes())
    need(inventory['lineage/verified-ancestor.zip']=={'bytes':ancestor['zip_bytes'],'sha256':ancestor['zip_sha256']}
         and ancestor['zip_sha256']==spec['unadvanced_complete_ancestor_zip_sha256'],'ALDER_PACKET_FAILURE_EXACT_ANCESTOR')
    raw=(root/'economic-worker.log').read_bytes();review=(root/'independent-review-stop/worker.log').read_bytes()
    need(hashlib.sha256(raw).hexdigest()==spec['unadvanced_worker_log_sha256']
         and b'facts.qualify(loaded' in raw and b'packet.session' in raw
         and b"AttributeError: 'Packet' object has no attribute 'session'" in raw
         and hashlib.sha256(review).hexdigest()==spec['unadvanced_reviewer_log_sha256']
         and b'REFUSED_FULL_SYSTEM_FACTUAL_EXACT_RECOVERED_TAIL' in review,'ALDER_PACKET_FAILURE_EXACT_LOGS')
    for name in ('old-branch-canonical-review.json','independent-review-stop/core-review.json'):
        need(sha256_file(root/name)==spec['unadvanced_prefix_reviews'][name],'ALDER_PACKET_FAILURE_REVIEW_BYTES')
        proof=json.loads((root/name).read_bytes())
        need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
             and proof['checkpoint_sha256']==spec['outer_sha256'] and not proof['complete'],
             'ALDER_PACKET_FAILURE_CANONICAL_PREFIX_REVIEW')


def prove_unadvanced_buffer_constructor(spec,inventory,root):
    need(spec['receipt_schema']=='research.system-campaign-basis-equivalence-receipt/1'
         and spec['unadvanced_receipt_status']=='STOPPED_FACTUAL_PREFIX_PRESERVED',
         'BUFFER_FAILURE_EXACT_DECLARED_PROOF_SCOPE')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file']==spec['unadvanced_original_selected_file']
         and all(inventory['book/'+n+'.jsonl']==spec['unadvanced_original_journals'][n]
             for n in ('formation','daily','monthly','watch')),
         'BUFFER_FAILURE_NO_FINANCIAL_OR_JOURNAL_ADVANCEMENT')
    need(not any(n in inventory for n in ('book/status.json','book/result.json','basis-equivalence-worker.json',
         'acceleration-proof.json','correlation-capture-proof.json')),
         'BUFFER_FAILURE_NEVER_ENTERED_FINANCIAL_BACKTEST')
    ancestor=json.loads((root/'lineage/ancestor.json').read_bytes())
    need(inventory['lineage/verified-ancestor.zip']=={'bytes':ancestor['zip_bytes'],'sha256':ancestor['zip_sha256']}
         and ancestor['zip_sha256']==spec['unadvanced_complete_ancestor_zip_sha256'],
         'BUFFER_FAILURE_EXACT_COMPLETE_ENCRYPTED_ANCESTOR')
    raw=(root/'economic-worker.log').read_bytes()
    need(hashlib.sha256(raw).hexdigest()==spec['unadvanced_worker_log_sha256']
         and b"AttributeError: 'function' object has no attribute 'prepare'" in raw
         and b'File "/driver/system_campaign_acceleration.py", line 56, in __enter__' in raw
         and sha256_file(root/'request.json')==spec['request_sha256'],
         'BUFFER_FAILURE_EXACT_PRE_FINANCIAL_CONSTRUCTOR_REFUSAL')
    old=json.loads((root/'old-branch-canonical-review.json').read_bytes())
    partial=json.loads((root/'independent-review-stop/core-review.json').read_bytes())
    need(old['complete'] and old['counts']=={'formation':126,'daily':2156}
         and old['all_prefixes_verified'] and old['all_daily_factors_and_chains_verified']
         and partial['checkpoint_sha256']==spec['outer_sha256']
         and partial['all_prefixes_verified'] and partial['all_daily_factors_and_chains_verified']
         and partial['counts']==spec['unadvanced_review_counts'],
         'BUFFER_FAILURE_ACTUAL_CANONICAL_OLD_AND_UNADVANCED_PREFIX')


def prove_unadvanced_completions_schema(spec,inventory,root):
    need(spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
         and spec['unadvanced_receipt_status']=='STOPPED_P02_UNCERTAINTY_PREFIX_PRESERVED'
         and spec['run_id']==41113691657 and spec['head']=='b64c05cb315f798251f1d82bd8d2909f16a77ade'
         and spec['arm']=='P02' and spec['selected_session']=='2020-12-31'
         and spec['outer_sha256']=='cbca264ce9e9b47f251e21b975d27d489607441ae781a9b562312c974d028a29'
         and spec['inspections']['economic-worker-inspect.json']['exit_code']==1
         and spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==1,
         'COMPLETIONS2021_SCHEMA_FAILURE_EXACT_SCOPE')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file']==spec['unadvanced_original_selected_file']
         and all(inventory['book/'+n+'.jsonl']==spec['unadvanced_original_journals'][n]
                 for n in ('formation','daily','monthly','watch')),
         'COMPLETIONS2021_SCHEMA_FAILURE_NO_FINANCIAL_ADVANCEMENT')
    need(not any(n in inventory for n in ('book/status.json','book/result.json',
         '2021-completions-input-qualification.json','acceleration-proof.json',
         'correlation-capture-proof.json','recovered-tail-proof.json',
         'common-factual-and-uncertainty-basis.json','uncertainty-certificate.jsonl',
         'correlation-inputs.jsonl.gz')),'COMPLETIONS2021_SCHEMA_FAILURE_BEFORE_FINANCIAL_ENTRY')
    ancestor=json.loads((root/'lineage/ancestor.json').read_bytes())
    need(inventory['lineage/verified-ancestor.zip']=={'bytes':ancestor['zip_bytes'],'sha256':ancestor['zip_sha256']}
         and ancestor['zip_sha256']==spec['unadvanced_complete_ancestor_zip_sha256'],
         'COMPLETIONS2021_SCHEMA_FAILURE_EXACT_ANCESTOR')
    worker=(root/'economic-worker.log').read_bytes();review=(root/'independent-review-stop/worker.log').read_bytes()
    need(hashlib.sha256(worker).hexdigest()==spec['unadvanced_worker_log_sha256']
         and b'loaded=facts.overlay(cp,overlay)' in worker
         and b'ValidationError: 1 validation error for Repair' in worker
         and b'pure conversion cash must be explicitly null' in worker
         and hashlib.sha256(review).hexdigest()==spec['unadvanced_reviewer_log_sha256']
         and b'REFUSED_FULL_SYSTEM_FACTUAL_EXACT_RECOVERED_TAIL' in review,
         'COMPLETIONS2021_SCHEMA_FAILURE_EXACT_LOGS')
    need(sha256_file(root/'2021-completions-input-overlay.json')==spec['unadvanced_input_overlay_sha256']
         and sha256_file(root/'hydrated-2021-completions-terminal-catalog.json')==spec['unadvanced_hydrated_catalog_sha256'],
         'COMPLETIONS2021_SCHEMA_FAILURE_EXACT_UNADOPTED_INPUT')
    overlay=json.loads((root/'2021-completions-input-overlay.json').read_bytes())
    need(overlay['predecessor_checkpoint_sha256']==spec['inner_sha256']
         and overlay['add'][0]['kind']=='CONVERSION' and overlay['add'][0]['cash_per_share']==0.,
         'COMPLETIONS2021_SCHEMA_FAILURE_ACTUAL_UNUSED_NUMERIC_CASH')
    for name in ('old-branch-canonical-review.json','independent-review-stop/core-review.json'):
        need(sha256_file(root/name)==spec['unadvanced_prefix_reviews'][name],
             'COMPLETIONS2021_SCHEMA_FAILURE_PREFIX_REVIEW_BYTES')
        proof=json.loads((root/name).read_bytes())
        need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
             and proof['checkpoint_sha256']==spec['outer_sha256'] and not proof['complete']
             and proof['counts']=={'formation':126,'daily':756},
             'COMPLETIONS2021_SCHEMA_FAILURE_CANONICAL_PREFIX_PROOF')
    path=root/'old-uncertainty-certificate-review.json'
    need(sha256_file(path)==spec['unadvanced_certificate_review_sha256'],
         'COMPLETIONS2021_SCHEMA_FAILURE_OLD_CERTIFICATE_BYTES')
    proof=json.loads(path.read_bytes())
    need(proof['status']=='COMMITTED_PREFIX_INTERVAL_INVARIANT' and proof['checkpoint_sha256']==spec['outer_sha256']
         and proof['through']=='2020-12-31' and proof['rows']==302 and proof['comparisons']==608
         and proof['financial_path_invariant_over_declared_sensor_interval'],
         'COMPLETIONS2021_SCHEMA_FAILURE_RETAINED_INTERVAL_PROOF')


def prove_unadvanced_sprint_packet(spec,inventory,root):
    kind=spec.get('unadvanced_failure_kind')
    need(spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
         and spec['unadvanced_receipt_status']=='STOPPED_P02_UNCERTAINTY_PREFIX_PRESERVED'
         and ((kind=='SPRINT_PACKET_DAY_FIELD' and spec['run_id']==41086155048)
              or (kind=='SPRINT_RETAINED_BASIS_FILE' and spec['run_id']==41089567127)
              or (kind=='SPRINT_VARIANT_PACKET_SOURCE' and spec['run_id']==41094977331))
         and spec['arm']=='P02' and spec['selected_session']=='2020-02-28'
         and spec['outer_sha256']=='04dbed001c745fa04aaa5a28320911a6a7ac3eb1cbfc2b418a42dadfaa5fcb0a',
         'SPRINT_PACKET_FAILURE_EXACT_DECLARED_SCOPE')
    need(inventory['book/checkpoint.json.gz']==spec['selected_file']==spec['unadvanced_original_selected_file']
         and all(inventory['book/'+n+'.jsonl']==spec['unadvanced_original_journals'][n]
                 for n in ('formation','daily','monthly','watch')),'SPRINT_PACKET_FAILURE_NO_FINANCIAL_ADVANCEMENT')
    need(not any(n in inventory for n in ('book/status.json','book/result.json','sprint-input-qualification.json',
         'acceleration-proof.json','correlation-capture-proof.json','recovered-tail-proof.json')),
         'SPRINT_PACKET_FAILURE_BEFORE_FINANCIAL_ENTRY')
    ancestor=json.loads((root/'lineage/ancestor.json').read_bytes())
    need(inventory['lineage/verified-ancestor.zip']=={'bytes':ancestor['zip_bytes'],'sha256':ancestor['zip_sha256']}
         and ancestor['zip_sha256']==spec['unadvanced_complete_ancestor_zip_sha256'],'SPRINT_PACKET_FAILURE_EXACT_ANCESTOR')
    worker=(root/'economic-worker.log').read_bytes();review=(root/'independent-review-stop/worker.log').read_bytes()
    if kind=='SPRINT_RETAINED_BASIS_FILE':
        need(not any(n in inventory for n in ('common-factual-and-uncertainty-basis.json',
             'uncertainty-certificate.jsonl','correlation-inputs.jsonl.gz','sprint-input-overlay.json'))
             and b"FileNotFoundError: [Errno 2] No such file or directory: '/old/common-factual-and-uncertainty-basis.json'" in worker,
             'SPRINT_BASIS_FAILURE_EXACT_MISSING_SUPPORT_BEFORE_INPUT_SUCCESSOR')
    elif kind=='SPRINT_VARIANT_PACKET_SOURCE':
        need(b'facts.qualify(loaded' in worker
             and b'REFUSED_FULL_SYSTEM_SPRINT_EXACT_ACTUAL_CANONICAL_PACKET_SCHEMA' in worker
             and sha256_file(root/'sprint-input-overlay.json')==spec['unadvanced_input_overlay_sha256']
             and 'common-factual-and-uncertainty-basis.json' not in inventory
             and 'uncertainty-certificate.jsonl' in inventory and 'correlation-inputs.jsonl.gz' in inventory,
             'SPRINT_VARIANT_FAILURE_EXACT_SCHEMA_GUARD_AND_UNCOMMITTED_INPUT')
    else:
        need(b'facts.qualify(loaded' in worker and b'packet.session' in worker
             and b"AttributeError: 'Packet' object has no attribute 'session'" in worker,
             'SPRINT_PACKET_FAILURE_EXACT_SCHEMA_ERROR')
    need(hashlib.sha256(worker).hexdigest()==spec['unadvanced_worker_log_sha256']
         and hashlib.sha256(review).hexdigest()==spec['unadvanced_reviewer_log_sha256']
         and b'REFUSED_FULL_SYSTEM_FACTUAL_EXACT_RECOVERED_TAIL' in review,'SPRINT_PACKET_FAILURE_EXACT_PRE_FINANCIAL_LOGS')
    for name in ('old-branch-canonical-review.json','independent-review-stop/core-review.json'):
        need(sha256_file(root/name)==spec['unadvanced_prefix_reviews'][name],'SPRINT_PACKET_FAILURE_REVIEW_BYTES')
        proof=json.loads((root/name).read_bytes())
        need(proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
             and proof['checkpoint_sha256']==spec['outer_sha256'] and not proof['complete']
             and proof['counts']=={'formation':126,'daily':543},'SPRINT_PACKET_FAILURE_CANONICAL_PREFIX_REVIEW')
    path=root/'old-uncertainty-certificate-review.json'
    need(sha256_file(path)==spec['unadvanced_certificate_review_sha256'],'SPRINT_PACKET_FAILURE_OLD_CERTIFICATE_BYTES')
    proof=json.loads(path.read_bytes())
    need(proof['status']=='COMMITTED_PREFIX_INTERVAL_INVARIANT' and proof['checkpoint_sha256']==spec['outer_sha256']
         and proof['through']=='2020-02-28' and proof['rows']==89 and proof['comparisons']==165
         and proof['financial_path_invariant_over_declared_sensor_interval'],'SPRINT_PACKET_FAILURE_RETAINED_INTERVAL_PROOF')
