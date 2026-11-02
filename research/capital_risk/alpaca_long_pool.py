"""Disjoint canonical source admission; no Core/controller state in workers."""
from collections import Counter
import copy
import multiprocessing
import os
import time

from alpaca_fit_inputs import Inputs,need,hosted

_STATIC=None


def chunks(sids,size=128):
    need(sids==sorted(set(sids)) and size==128,'LONG_POOL_SORTED_UNIQUE_IDS')
    return [tuple(sids[i:i+size]) for i in range(0,len(sids),size)]


def _admit(task):
    days,ids=task
    need(_STATIC is not None and _STATIC._admission_pool is None,'LONG_POOL_STATIC_ONLY')
    local=copy.copy(_STATIC);local.sids=list(ids)
    return Inputs.admitted(local,list(days))


class AdmissionPool:
    def __init__(self,data):
        hosted();need(os.name=='posix' and os.environ.get('ALPACA_LONG_HOSTED')=='1','LONG_POOL_HOSTED_FORK')
        need(getattr(data,'_admission_pool',None) is None and not any(hasattr(data,k) for k in
            ('wealth_core','owned_impairment','controller_states','portfolio','ledger')),'LONG_POOL_NO_FINANCIAL_STATE')
        global _STATIC
        data.values.flags.writeable=False;data.present.flags.writeable=False
        _STATIC=copy.copy(data);_STATIC._admission_pool=None
        self.groups=chunks(data.sids);self.pool=multiprocessing.get_context('fork').Pool(processes=3)
        self.proofs=[];self.qualified_lengths=set();self.closed=False

    def admitted(self,data,days):
        need(not self.closed and len(days) in (299,300),'LONG_POOL_WINDOW')
        started=time.monotonic();results=self.pool.map(_admit,[(tuple(days),ids) for ids in self.groups],chunksize=1)
        admitted={};reasons=Counter()
        for found,why in results:
            need(not (set(found)&set(admitted)),'LONG_POOL_DISJOINT_RESULTS')
            admitted.update(found);reasons.update(why)
        actual=(dict(sorted(admitted.items())),dict(sorted(reasons.items())))
        elapsed=time.monotonic()-started
        if len(days) not in self.qualified_lengths:
            before=time.monotonic();reference=Inputs.admitted(data,days);serial=time.monotonic()-before
            need(actual==reference,'LONG_POOL_COMPLETE_CANONICAL_ADMISSION_EQUALITY')
            self.proofs.append({'first_session':days[0],'session':days[-1],'sessions':len(days),
                'pool_seconds':elapsed,'serial_seconds':serial,'complete_admission_and_reasons_equal':True,
                'qualified_security_ids':len(data.sids),'workers':3,'financial_state_passed_to_workers':False})
            self.qualified_lengths.add(len(days))
        return actual

    def close(self):
        if self.closed:return
        self.pool.close();self.pool.join();self.closed=True
