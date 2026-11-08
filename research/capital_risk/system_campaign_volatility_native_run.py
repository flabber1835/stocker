"""Exact native V transport plus the shared immutable anchor-proof writer."""
import argparse,ast
from pathlib import Path
from full_system_benchmark import need
from system_campaign_parallel_discovery import compile_body
from system_campaign_volatility_native_parent import original_bytes
from system_campaign_volatility_native_transport import profile
from system_campaign_volatility_native_gate import qualify
from system_campaign_anchor_proofs import AnchorQualification
import system_campaign_volatility_discovery_run as original


def diagnostic_tree():
    fn=original.diagnostic_tree();sites=[]
    for n in ast.walk(fn):
        if isinstance(n,ast.Call) and ast.unparse(n.func)=='Execution':
            need(ast.unparse(n)=="Execution('FAST', signal_closes=127)",'V_NATIVE_ONE_OLD_DIAGNOSTIC_CONFIGURATION')
            n.keywords[0].value=ast.Constant(profile()['signal_closes']);sites.append(n)
    need(len(sites)==1,'V_NATIVE_ONLY_ONE_DIAGNOSTIC_TRANSPORT_SITE')
    cp,=[n for n in ast.walk(fn) if isinstance(n,ast.FunctionDef) and n.name=='checkpoint']
    at,=[i for i,n in enumerate(cp.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
          and ast.unparse(n.value.func)=='journal.write_checkpoint']
    cp.body[at:at]=ast.parse('value.update(retained_anchor_qualifications=anchor_gate.commitment())').body
    return ast.fix_missing_locations(fn)


def worker_tree():
    fn,=[n for n in ast.parse(original_bytes(original)).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    namespace=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='dict'
               and len(n.args)==1 and ast.unparse(n.args[0])=='vars(original)'
               and [k.arg for k in n.keywords]==['diagnostic_tree']]
    need(len(namespace)==1,'V_NATIVE_ONE_SHARED_PROOF_WRITER_NAMESPACE_SITE')
    namespace[0].keywords.append(ast.keyword(arg='AnchorQualification',value=ast.Name(id='AnchorQualification',ctx=ast.Load())))
    return ast.fix_missing_locations(fn)


def main(args):
    return compile_body(worker_tree(),dict(vars(original),qualify=qualify,
        diagnostic_tree=diagnostic_tree,AnchorQualification=AnchorQualification))(args)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=original.ARMS,required=True)
    p.add_argument('--mode',choices=('qualify','discovery'),required=True)
    p.add_argument('--spec',type=Path,required=True);main(p.parse_args())
