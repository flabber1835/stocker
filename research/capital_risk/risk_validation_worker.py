"""Exact selected-candidate suffix only, under its unchanged financial identity."""
import argparse,hashlib,json,os
from pathlib import Path
from risk_profiles import selected
from risk_adapter import install,identity
from selective_input import Source
from selective_screen import canonical_bindings,run_book,BOUNDARY
from selective_journal import encode,load
from holding_account import need

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True)
    for n in ('actual','root','bundle','qualified','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_SELECTED_VALIDATION');profile=selected(a.profile)
    a.output.mkdir(exist_ok=False);source=Source(a.root,a.bundle,a.qualified,a.output);source.last_formation_global=list(source.rows())[125]['economics']['pending_allocation']
    canonical,bindings=canonical_bindings(source);Runtime=install(profile);source_sha=identity(profile,bindings,source.input_sha256)
    actual=json.loads((a.actual/'source-bindings.json').read_bytes());need(source_sha==actual['source_sha256'] and actual['binding']['profile']==profile.model_dump(mode='json'),'REFUSED_CHANGED_SELECTED_PROFILE_SOURCE')
    boundary_path=a.actual/'book/restart-boundary.json.gz';boundary=load(boundary_path);final=load(a.actual/'book/checkpoint.json.gz')['runtime']
    restored=Runtime(source_sha,canonical,enabled=True,checkpoint=boundary['runtime']);need(restored.checkpoint()==boundary['runtime'] and boundary['runtime']['session']==BOUNDARY,'REFUSED_SELECTED_OWN_BOUNDARY')
    lineage=a.output/'lineage';lineage.mkdir();(lineage/'original-boundary.json.gz').write_bytes(boundary_path.read_bytes())
    result,_,_=run_book(source,canonical,a.output/'suffix',source_sha,enabled=True,boundary=boundary,checkpoints=False)
    original=json.loads((a.actual/'book/book-summary.json').read_bytes());need(result['finance_path_sha256']==original['suffix_finance_sha256'] and result['final']==final,'REFUSED_SELECTED_COMPLETE_SUFFIX_EQUIVALENCE')
    proof=dict(status='SELECTED_EXACT_SUFFIX_PASSED',profile_id=profile.id,source_sha256=source_sha,boundary=BOUNDARY,
        original_boundary_sha256=hashlib.sha256(boundary_path.read_bytes()).hexdigest(),preserved_prefixes=boundary['journals'],
        suffix_financial_rows_sha256=result['finance_path_sha256'],suffix_records=result['records'],complete_final_runtime_equal=True,
        original_main_path_replayed=False,production_contacted=False)
    (a.output/'proof.json').write_bytes(encode(proof)+b'\n');print('SELECTED_SUFFIX_VALIDATION_FINISHED')

if __name__=='__main__':main()
