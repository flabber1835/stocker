"""Hosted exact indexed diagnostic suffix; same frozen canonical run body."""
import argparse
import ast
from copy import deepcopy
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_parallel_discovery import compile_body
from system_campaign_discovery_indexed_spinoff_parent import exact,specification,validate_contents,ARMS
from system_campaign_discovery_indexed_spinoff_replay import replay
import system_campaign_discovery_suffix_run as original

REQUEST='system-campaign-discovery-indexed-spinoff-request-001.json'

def main_tree():
 fn,=[deepcopy(n) for n in ast.parse(exact(original)).body if isinstance(n,ast.FunctionDef) and n.name=='main']
 selected=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n)=="args.arm in ('P06', 'P07')"]
 need(len(selected)==1,'INDEXED_SPIN_ONE_SCOPED_CONTEXT_FACTORY_SELECTION_SITE')
 selected[0].comparators=[ast.parse(repr(ARMS),mode='eval').body]
 return ast.fix_missing_locations(fn)

def main(args):
 hosted();need(args.arm in ARMS and args.request==Path('/driver/'+REQUEST),'INDEXED_SPIN_EXACT_HOSTED_ARM_REQUEST_ENTRYPOINT')
 return compile_body(main_tree(),dict(vars(original),specification=specification,validate_contents=validate_contents,replay=replay))(args)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
 for name in ('spec','request'):p.add_argument('--'+name,type=Path,required=True)
 main(p.parse_args())
