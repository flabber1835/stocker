"""Hosted canonical input-startup pause; no financial transition is permitted."""
from copy import deepcopy
from pathlib import Path
import signal

from full_system_core import hosted
from full_system_benchmark import need
from system_campaign_facts import digest,sha

UNCHANGED = ('base','source_cursor','completed','economics','stats','spy_base','retries')


def adoption(saved,original,overlay_sha256,earliest):
    need(all(saved[k]==original[k] for k in UNCHANGED),
         'PXD_ZERO_STARTUP_ALL_FINANCIAL_AND_REPORTING_VALUES_UNCHANGED')
    before,after=original['run'],saved['run']
    need({k:v for k,v in before.items() if k not in ('input_sha256','checkpoint_sha256')}
         =={k:v for k,v in after.items() if k not in ('input_sha256','checkpoint_sha256')},
         'PXD_ZERO_STARTUP_FULL_CORE_CONTROLLER_STATE_UNCHANGED')
    descriptor=dict(filename=overlay_sha256+'.json',sha256=overlay_sha256,
        resume_session=original['source_cursor'],predecessor_checkpoint_sha256=before['checkpoint_sha256'])
    need(saved['repairs']==[*original['repairs'],descriptor],
         'PXD_ZERO_STARTUP_ALL_OLD_DESCRIPTORS_AND_ONE_EXACT_ADOPTION')
    need(after['input_sha256']==digest(dict(base=saved['base'],repairs=saved['repairs']))
         and after['checkpoint_sha256']==digest({k:v for k,v in after.items() if k!='checkpoint_sha256'})
         and saved['sha256']==digest({k:v for k,v in saved.items() if k!='sha256'}),
         'PXD_ZERO_STARTUP_CANONICAL_FULL_INPUT_INNER_AND_OUTER_HASHES')
    need(saved['journals'].keys()==original['journals'].keys()
         and all(saved['journals'][k]==original['journals'][k] for k in original['journals'] if k!='watch')
         and saved['journals']['watch']['bytes']>original['journals']['watch']['bytes'],
         'PXD_ZERO_STARTUP_ONLY_CANONICAL_INPUT_BOUNDARY_WATCH_APPENDED')
    event=dict(schema='research.pooled-action-successor/1',
        predecessor_checkpoint_sha256=before['checkpoint_sha256'],
        unchanged_through=original['source_cursor'],earliest_affected_session=earliest,
        state_sha256=before['state_sha256'],overlay=descriptor,
        predecessor_input_sha256=before['input_sha256'],successor_input_sha256=after['input_sha256'])
    need(saved['chain']==digest(dict(previous=original['chain'],event=event)),
         'PXD_ZERO_STARTUP_EXACT_CANONICAL_INPUT_SUCCESSOR_CHAIN')
    return event


class PauseAfterAdoption:
    def __init__(self,checkpoint,path,overlay_sha256,earliest):
        self.original=deepcopy(checkpoint);self.path=Path(path).resolve()
        self.overlay_sha256,self.earliest=overlay_sha256,earliest
        self.adoptions=0;self.adoption_writes=0;self.advance_attempts=0
        self.event=None;self.saved=None;self.handler=None

    def advance(self,*args,**kwargs):
        self.advance_attempts+=1
        raise ValueError('REFUSED_PXD_ZERO_SESSION_QUALIFICATION_CANNOT_ADVANCE')

    def write(self,path,saved):
        need(Path(path).resolve()==self.path,'PXD_ZERO_STARTUP_ONLY_DISPOSABLE_CURRENT_CHECKPOINT')
        if saved['repairs']==self.original['repairs']:
            need(self.adoptions==0 and saved==self.original,'PXD_ZERO_STARTUP_UNCHANGED_PRE_ADOPTION_CHECKPOINT')
            return self.original_write(path,saved)
        if self.adoptions:
            need(self.adoptions==1 and self.adoption_writes==1 and saved==self.saved,
                 'PXD_ZERO_STARTUP_ONLY_ONE_IDENTICAL_FINAL_PAUSE_FLUSH')
            self.original_write(path,saved);self.adoption_writes+=1
            return
        need(self.adoptions==0,'PXD_ZERO_STARTUP_EXACTLY_ONE_INPUT_ADOPTION')
        event=adoption(saved,self.original,self.overlay_sha256,self.earliest)
        handler=signal.getsignal(signal.SIGTERM)
        need(callable(handler) and getattr(handler,'__code__',None) is not None
             and handler.__code__.co_filename==self.backtest.run_backtest.__code__.co_filename
             and handler.__code__.co_freevars==('stop',),
             'PXD_ZERO_STARTUP_ONLY_ACTUAL_PRIVATE_CANONICAL_STOP_HANDLER')
        cells=dict(zip(handler.__code__.co_freevars,handler.__closure__))
        stop=cells['stop'].cell_contents
        need(type(stop) is list and stop==[], 'PXD_ZERO_STARTUP_PRIVATE_STOP_LIST_EMPTY')
        self.original_write(path,saved)
        handler(signal.SIGTERM,None)  # Deliberate function call; no OS signal is sent.
        need(stop==[signal.SIGTERM],'PXD_ZERO_STARTUP_ACTUAL_CANONICAL_PAUSE_REQUESTED')
        self.adoptions+=1;self.adoption_writes+=1
        self.event=event;self.saved=deepcopy(saved);self.handler=handler

    def __enter__(self):
        hosted()
        from research.pooled_vacancy_funding import backtest,runtime
        need(backtest.source_files()==self.original['base']['sources']
             and sha(Path(backtest.__file__).read_bytes())
                 ==self.original['base']['sources']['research/pooled_vacancy_funding/backtest.py'],
             'PXD_ZERO_STARTUP_EXACT_OWN_PINNED_FINANCIAL_SOURCE')
        self.backtest,self.runtime=backtest,runtime
        self.original_write,self.original_advance=backtest.write_checkpoint,runtime.advance
        self.original_handlers={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
        backtest.write_checkpoint=self.write;runtime.advance=self.advance
        return self

    def __exit__(self,*args):
        self.backtest.write_checkpoint=self.original_write;self.runtime.advance=self.original_advance
        for sig,handler in self.original_handlers.items():signal.signal(sig,handler)

    def proof(self):
        need(self.adoptions==1 and self.adoption_writes==2 and self.advance_attempts==0 and self.saved is not None,
             'PXD_ZERO_STARTUP_EXACT_ADOPTION_WITH_NO_ADVANCE')
        return dict(status='CANONICAL_INPUT_STARTUP_PAUSED_WITH_ZERO_FINANCIAL_SESSIONS',
            canonical_backtest_startup_invoked=True,financial_sessions_advanced=0,
            attempted_financial_transitions=0,input_adoptions=1,canonical_adoption_checkpoint_writes=2,
            original_checkpoint_sha256=self.original['sha256'],
            qualification_checkpoint_sha256=self.saved['sha256'],
            checkpoint_session=self.saved['source_cursor'],completed=self.saved['completed'],
            exact_canonical_boundary_event=self.event,all_financial_and_controller_state_unchanged=True,
            financial_resume_from_this_copy_authorized=False,production_contacted=False)
