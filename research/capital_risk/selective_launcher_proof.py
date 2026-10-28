"""Hosted synthetic proof only; never advances a historical financial account."""
from pathlib import Path
import gzip,hashlib,json,os
from selective_journal import encode
from holding_account import need

def main():
    need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_LAUNCHER_PROOF')
    from stock_strategy_shared.wealth_core import terminal,shares
    from sentinel.breadth import classifier
    from selective_gate import run
    from selective_input import admitted_source_hash
    cp=json.loads(gzip.decompress(Path('/frozen/baseline-comparison/checkpoint.json.gz').read_bytes()));sources=cp['base']['sources'];del cp
    bindings={}
    for m in (terminal,shares,classifier):
        p=Path(m.__file__);rel=str(p).removeprefix('/fixed/');h=hashlib.sha256(p.read_bytes()).hexdigest()
        need(str(p).startswith('/fixed/') and admitted_source_hash(Path('/frozen/baseline-comparison'),sources,rel)==h,'PROOF_FROZEN_CANONICAL_SOURCE');bindings[rel]=h
    out=Path('/out/proof');out.mkdir(exist_ok=False)
    result=run(dict(terminal=terminal,shares=shares,classifier=classifier),out/'composed-gate.json')
    try:Path('/qualified/forbidden-write').write_text('FORBIDDEN')
    except OSError as exc:need(exc.errno in (13,30),'PROOF_UNEXPECTED_WRITE_ERROR');readonly=True
    else:raise AssertionError('QUALIFIED_MOUNT_WRITABLE')
    marker=b'SYNTHETIC_H0P2_LAUNCHER_EXPORT_PROOF\n';(out/'marker.txt').write_bytes(marker)
    summary=dict(status='SYNTHETIC_LAUNCHER_PROOF_PASSED',composed_cases=len(result['cases']),qualified_mount_readonly=readonly,
        marker_sha256=hashlib.sha256(marker).hexdigest(),marker_bytes=len(marker),canonical_source_bindings=bindings,
        historical_financial_accounts_started=0,P2_historical_trial_started=False,production_contacted=False)
    (out/'summary.json').write_bytes(encode(summary)+b'\n');print('SYNTHETIC_LAUNCHER_PROOF_FINISHED')
if __name__=='__main__':main()
