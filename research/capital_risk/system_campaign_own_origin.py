"""Retain an already qualified ORIGINAL origin as evidence, never as resume state."""
import gzip,hashlib,json,shutil
from pathlib import Path
from full_system_benchmark import need,save
from system_campaign_facts import sha


def capture(reference,old,out):
    from probe import check_context
    import os
    check_context(os.environ)
    need((reference/'source-bindings.json').read_bytes()==(old/'source-bindings.json').read_bytes()
         and (reference/'book/identity.json').read_bytes()==(old/'book/identity.json').read_bytes(),
         'OWN_ORIGIN_EXACT_SAME_SOURCE_AND_BOOK')
    paths=list(reference.rglob('origin-admission.json'));need(paths,'OWN_ORIGIN_ACTUAL_RETAINED_ADMISSION')
    identities=[json.loads(p.read_bytes()) for p in paths]
    need(len({v['outer_sha256'] for v in identities})==len({v['state_sha256'] for v in identities})==1,
         'OWN_ORIGIN_UNIQUE_ORIGINAL_FEATURE_STATE')
    identity=identities[0];need(identity['schema']=='research.full-system-own-origin/1','OWN_ORIGIN_ACTUAL_ADMISSION_SCHEMA')
    cp_paths=list(reference.rglob(identity['outer_sha256']+'.json.gz'));need(cp_paths,'OWN_ORIGIN_RETAINED_GZIP')
    raw=cp_paths[0].read_bytes();cp=json.loads(gzip.decompress(raw));selected=json.loads(gzip.decompress((old/'book/checkpoint.json.gz').read_bytes()))
    need(sha(raw)==identity['outer_file_sha256'] and cp['sha256']==identity['outer_sha256']
         and cp['run']['state_sha256']==identity['state_sha256'] and cp['base']==selected['base']
         and cp['completed']==0 and cp['run']['state']['last_processed_session'] is None
         and identity['canonical_roundtrip'] and identity['all_four_prefixes_empty_verified'],
         'OWN_ORIGIN_ACTUAL_ORIGINAL_ZERO_FINANCIAL_BINDING')
    need(cp['source_cursor']==identity['resume_session']=='2017-06-30'
         and set(cp['journals'])=={'formation','daily','monthly','watch'}
         and all(c['bytes']==0 and c['prefix_sha256']==sha(b'') for c in cp['journals'].values()),
         'OWN_ORIGIN_ACTUAL_EMPTY_PREFIXES_BEFORE_FORMATION')
    dest=out/'lineage/original-own-origin';dest.mkdir(parents=True)
    shutil.copyfile(paths[0],dest/'origin-admission.json');(dest/(identity['outer_sha256']+'.json.gz')).write_bytes(raw)
    save(dest/'preservation.json',{'original_gzip_sha256':sha(raw),'original_admission_sha256':sha(paths[0].read_bytes()),
        'original_outer_sha256':identity['outer_sha256'],'financial_resume_checkpoint_unchanged':True,
        'new_origin':False,'source_conversion':False})


def qualify(evidence,selected,output):
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,runtime,journal
    from research.pooled_input_support.bundle import axis
    root=evidence/'lineage/original-own-origin';identity=json.loads((root/'origin-admission.json').read_bytes())
    path=root/(identity['outer_sha256']+'.json.gz');cp=journal.read_checkpoint(path)
    need(sha(path.read_bytes())==identity['outer_file_sha256'] and cp['base']==selected['base']
         and cp['base']['sources']==backtest.source_files() and cp['sha256']==identity['outer_sha256']
         and cp['run']['state_sha256']==identity['state_sha256'] and cp['run']['input_sha256']==identity['input_sha256']
         and cp['completed']==0 and cp['run']['state']['last_processed_session'] is None,
         'OWN_ORIGIN_ORIGINAL_SOURCE_STATE_INPUT')
    need(cp['source_cursor']==identity['resume_session']=='2017-06-30'
         and all(c['bytes']==0 and c['prefix_sha256']==sha(b'') for c in cp['journals'].values()),
         'OWN_ORIGIN_ZERO_COMMITTED_FINANCIAL_PREFIXES')
    full=axis();wanted=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
    backtest.validate_checkpoint(cp,cp['base'],wanted)
    state=runtime.restore(cp['run'],policy=cp['base']['policy'],input_sha256=backtest.input_hash(cp['base'],cp['repairs']))
    need(runtime.checkpoint(state)==cp['run'],'OWN_ORIGIN_ACTUAL_CANONICAL_ZERO_SESSION_ROUNDTRIP')
    save(output,{'source_outer_sha256':cp['sha256'],'source_gzip_sha256':sha(path.read_bytes()),
        'original_own_zero_session_origin_restored':True,'financial_resume_outer_sha256':selected['sha256'],
        'origin_used_as_financial_resume':False,'financial_sessions_advanced':0,'new_warmup_or_book':False})
