"""Readmit exact stopped reconstruction evidence; no financial state is adopted."""
import ast,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_factual_admit import hosted_destination,authenticate,AuthenticatedStream
from full_system_core import hosted
from probe import FORBIDDEN_CREDENTIALS,check_context
from runtime_identity import EXECUTION_IMAGE
from stage import SECRET
from seal import safe_name,sha256_file


def compare_stopped_books(cold,bounded,source,expected_sha256):
    """Reuse only the qualified pure byte comparator, without replay imports."""
    raw=Path(source).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==expected_sha256,'RECONSTRUCTION_ADMISSION_QUALIFIED_COMPARATOR_SOURCE')
    tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='compare_books']
    need(len(nodes)==1 and not nodes[0].decorator_list,'RECONSTRUCTION_ADMISSION_ONE_PURE_QUALIFIED_COMPARATOR')
    module=ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[]));scope={'json':json,'need':need}
    exec(compile(module,'<qualified-stopped-book-byte-comparator>','exec'),scope)
    return scope['compare_books'](cold,bounded)


def require_scope(admission,spec):
    need(admission['schema']=='research.exact-reconstruction-economic-admission/1'
         and admission['run_id']==41138859385 and admission['artifact_id']==13018377134
         and admission['head']=='fd0a26d42ef175a70bfc81b56fbe7339dc43ab94'
         and admission['predecessor_outer_sha256']==spec['outer_sha256']
         and spec['run_id']==41134805155 and spec['selected_session']=='2021-11-30'
         and admission['next_session']=='2021-12-01'
         and admission['economic_predecessor_is_qualification_book'] is False,
         'RECONSTRUCTION_ADMISSION_EXACT_QUALIFIED_OWN_FINANCIAL_BOUNDARY')


def require_stopped(v,expected):
    h,c=v['HostConfig'],v['Config'];mounts={x['Destination']:x for x in v['Mounts'] if x['Type']=='bind'}
    need(v['Name']==expected['name'] and v['Id']==expected['id'] and v['Image']==EXECUTION_IMAGE
         and not v['State']['Running'] and not v['State']['OOMKilled'] and v['State']['ExitCode']==0
         and h['NetworkMode']=='none' and h['Memory']==h['MemorySwap']==8*1024**3
         and h['NanoCpus']==2000000000 and h['PidsLimit']==64 and h['ReadonlyRootfs']
         and h['CapDrop']==['ALL'] and any(s.startswith('no-new-privileges') for s in h['SecurityOpt']),
         'RECONSTRUCTION_ADMISSION_ACTUAL_STOPPED_FENCED_WORKER')
    need(set(mounts)=={'/variant','/frozen','/driver','/out','/old'} and mounts['/out']['RW']
         and all(not x['RW'] for k,x in mounts.items() if k!='/out')
         and c['WorkingDir']=='/variant' and c['User']==expected['user']
         and c['Labels']['research.study']=='full-system-search-20261029'
         and c['Labels']['research.role']=='worker'
         and c['Cmd']==['-B','-u','/driver/system_campaign_resume_qualification.py','--spec',
             '/out/spec.json','--request','/driver/system-campaign-reconstruction-request.json'],
         'RECONSTRUCTION_ADMISSION_EXACT_WORKER_MOUNTS_AND_ENTRYPOINT')
    forbidden=set(FORBIDDEN_CREDENTIALS)|{SECRET,'GH_TOKEN','GITHUB_TOKEN'}
    need(not any(k in forbidden and value for k,_,value in (s.partition('=') for s in c['Env'])),
         'RECONSTRUCTION_ADMISSION_NO_WORKER_CREDENTIALS')


def require_later_cash(catalog,next_session):
    from system_campaign_cash_calendar import validate_term
    need(catalog['canonical_financial_source_changed'] is False and catalog['provider_metadata_upgraded'] is False,
         'RECONSTRUCTION_ADMISSION_ONLY_TERMINAL_INPUT_APPEND')
    for term in catalog['terms']:
        validate_term(term)
        need(min(term['native_session'],term['added']['session'])>next_session,
             'RECONSTRUCTION_ADMISSION_NO_CHECKPOINT_OR_NEXT_PACKET_CHANGE')


