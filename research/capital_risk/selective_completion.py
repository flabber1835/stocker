"""Hosted completion only: admitted H0 controls, first P2 and exact suffix proofs."""
import argparse,hashlib,json,os,time
from pathlib import Path
from fractions import Fraction as Q
from selective_input import Source
from selective_model import Runtime
from selective_screen import run_book,verify_retained,canonical_bindings,all_metrics,BOUNDARY
from selective_journal import encode,digest,load
from holding_account import need

def restore_exact(path,source_sha,canonical,enabled):
    cp=load(path);runtime=Runtime(source_sha,canonical,enabled=enabled,checkpoint=cp['runtime'])
    need(runtime.checkpoint()==cp['runtime'],'REFUSED_COMPLETION_OWN_CANONICAL_RESTORE')
    return cp

def admitted_controls(root,source_sha,canonical):
    h=restore_exact(root/'comparison/H0/checkpoint.json.gz',source_sha,canonical,None)
    d=restore_exact(root/'comparison/H0-disabled/checkpoint.json.gz',source_sha,canonical,False)
    boundary=restore_exact(root/'comparison/H0/restart-boundary.json.gz',source_sha,canonical,None)
    hs=json.loads((root/'comparison/H0/book-summary.json').read_bytes());ds=json.loads((root/'comparison/H0-disabled/book-summary.json').read_bytes())
    need(hs['records']==ds['records']==4639 and hs['last_session']==ds['last_session']=='2026-07-31'
        and hs['finance_path_sha256']==ds['finance_path_sha256'] and hs['events']==ds['events'],'REFUSED_COMPLETION_CONTROL_PATH')
    need({k:v for k,v in h['runtime'].items() if k!='policy_enabled'}==
         {k:v for k,v in d['runtime'].items() if k!='policy_enabled'},'REFUSED_COMPLETION_FULL_CONTROL_STATE')
    need(boundary['runtime']['session']==BOUNDARY and not (root/'comparison/P2').exists(),'REFUSED_COMPLETION_BOUNDARY_OR_PRIOR_P2')
    return hs,h['runtime'],boundary

