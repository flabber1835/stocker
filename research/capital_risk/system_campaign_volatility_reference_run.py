"""Same V worker, with a source-bound reference-only qualification successor."""
import argparse,ast
from pathlib import Path

from system_campaign_parallel_discovery import compile_body
from system_campaign_volatility_reference_parent import exact_source
from system_campaign_volatility_reference_gate import qualify
import system_campaign_volatility_discovery_run as original


def main(args):
    fn,=[n for n in ast.parse(exact_source(original)).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    return compile_body(fn,dict(vars(original),qualify=qualify))(args)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=original.ARMS,required=True)
    p.add_argument('--mode',choices=('qualify','discovery'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
