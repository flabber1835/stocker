"""Hosted read-only stopped-artifact diagnostics; ZERO financial execution."""
import argparse,base64,hashlib,json,os,re,shutil,subprocess,tarfile,zipfile
from pathlib import Path
from system_campaign_factual_admit import authenticate,AuthenticatedStream,hosted_destination
from full_system_benchmark import need
from probe import check_context
from seal import safe_name,sha256_file,EncryptWriter
from full_system_trials_job import seal
from stage import SECRET

HERE=Path(__file__).resolve().parent
SOURCES=('system_campaign_diagnostic_job.py','system_campaign_factual_admit.py','full_system_benchmark.py',
    'probe.py','seal.py','full_system_trials_job.py','full_system_source.py','alpaca_fit_job.py','alpaca_fit_stage.py','runtime_identity.py','stage.py')
KEEP={'economic-worker.log','worker-inspect.json','economic-worker-inspect.json','factual-preflight.json','factual-overlay-admission.json',
    'factual-input-qualification.json','factual-outcome.json','old-branch-canonical-review.json','hydrated-factual-catalog.json',
    'independent-review-stop/worker.log','independent-review-stop/worker-inspect.json','independent-review-stop/core-review.json',
    'book/checkpoint.json.gz','book/status.json','book/result.json'}


def main(a):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','NO_DIAGNOSTIC_RERUN')
    request=json.loads(a.request.read_bytes())
    need(request['schema']=='research.system-campaign-diagnostic-request/1' and request['financial_sessions']==0
         and request['sources']=={n:sha256_file(HERE/n) for n in SOURCES},'EXACT_DIAGNOSTIC_REQUEST')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'KEY')
    root=hosted_destination(Path(os.environ['RUNNER_TEMP'])/'campaign-factual-transfer-diagnostics');root.mkdir(mode=0o700)
    out=root/'output';out.mkdir(mode=0o700);proofs={}
    for arm,spec in request['arms'].items():
        archive=root/(arm+'.zip')
        need(spec['zip_bytes']<256*1024**2,'DIAGNOSTIC_ZIP_BOUND')
        with archive.open('xb') as f:subprocess.run(['gh','api',f"repos/flabber1835/stocker/actions/artifacts/{spec['artifact_id']}/zip"],stdout=f,check=True,timeout=180)
        need(archive.stat().st_size==spec['zip_bytes'] and sha256_file(archive)==spec['zip_sha256'],'DIAGNOSTIC_ZIP_SHA')
        dest=out/arm;dest.mkdir(mode=0o700);captured={}
        with zipfile.ZipFile(archive) as z:
            raw=z.read(spec['receipt_name']);need(hashlib.sha256(raw).hexdigest()==spec['receipt_sha256'],'DIAGNOSTIC_RECEIPT_SHA')
            receipt=json.loads(raw);asset=receipt['encrypted_output'];need(asset==spec['encrypted_output'] and receipt['arm']==arm
                and int(receipt['run_id'])==spec['run_id'] and receipt['head']==spec['head'] and not receipt['production_contacted'],'DIAGNOSTIC_SCOPE')
            (dest/'receipt.json').write_bytes(raw);header,tag=authenticate(z,asset,key)
            with z.open(asset['name']) as source:
                plain=AuthenticatedStream(source,asset,key,header,tag)
                with tarfile.open(fileobj=plain,mode='r|gz') as tar:
                    first=tar.next();need(first.name=='manifest.json' and first.isfile() and first.size<2*1024**2,'DIAGNOSTIC_MANIFEST')
                    raw=tar.extractfile(first).read();need(hashlib.sha256(raw).hexdigest()==asset['manifest_sha256'],'DIAGNOSTIC_MANIFEST_SHA')
                    manifest=json.loads(raw)
                    need(manifest['schema']=='research.full-system-output/1' and manifest['stage']=='campaign-factual-suffix'
                         and manifest['arm']==arm and int(manifest['run_id'])==spec['run_id'] and manifest['head']==spec['head']
                         and manifest['request_sha256']==receipt['request_sha256'] and manifest['protocol_sha256']==receipt['protocol_sha256'],'DIAGNOSTIC_MANIFEST_SCOPE')
                    inventory=manifest['members'];need(len(inventory)<5000 and sum(v['bytes'] for v in inventory.values())<1024**3,'DIAGNOSTIC_INVENTORY_BOUND')
                    (dest/'authenticated-manifest.json').write_bytes(raw);seen=set()
                    while item:=tar.next():
                        safe_name(item.name);need(item.isfile() and item.name in inventory and item.name not in seen,'DIAGNOSTIC_MEMBER');seen.add(item.name)
                        expected=inventory[item.name];need(item.size==expected['bytes'],'DIAGNOSTIC_MEMBER_LENGTH')
                        h=hashlib.sha256();count=0;target=dest/item.name;consumer=None
                        if item.name in KEEP:
                            need(item.size<8*1024**2,'DIAGNOSTIC_SELECTED_MEMBER_BOUND');target.parent.mkdir(parents=True,exist_ok=True);consumer=target.open('xb')
                        try:
                            with tar.extractfile(item) as f:
                                while raw:=f.read(1024**2):
                                    h.update(raw);count+=len(raw)
                                    if consumer is not None:consumer.write(raw)
                        finally:
                            if consumer is not None:consumer.close()
                        need(count==expected['bytes'] and h.hexdigest()==expected['sha256'],'DIAGNOSTIC_EVERY_MEMBER_SHA')
                        if item.name in KEEP:captured[item.name]=expected
                    need(seen==set(inventory),'DIAGNOSTIC_COMPLETE_INVENTORY')
                while plain.read(1024**2):pass
            proofs[arm]={'source_run_id':spec['run_id'],'source_head':spec['head'],'artifact_id':spec['artifact_id'],
                'complete_gcm_inventory_authenticated':True,'selected':captured,'financial_sessions_advanced':0}
            safe={}
            for name in ('economic-worker.log','independent-review-stop/worker.log'):
                if not (dest/name).exists():continue
                log=(dest/name).read_text();codes=re.findall(r'\bREFUSED_[A-Z_]+\b',log)
                locations=re.findall(r'File "/driver/([a-z_]+\.py)", line ([0-9]+), in ([a-z_]+)',log)
                safe[name]={'error_codes':list(dict.fromkeys(codes)),'driver_locations':locations[-5:]}
            print(json.dumps({'arm':arm,'authenticated_stopped_artifact_diagnostics':safe,'financial_sessions_advanced_by_reader':0}),flush=True)
    os.environ.pop('GH_TOKEN',None)
    (out/'diagnostic-proof.json').write_text(json.dumps(proofs,indent=2)+'\n')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    asset=seal(out,a.output.parent/'campaign-diagnostics.tar.crseal',key,a.request,'DIAGNOSTIC',stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;receipt={'schema':'research.system-campaign-diagnostic-receipt/1','run_id':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],
        'request_sha256':sha256_file(a.request),'protocol_sha256':request['protocol_sha256'],'status':'COMPLETE_READ_ONLY_DIAGNOSTICS',
        'arms':list(proofs),'financial_sessions_advanced':0,'production_contacted':False,'encrypted_output':asset}
    a.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