def preserve_members(root,out,manifest,admission,spec,old):
    """Reference only the identical duplicate opaque ancestor; copy all unique bytes."""
    target=out/'lineage/reconstruction-qualification';target.mkdir(parents=True)
    excluded='lineage/verified-ancestor.zip';original=root/excluded;financial=old.parent/'predecessor.zip'
    need(manifest['members'][excluded]==dict(bytes=spec['zip_bytes'],sha256=spec['zip_sha256'])
         and all(p.stat().st_size==spec['zip_bytes'] and sha256_file(p)==spec['zip_sha256'] for p in (original,financial)),
         'RECONSTRUCTION_ADMISSION_IDENTICAL_OPAQUE_ANCESTOR_ONLY')
    for name,entry in manifest['members'].items():
        if name==excluded:continue
        p=target/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,p)
        need(p.stat().st_size==entry['bytes'] and sha256_file(p)==entry['sha256'],
             'RECONSTRUCTION_ADMISSION_EVERY_UNIQUE_MEMBER_PRESERVED')
    for name in ('authenticated-manifest.json','artifact-receipt.json','artifact-staging.json'):
        shutil.copyfile(root/name,target/name)
    proof=dict(schema='research.exact-reconstruction-lineage/1',qualification_run_id=admission['run_id'],
        qualification_artifact_id=admission['artifact_id'],qualification_zip_sha256=admission['zip_sha256'],
        qualification_zip_bytes=admission['zip_bytes'],members=len(manifest['members']),
        copied_unique_members=len(manifest['members'])-1,duplicate_member=excluded,
        duplicate_reference='../verified-ancestor.zip',duplicate_sha256=spec['zip_sha256'],
        duplicate_bytes=spec['zip_bytes'],qualification_checkpoint_not_economic_predecessor=True,production_contacted=False)
    save(target/'preservation.json',proof);return target


def admit(admission,spec,old,out,key,*,driver=Path('/driver')):
    check_context(os.environ)
    root=hosted_destination(Path(os.environ['RUNNER_TEMP'])/'campaign-factual-transfer-reconstruction-admission')
    require_scope(admission,spec)
    need(type(admission['zip_bytes']) is int and 0<admission['zip_bytes']<1024**3,
         'RECONSTRUCTION_ADMISSION_TYPED_ONE_GIB_CIPHER_BOUND')
    root.mkdir(mode=0o700);archive=root/'qualification.zip'
    with archive.open('xb') as stream:
        subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{admission['artifact_id']}/zip"],
            stdout=stream,check=True,timeout=180)
    need(archive.stat().st_size==admission['zip_bytes'] and sha256_file(archive)==admission['zip_sha256'],
         'RECONSTRUCTION_ADMISSION_EXACT_ZIP')
    dest=root/'admitted';dest.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as z:
        raw=z.read('reconstruction.json')
        need(hashlib.sha256(raw).hexdigest()==admission['receipt_sha256'],
             'RECONSTRUCTION_ADMISSION_RECEIPT_BYTES')
        r=json.loads(raw);asset=r['encrypted_output']
        need(r==admission['receipt'] and set(z.namelist())=={'reconstruction.json','full-core-staging.json',asset['name']}
             and z.getinfo(asset['name']).file_size==asset['bytes'],
             'RECONSTRUCTION_ADMISSION_EXACT_RECEIPT_AND_MEMBERS')
        header,tag=authenticate(z,asset,key)
        with z.open(asset['name']) as source:
            plain_stream=AuthenticatedStream(source,asset,key,header,tag)
            with tarfile.open(fileobj=plain_stream,mode='r|gz') as tar:
                first=tar.next();need(first.isfile() and first.name=='manifest.json' and first.size<2*1024**2,
                                     'RECONSTRUCTION_ADMISSION_FIRST_MANIFEST')
                raw_manifest=tar.extractfile(first).read()
                need(hashlib.sha256(raw_manifest).hexdigest()==asset['manifest_sha256'],
                     'RECONSTRUCTION_ADMISSION_MANIFEST_BYTES')
                m=json.loads(raw_manifest);inventory=m['members']
                need(m['schema']=='research.full-system-output/1' and m['stage']=='campaign-factual-suffix'
                     and m['arm']=='P02' and int(m['run_id'])==admission['run_id'] and m['head']==admission['head']
                     and m['request_sha256']==r['request_sha256'] and m['protocol_sha256']==spec['protocol_sha256']
                     and len(inventory)==196 and sum(e['bytes'] for e in inventory.values())<2*1024**3,
                     'RECONSTRUCTION_ADMISSION_TYPED_QUALIFICATION_SCOPE_AND_BOUND')
                seen=set()
                while item:=tar.next():
                    safe_name(item.name)
                    need(item.isfile() and item.name in inventory and item.name not in seen
                         and item.size==inventory[item.name]['bytes'],'RECONSTRUCTION_ADMISSION_MEMBER_LENGTH')
                    seen.add(item.name);p=dest/item.name
                    need(p.resolve().is_relative_to(dest),'RECONSTRUCTION_ADMISSION_EXTRACTION_BOUNDARY')
                    p.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(item) as src,p.open('xb') as target:shutil.copyfileobj(src,target,1024**2)
                    need(sha256_file(p)==inventory[item.name]['sha256'],'RECONSTRUCTION_ADMISSION_MEMBER_HASH')
                need(seen==set(inventory),'RECONSTRUCTION_ADMISSION_COMPLETE_INVENTORY')
            while plain_stream.read(1024**2):pass
        (dest/'artifact-receipt.json').write_bytes(z.read('reconstruction.json'))
        (dest/'artifact-staging.json').write_bytes(z.read('full-core-staging.json'))
        (dest/'authenticated-manifest.json').write_bytes(raw_manifest)
    for name,expected in admission['qualified_reconstruction_source_sha256'].items():
        need(sha256_file(driver/name)==expected,'RECONSTRUCTION_ADMISSION_IDENTICAL_QUALIFIED_IMPLEMENTATION')
    need(json.loads((dest/'spec.json').read_bytes())==spec
         and (dest/'source-bindings.json').read_bytes()==(old/'source-bindings.json').read_bytes(),
         'RECONSTRUCTION_ADMISSION_OWN_SPEC_AND_ALL_FINANCIAL_SOURCE_BYTES')
    require_stopped(json.loads((dest/'worker-inspect.json').read_bytes()),admission['worker_identity'])
    q=json.loads((dest/'reconstruction-qualification.json').read_bytes())
    need(q['status']=='EXACT_NEXT_TRANSITION_EQUAL' and not q['selected_for_economic_use']
         and q['predecessor']==spec['outer_sha256'] and compare_stopped_books(dest/'cold',dest/'bounded',
             driver/'system_campaign_resume_qualification.py',
             admission['qualified_reconstruction_source_sha256']['system_campaign_resume_qualification.py'])==q['comparison'],
         'RECONSTRUCTION_ADMISSION_ACTUAL_NEXT_CHECKPOINT_AND_STREAM_EQUALITY')
    need(q['probes']['COLD']['buffer_fingerprints']==q['probes']['BOUNDED']['buffer_fingerprints']
         and q['probes']['COLD']['published_fingerprint']==q['probes']['BOUNDED']['published_fingerprint']
         and all(p['original_checkpoint_sha256']==spec['outer_sha256'] and p['original_completed']==986
                 and p['completed']==987 and p['next_session']==admission['next_session']
                 and len(p['actual_material_falsifiers'])==7 and p['qualification_only_not_economic_predecessor']
                 for p in q['probes'].values()),'RECONSTRUCTION_ADMISSION_ACTUAL_COMPLETE_MATERIAL_PROOF')
    target=preserve_members(dest,out,m,admission,spec,old)
    review_raw=admission['independent_review_raw_utf8'].encode('utf8')
    need(hashlib.sha256(review_raw).hexdigest()==admission['independent_review_sha256']
         and json.loads(review_raw)==admission['independent_review']
         and admission['independent_review']['status']=='QUALIFICATION_INDEPENDENTLY_REVIEWED'
         and admission['independent_review']['predecessor_checkpoint_sha256']==spec['outer_sha256']
         and admission['independent_review']['each_new_row_matches_original_unsent_oracle'],
         'RECONSTRUCTION_ADMISSION_EXACT_EXTERNAL_INDEPENDENT_REVIEW')
    (target/'independent-review.json').write_bytes(review_raw)
    proof=dict(schema='research.exact-reconstruction-economic-admission/1',status='QUALIFIED_RECONSTRUCTION_ADMITTED',
        qualification_run_id=admission['run_id'],predecessor_outer_sha256=spec['outer_sha256'],
        predecessor_session=spec['selected_session'],next_session=admission['next_session'],
        exact_buffer_fingerprints=q['probes']['COLD']['buffer_fingerprints'],
        exact_next_publication_fingerprint=q['probes']['COLD']['published_fingerprint'],
        qualification_state_never_adopted=True,production_contacted=False)
    save(out/'reconstruction-admission.json',proof);return proof


