"""Build one hash-bound funded request from actual stopped client admissions."""
import argparse
import hashlib
import json
from pathlib import Path
from alpaca_fit_prepare import source_inventory
from alpaca_fit_inputs import need


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def admitted(folder,*,funded=False):
    folder=Path(folder);receipt=json.loads((folder/'download'/('alpaca-funded.json' if funded else 'alpaca-fit-baseline.json')).read_bytes())
    client=json.loads((folder/'verified/admission.json').read_bytes())
    audit=json.loads((folder/'verified/full/stopped-independent-review/review/independent-review.json').read_bytes())
    need(client['ciphers_gcm_and_inventory_verified'] is True and client['stopped'] is True
        and client['oom'] is False and client['run_id']==int(receipt['run_id']) and client['head']==receipt['head'],'FUNDED_ACTUAL_CLIENT_ADMISSION')
    inspector=json.loads((folder/'verified/full/stopped-independent-review/worker-inspect.json').read_bytes())
    need(inspector['State']['Running'] is False and inspector['State']['ExitCode']==0 and inspector['State']['OOMKilled'] is False,
        'FUNDED_ACTUAL_REVIEWER_STOP')
    return receipt,audit


def artifact(folder,id_,receipt):
    p=Path(folder)/'download/artifact.zip'
    return {'id':id_,'run_id':int(receipt['run_id']),'head':receipt['head'],'bytes':p.stat().st_size,'sha256':digest(p),
        'full':receipt['encrypted_outputs']['full']}


def prepare(a):
    protocol=Path(__file__).with_name('alpaca-fit-protocol.json');p=json.loads(protocol.read_bytes());sha=digest(protocol)
    core=Path(a.core);r,audit=admitted(core);original=json.loads((core/'request.json').read_bytes());source=source_inventory()
    end=p['training_end'] if a.stage=='TRAINING' else p['data_end']
    need(audit['status'] in ('COMPLETE_TRACE_REVIEWED','PARTIAL_PREFIX_REVIEWED') and audit['last_committed_session']>=end
        and audit['uncommitted_tail_bytes']==0 and r['protocol_sha256']==sha,'FUNDED_COMPLETE_SOURCE_REQUIRED')
    request={'schema':'research.alpaca-funded-request/1','study_id':'alpaca-owned55-fit-001','request_id':a.request_id,'stage':a.stage,
        'protocol_sha256':sha,'dataset_sha256':original['dataset_sha256'],'required_core_end':end,
        'source_files':source,'input_request':original,'core_artifact':artifact(core,a.core_artifact_id,r),
        'core_independent_review_sha256':digest(core/'verified/full/stopped-independent-review/review/independent-review.json'),
        'production_contacted':False,'new_forecaster':False,'known_history_not_unseen':True}
    if a.previous:
        old=Path(a.previous);receipt,review=admitted(old,funded=True)
        need(receipt['protocol_sha256']==sha and receipt['dataset_sha256']==request['dataset_sha256']
            and review['status'] in ('COMPLETE_REVIEWED','PARTIAL_PREFIXES_REVIEWED'),'FUNDED_PREVIOUS_REVIEW')
        previous_request=json.loads((old/'request.json').read_bytes())
        from alpaca_fit_funded_book import FINANCIAL_FILES
        closure=set(FINANCIAL_FILES)|{x for x in previous_request['source_files'] if x.startswith(('sentinel/','shared/stock_strategy_shared/'))}
        need(all(source[x]==previous_request['source_files'][x] for x in closure),'FUNDED_FINANCIAL_SOURCE_UNCHANGED')
        request['previous_artifact']=artifact(old,a.previous_artifact_id,receipt)
        if a.stage=='DIAGNOSTIC':
            selected=old/'verified/full/stopped-independent-review/review/locked-selection.json'
            need(review['status']=='COMPLETE_REVIEWED' and selected.is_file(),'FUNDED_TRAINING_LOCK_REQUIRED')
            request['locked_selection_sha256']=digest(selected)
    need(a.stage!='DIAGNOSTIC' or a.previous,'DIAGNOSTIC_CANNOT_CREATE_NEW_ORIGINS')
    target=Path(a.output);need(not target.exists(),'FUNDED_REQUEST_COLLISION')
    target.write_text(json.dumps(request,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'request_sha256':digest(target),'source_files':len(source),'stage':a.stage}))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('core','output','request-id'):p.add_argument('--'+key,required=True)
    p.add_argument('--stage',choices=('TRAINING','DIAGNOSTIC'),required=True);p.add_argument('--core-artifact-id',type=int,required=True)
    p.add_argument('--previous');p.add_argument('--previous-artifact-id',type=int)
    prepare(p.parse_args())
