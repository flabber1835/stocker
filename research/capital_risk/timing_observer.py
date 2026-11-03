"""Clock-only observation of selected Python calls; no portfolio values are read."""
import json
import time

PREFIX='/variant/research/'
TARGETS={
    (PREFIX+'pooled_input_support/bundle.py','verify_bundle'):'input_verification',
    (PREFIX+'pooled_input_support/adapter.py','prepare'):'input_preparation',
    (PREFIX+'pooled_vacancy_funding/backtest.py','comparisons'):'reference_inputs',
    (PREFIX+'pooled_vacancy_funding/runtime.py','restore'):'canonical_restore',
    (PREFIX+'pooled_vacancy_funding/runtime.py','advance'):'canonical_transition',
    (PREFIX+'pooled_vacancy_funding/backtest.py','advance_account'):'funded_account',
    (PREFIX+'pooled_vacancy_funding/retries.py','advance'):'retry_diagnostics',
    (PREFIX+'pooled_vacancy_funding/backtest.py','save'):'checkpoint_save',
}


class TimingObserver:
    def __init__(self,stream,targets=TARGETS):
        self.stream=stream;self.targets=targets;self.active={};self.counts={}

    def __call__(self,frame,event,arg):
        if event=='call':
            label=self.targets.get((frame.f_code.co_filename,frame.f_code.co_name))
            if label is not None:self.active[id(frame)]=(label,time.perf_counter(),time.process_time())
        elif event=='return':
            saved=self.active.pop(id(frame),None)
            if saved is None:return
            label,wall,cpu=saved;ordinal=self.counts.get(label,0);self.counts[label]=ordinal+1
            record=dict(label=label,ordinal=ordinal,wall_seconds=time.perf_counter()-wall,
                cpu_seconds=time.process_time()-cpu,returned_value=arg is not None)
            self.stream.write(json.dumps(record,sort_keys=True)+'\n');self.stream.flush()
