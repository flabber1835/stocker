"""Original V discovery with sufficient existing signal material retained."""
import argparse,ast,json
from pathlib import Path
from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import digest
from system_campaign_parallel_discovery import specification,check_parent,compile_body
import system_campaign_parallel_discovery_run as original
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_volatility_discovery_gate import qualify

ARMS=('P10','P11')
CODE='REFUSED_VOLATILITY_CAUSAL_AXIS'

def diagnostic_tree():
    fn=original.diagnostic_tree();calls=[]
    for node in ast.walk(fn):
        if isinstance(node,ast.Call) and ast.unparse(node.func)=='Execution':
            need(ast.unparse(node)=="Execution('FAST', signal_closes=1)",
                 'V_RETENTION_EXACT_OLD_DISCOVERY_EXECUTION')
            node.keywords[0].value=ast.Constant(127);calls.append(node)
    need(len(calls)==1,'V_RETENTION_ONE_DISCOVERY_CONFIGURATION_SITE')
    return fn

def main(args):
    hosted();need(args.arm in ARMS,'V_RETENTION_ONLY_TWO_UNSTARTED_V_ARMS')
    if args.mode=='discovery':
        fn=ast.parse(Path(original.__file__).read_bytes())
        fn,=[n for n in fn.body if isinstance(n,ast.FunctionDef) and n.name=='main']
        return compile_body(fn,dict(vars(original),diagnostic_tree=diagnostic_tree))(args)
    from research.pooled_vacancy_funding import journal,runtime
    spec=specification(args.arm);need(json.loads(args.spec.read_bytes())==spec,'V_RETENTION_EXACT_OWN_SPEC')
    root,out=Path('/old'),Path('/out')
    parent=require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    check_parent(parent,spec)
    with original.retained_inputs(root,parent,out):
        run=runtime.restore(parent['run'],policy=parent['base']['policy'],input_sha256=parent['run']['input_sha256'])
        need(runtime.checkpoint(run)==parent['run'],'V_RETENTION_OWN_CANONICAL_PARENT_ROUNDTRIP')
        with original.Anchors(out,run.state,source_sha256=digest(parent['base']['sources']),
                input_sha256=parent['run']['input_sha256'],expected_adapter_sha256=
                parent['base']['sources']['research/pooled_input_support/adapter.py']) as anchors:
            qualify(root,parent,out,selected_file=spec['selected_checkpoint'],
                    source_iterator=original.iterator(anchors),code=CODE)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    p.add_argument('--mode',choices=('qualify','discovery'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
