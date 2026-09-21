"""Isolated, assertion-verified falsifiers for the owned protection contract."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

CASES={
    'disable_entry':('step',"active, entry, reason = True, 0, 'OWNED_IMPAIRMENT_ENTER'",
                    "active, entry, reason = False, 0, 'OWNED_IMPAIRMENT_ENTER'",
                    'test_saturated_damage_enters_on_fifth_close_without_new_shock'),
    'early_recovery':('step',"if recovery >= RULE['recovery_sessions']:", 'if recovery >= 7:',
                     'test_recovery_needs_eight_owned_healthy_closes_and_preserves_parent_ceiling'),
    'bypass_ceiling':('step','target=min(base_target, ceiling)','target=base_target',
                     'test_complete_kernel_enforces_owned_protection_with_same_core'),
    'ignore_cursor':('validate','state.last_session != expected_session','False',
                     'test_snapshot_cannot_detach_protection_from_canonical_cursor'),
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',choices=CASES)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--scratch',type=Path,default=Path(tempfile.gettempdir())/'sentinel-owned-mutations')
    args=parser.parse_args()
    if args.child:
        import pytest
        from sentinel.controller import owned_impairment as owned
        function,old,new,test=CASES[args.child]
        source=inspect.getsource(getattr(owned,function));assert source.count(old)==1
        namespace=dict(owned.__dict__)
        exec(compile(source.replace(old,new),'<owned-mutant>','exec'),namespace)
        setattr(owned,function,namespace[function])
        file='test_owned_kernel.py' if args.child=='bypass_ceiling' else 'test_owned_impairment.py'
        scratch=args.scratch/('mutation-'+uuid.uuid4().hex)
        args.scratch.mkdir(parents=True,exist_ok=True)
        return int(pytest.main([f'tests/champion/{file}::{test}','-q','-p','no:cacheprovider',
                               '--basetemp',str(scratch)]))
    if args.output is None: parser.error('--output is required')
    results=[]
    for name in CASES:
        proc=subprocess.run([sys.executable,'-m','tools.owned_impairment_mutations','--child',name,
                             '--scratch',str(args.scratch)],
                            capture_output=True,text=True,check=False)
        killed=(proc.returncode==1 and '1 failed' in proc.stdout
                and ('AssertionError' in proc.stdout or 'DID NOT RAISE' in proc.stdout))
        results.append(dict(mutant=name,killed=killed,exit_code=proc.returncode,output=proc.stdout+proc.stderr))
        print(name,'KILLED' if killed else 'NOT KILLED',flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8',newline='\n')
    return 0 if all(r['killed'] for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