class FirstMaterial:
    """Verify the actual financial restart before its first runtime.advance call."""
    def __init__(self,proof,out):self.proof=proof;self.out=out;self.buffers=[];self.published=False
    def __enter__(self):
        hosted()
        from system_campaign_resume_qualification import fingerprint
        from system_campaign_resume_window import exact_buffer,plain
        from research.pooled_input_support.adapter import Buffer
        self.Buffer=Buffer;self.append=Buffer.append;self.prepare=Buffer.prepare
        def append(buffer,packet):
            value=self.append(buffer,packet)
            if packet.day in self.proof['exact_buffer_fingerprints']:
                need(packet.day not in self.buffers and fingerprint(exact_buffer(buffer))==
                     self.proof['exact_buffer_fingerprints'][packet.day],
                     'RECONSTRUCTION_ACTUAL_RESTART_AND_NEXT_BUFFER_MATCH_QUALIFICATION')
                self.buffers.append(packet.day)
            return value
        def prepare(buffer,*args,**kwargs):
            value=self.prepare(buffer,*args,**kwargs)
            if not self.published:
                need(value.session==self.proof['next_session'] and len(self.buffers)==2
                     and fingerprint(plain(value))==self.proof['exact_next_publication_fingerprint'],
                     'RECONSTRUCTION_ACTUAL_FIRST_PUBLICATION_BEFORE_FINANCIAL_ADVANCE')
                self.published=True
                save(self.out/'reconstruction-actual-first-material.json',dict(status='EXACT_QUALIFIED_MATERIAL',
                    buffers=self.buffers,next_session=value.session,financial_advance_not_yet_called=True))
            return value
        Buffer.append=append;Buffer.prepare=prepare;return self
    def __exit__(self,kind,error,traceback):
        self.Buffer.append=self.append;self.Buffer.prepare=self.prepare
        if error is None:need(self.published,'RECONSTRUCTION_ACTUAL_FIRST_MATERIAL_REQUIRED')
