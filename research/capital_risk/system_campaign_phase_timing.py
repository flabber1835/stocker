"""Phase timings only; preserve return values, exceptions and financial behavior."""
from contextlib import contextmanager
import time
from full_system_benchmark import save


class PhaseTiming:
    def __init__(self,out,mode):
        self.out=out;self.mode=mode;self.phases=[];self.started=time.perf_counter()

    @contextmanager
    def phase(self,name):
        began=time.perf_counter();status='PASSED';error_type=None
        try:
            yield
        except BaseException as error:
            status='FAILED';error_type=type(error).__name__;raise
        finally:
            self.phases.append(dict(name=name,seconds=time.perf_counter()-began,
                                    status=status,error_type=error_type))

    def call(self,name,function,*args,**kwargs):
        with self.phase(name):return function(*args,**kwargs)

    def __enter__(self):return self

    def __exit__(self,kind,error,traceback):
        proof=dict(schema='research.exact-replay-phase-timing/1',mode=self.mode,
            total_seconds=time.perf_counter()-self.started,phases=self.phases,
            financial_equations_changed=False,financial_state_read_or_changed=False,
            exceptions_swallowed=False,production_contacted=False)
        try:save(self.out/'phase-timing.json',proof)
        except Exception as export_error:
            if error is None:raise
            error.add_note('Phase timing export failed: '+type(export_error).__name__)
        return False