def main():
    parser=argparse.ArgumentParser()
    for n in ('root','bundle','qualified','controls','output','protocol'):parser.add_argument('--'+n,type=Path,required=True)
    a=parser.parse_args();need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_COMPLETION')
    a.output.mkdir(exist_ok=False);started=time.perf_counter();plan=json.loads(a.protocol.read_bytes())
    source=Source(a.root,a.bundle,a.qualified,a.output);source.last_formation_global=list(source.rows())[125]['economics']['pending_allocation']
    canonical,bindings=canonical_bindings(source)
    source_sha=digest(dict(protocol=hashlib.sha256(a.protocol.read_bytes()).hexdigest(),
        sources={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in plan['account_sources']},
        canonical=bindings,original_input=source.input_sha256))
    original_bindings=json.loads((a.controls/'comparison/source-bindings.json').read_bytes())
    need(original_bindings==dict(source_sha256=source_sha,canonical=bindings,original_base=source.base,original_input=source.input_sha256),'REFUSED_CHANGED_FINANCIAL_SOURCE_IDENTITY')
    need(hashlib.sha256((a.output/'identity/identity-bindings.jsonl').read_bytes()).hexdigest()==
        hashlib.sha256((a.controls/'comparison/identity/identity-bindings.jsonl').read_bytes()).hexdigest(),'REFUSED_CHANGED_EPISODE_BINDINGS')
    (a.output/'source-bindings.json').write_bytes(encode(original_bindings)+b'\n')
    hs,hfinal,hboundary=admitted_controls(a.controls,source_sha,canonical)
    lineage=a.output/'control-lineage';lineage.mkdir()
    (lineage/'H0-boundary.json.gz').write_bytes((a.controls/'comparison/H0/restart-boundary.json.gz').read_bytes())
    admission=dict(status='EXISTING_COMPLETE_FINANCIAL_CONTROLS_ADMITTED',original_run=40719685611,
        original_wallclock_gate='FAILED_PRESERVED_OWNER_AMENDMENT_ACCEPTS_COMPLETED_FINANCIAL_EVIDENCE',
        financial_fields_exact=True,canonical_final_and_boundary_restores=True,source_identity_unchanged=True,
        H0=hs,H0_original_prefix=hboundary['journals'],P2_prior_origin_absent=True,neutral_accounts_replayed=0)
    (a.output/'control-admission.json').write_bytes(encode(admission)+b'\n')
    # Original, unchanged financial implementation. The completion code only sequences it.
    p2,p2v,p2boundary=run_book(source,canonical,a.output/'P2',source_sha,enabled=True)
    verify_retained(a.output/'P2',source_sha,canonical,True)
    restarts={}
    for arm,boundary,suffix_sha,final in [('H0',hboundary,hs['suffix_finance_sha256'],hfinal),
                                        ('P2',p2boundary,p2['suffix_finance_sha256'],p2['final'])]:
        restored,_,_=run_book(source,canonical,a.output/(arm+'-restored-suffix'),source_sha,
            enabled=True if arm=='P2' else None,boundary=boundary,checkpoints=False)
        need(restored['finance_path_sha256']==suffix_sha and restored['final']==final,'REFUSED_COMPLETION_SERIALIZED_SUFFIX')
        restarts[arm]=dict(boundary=BOUNDARY,preserved_prefix=boundary['journals'],suffix_sha256=suffix_sha,full_final_state_equal=True)
    import csv,gzip
    with gzip.open(a.controls/'comparison/H0/daily.jsonl.gz','rt') as f:h0v=[(r['session'],r['finance']['nav']) for r in map(json.loads,f)]
    with gzip.open(a.bundle/'benchmark.csv.gz','rt') as f:spy={r['session']:r['level'] for r in csv.DictReader(f) if r['ticker']=='SPY'}
    spyv=[(day,str(Q(50000)*Q(spy[day])/Q(spy['2008-02-22']))) for day,_ in h0v]
    blocks=all_metrics(dict(H0=h0v,P2=p2v,SPY=spyv));full=blocks['full'];growth=full['P2']['cagr']-full['H0']['cagr']
    improvement=Q(full['H0']['maximum_drawdown_magnitude'])-Q(full['P2']['maximum_drawdown_magnitude'])
    treatment=any(t['stress_window'] for t in p2['treatments'])
    verdict='STRICT_JOINT_IMPROVEMENT' if growth>1e-10 and improvement>Q('1e-10') else 'REJECT_P2_FOR_JOINT_OBJECTIVE'
    if not treatment:verdict='NO_ADDITIONAL_FUNDED_STRESS_TREATMENT_UNINFORMATIVE'
    result=dict(schema='research.selective-comparison-result/1',status='H0_P2_COMPARISON_COMPLETE',verdict=verdict,
        joint_loss=max(-growth/.01,-float(improvement)/.05),additional_funded_stress_treatment=treatment,
        source_sha256=source_sha,canonical_source_bindings=bindings,formation_records=126,measured_records=4639,
        months=sum(k.startswith('month_') for k in blocks),metrics=blocks,restarts=restarts,treatments=p2['treatments'],
        reused_control_run=40719685611,neutral_accounts_replayed=0,total_processing_seconds=time.perf_counter()-started,
        defensive_model='BIL_TOTAL_RETURN_FACTOR_CASH_PROXY',stock_model='PERSISTENT_FUNDED_QUANTITIES',
        old_scalar_model_equivalence=False,core_transitions_executed=0,parameter_search=False,production_contacted=False)
    (a.output/'summary.json').write_bytes(encode(result)+b'\n');print('H0_P2_COMPLETION_FINISHED')

if __name__=='__main__':main()
