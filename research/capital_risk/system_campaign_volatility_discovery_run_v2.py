"""Exact V retention worker; only the observation recorder is succeeded."""
import argparse,ast
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
from system_campaign_parallel_discovery import compile_body
from system_campaign_volatility_discovery_gate_v2 import qualify,HERE,PRIOR,PRIOR_SHA
import system_campaign_volatility_discovery_run as original

def main(args):
    import json
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'V_RECORDER_EXACT_WORKER_REQUEST')
    code=Path(original.__file__).read_bytes()
    need(sha(code)==json.loads(raw)['sources'][Path(original.__file__).name],'V_RECORDER_UNCHANGED_RETENTION_WORKER')
    fn,=[n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    return compile_body(fn,dict(vars(original),qualify=qualify))(args)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=original.ARMS,required=True)
    p.add_argument('--mode',choices=('qualify','discovery'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
