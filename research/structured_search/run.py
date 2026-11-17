"""Execute and audit the frozen offline search without touching the Core path."""
import argparse
import json
from pathlib import Path
import sys
import traceback

from research.exposure_oracle import inputs
from . import audit, diagnostics, engine, report


def run(snapshot,output):
    from sentinel.core.kernel import advance_session
    code=advance_session.__code__; calls=0
    previous=sys.getprofile()
    def forbid(frame,event,arg):
        nonlocal calls
        if event=='call' and frame.f_code is code:
            calls+=1
            raise RuntimeError('Structured exposure research must not advance Wealth Core')
    sys.setprofile(forbid)
    try:
        result=engine.run(snapshot,output)
        print(json.dumps(dict(status='ROBUSTNESS_AND_ATTRIBUTION')),flush=True)
        diagnostics.assess(*result,output)
        print(json.dumps(dict(status='INDEPENDENT_AUDIT')),flush=True)
        proof=audit.run(snapshot,output)
        qa=report.write(snapshot,output)
        inputs.write_json(output/'status.json',dict(status='COMPLETE',audit=proof,report=qa))
        print(json.dumps(dict(status='COMPLETE',audit=proof,report=qa)),flush=True)
    except BaseException as error:
        if output.is_dir():
            inputs.write_json(output/'failure.json',dict(error=repr(error),traceback=traceback.format_exc()))
            inputs.write_json(output/'status.json',dict(status='FAILED',error=repr(error)))
        raise
    finally:
        sys.setprofile(previous)
        if output.is_dir(): inputs.write_json(output/'core-preservation.json',dict(
            canonical_core_transition_calls=calls,status='PASS' if calls==0 else 'FAIL',
            guarded_function='sentinel.core.kernel.advance_session'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    run(args.snapshot,args.output)
