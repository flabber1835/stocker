"""One hosted profile, original financial operations and full retained proofs."""
import argparse,hashlib,json,os,time
from pathlib import Path
from risk_profiles import selected
from risk_adapter import install,identity,source_binding
from selective_input import Source
from selective_screen import canonical_bindings,run_book,verify_retained
from selective_journal import encode

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True)
    for n in ('root','bundle','qualified','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    if os.environ.get('HOLDING_QUAL_HOSTED')!='1':raise ValueError('REFUSED_LOCAL_RISK_SEARCH')
    profile=selected(a.profile);a.output.mkdir(exist_ok=False);started=time.perf_counter()
    source=Source(a.root,a.bundle,a.qualified,a.output);source.last_formation_global=list(source.rows())[125]['economics']['pending_allocation']
    canonical,bindings=canonical_bindings(source)
    if profile.family=='ORACLE_H0':
        from risk_gate import run
        run(canonical,a.output/'architecture-gate.json')
    Runtime=install(profile);source_sha=identity(profile,bindings,source.input_sha256)
    binding=source_binding(profile,bindings,source.input_sha256);(a.output/'source-bindings.json').write_bytes(encode(dict(source_sha256=source_sha,binding=binding))+b'\n')
    enabled=None if profile.family=='ORACLE_H0' else True
    result,values,boundary=run_book(source,canonical,a.output/'book',source_sha,enabled=enabled)
    proof=verify_retained(a.output/'book',source_sha,canonical,enabled)
    # Cross-profile and changed-source restores must refuse the actual checkpoint.
    checkpoint=result['final'];bad={**checkpoint,'source_sha256':'0'*64};refused=False
    try:Runtime('1'*64,canonical,enabled=enabled,checkpoint=bad)
    except ValueError:refused=True
    if not refused:raise ValueError('REFUSED_SEARCH_RESTORE_FALSIFIER')
    summary=dict(status='SEARCH_PROFILE_FINISHED_REVIEW_REQUIRED',profile=profile.model_dump(mode='json'),
        source_sha256=source_sha,records=result['records'],formation=result['formation']['records'],end=result['last_session'],
        retained_checkpoints=proof['checkpoints'],actual_wrong_source_restore_refused=True,processing_seconds=time.perf_counter()-started,
        core_transitions_executed=0,production_contacted=False)
    (a.output/'summary.json').write_bytes(encode(summary)+b'\n');print('BOUNDED_RISK_PROFILE_FINISHED')

if __name__=='__main__':main()
