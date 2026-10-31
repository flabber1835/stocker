"""Observe exact replay work; no cached validation or altered return values."""
import time
from full_system_benchmark import save
from full_system_core import hosted


def timed_items(original,observe):
    """Preserve item/error identity while excluding time in the consumer."""
    iterator=iter(original)
    try:
        while True:
            start=time.perf_counter()
            try:item=next(iterator)
            except StopIteration:
                observe(time.perf_counter()-start,False,False);return
            except BaseException:
                observe(time.perf_counter()-start,False,True);raise
            observe(time.perf_counter()-start,True,False)
            yield item
    finally:
        close=getattr(iterator,'close',None)
        if close is not None:close()


class ReplayTiming:
    def __init__(self,out):self.out=out;self.metrics={};self.originals=[]

    def observe(self,name,seconds,item=True,error=False):
        row=self.metrics.setdefault(name,dict(seconds=0.,calls=0,errors=0))
        row['seconds']+=seconds;row['calls']+=int(item);row['errors']+=int(error)

    def wrap(self,owner,name,label):
        original=getattr(owner,name);self.originals.append((owner,name,original))
        def observed(*args,**kwargs):
            start=time.perf_counter();failed=False
            try:return original(*args,**kwargs)
            except BaseException:failed=True;raise
            finally:self.observe(label,time.perf_counter()-start,error=failed)
        setattr(owner,name,observed)

    def __enter__(self):
        hosted()
        from research.pooled_input_support import inputs,adapter,bundle
        from research.pooled_vacancy_funding import backtest
        for owner,name,label in ((bundle,'verify_bundle','bundle_verification'),
            (backtest,'comparisons','reference_loading_and_hashing'),
            (backtest,'source_files','source_hashing'),(adapter.Buffer,'append','buffer_append')):
            self.wrap(owner,name,label)
        original=inputs.packets;self.originals.append((inputs,'packets',original))
        def packets(*a,**kw):return timed_items(original(*a,**kw),lambda seconds,item,error:self.observe('source_packet_production',seconds,item,error))
        inputs.packets=packets
        return self

    def __exit__(self,kind,error,tb):
        for owner,name,original in reversed(self.originals):setattr(owner,name,original)
        proof=dict(schema='research.canonical-replay-work-timings/1',metrics=self.metrics,
            return_values_and_errors_unchanged=True,financial_state_read_or_edited=False,
            validation_verdict_cached=False,financial_equations_changed=False,production_contacted=False)
        try:save(self.out/'replay-work-timings.json',proof)
        except Exception as failure:
            if error is None:raise
            error.add_note('Replay timing export failed: '+type(failure).__name__)
        return False
