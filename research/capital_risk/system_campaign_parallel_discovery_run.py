"""Hosted canonical discovery for an admitted own-parameter strict parent."""
import argparse
import ast
from contextlib import contextmanager,ExitStack
from copy import deepcopy
import json
from pathlib import Path
import shutil

from full_system_core import hosted
from full_system_benchmark import need,save
from system_campaign_facts import digest,FactualInputs
from system_campaign_distribution_facts import DistributionFacts
from system_campaign_discovery_inputs import preserve_input_documents
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_p01_discovery_replay import replay_tree
import system_campaign_discovery_replay as original
import system_campaign_discovery_gate as gate
import system_campaign_p01_discovery_anchors as anchor_source
from system_campaign_parallel_discovery import (specification,check_parent,reference,body,
    compile_body,exact_raw,REQUEST)


@contextmanager
def retained_inputs(root,parent,out):
    hosted();preserve_input_documents(root,parent,out)
    with ExitStack() as stack:
        for name,cls,catalog in (
            ('factual',FactualInputs,'system-campaign-factual-catalog.json'),
            ('distribution',DistributionFacts,'system-campaign-distribution-facts.json')):
            old=Path(root)/('hydrated-'+name+'-catalog.json')
            if not old.exists():continue
            codec=cls('/driver/'+catalog);new=Path(out)/('hydrated-'+name+'-catalog.json')
            codec.hydrate(new)
            need(new.read_bytes()==old.read_bytes(),'PARALLEL_ONLY_OWN_PRIOR_INPUT_HYDRATION_BYTES')
            stack.enter_context(codec)
        need(all(json.loads((Path(root)/'book/repairs'/d['filename']).read_bytes())['schema']=='terminal-repair/1'
                 for d in parent['repairs']),'PARALLEL_NO_UNSELECTED_CONDITIONAL_INPUT_MODELS')
        yield


def anchor_prepare_tree(raw,expected):
    fn=body('system_campaign_p01_discovery_anchors.py','prepare_tree')
    return compile_body(fn,dict(vars(anchor_source),ADAPTER_SHA=expected))(raw)


class Anchors(anchor_source.RetainedAnchors):
    def __init__(self,*args,expected_adapter_sha256,**kwargs):
        super().__init__(*args,**kwargs);self.expected_adapter_sha256=expected_adapter_sha256

    def __enter__(self):
        owner,=[n for n in ast.parse(exact_raw('system_campaign_p01_discovery_anchors.py')).body
                 if isinstance(n,ast.ClassDef) and n.name=='RetainedAnchors']
        fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='__enter__']
        return compile_body(fn,dict(vars(anchor_source),
            prepare_tree=lambda raw:anchor_prepare_tree(raw,self.expected_adapter_sha256)))(self)


def iterator(anchors):
    fn=body('system_campaign_discovery_replay.py','source_iterator')
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=='prefix']
    index,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Expr)
              and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='buffer.append']
    loop.body[index:index]=ast.parse('anchors.observe(packet)').body
    return compile_body(fn,dict(vars(original),anchors=anchors))


class AnchorQualification:
    """Qualify actual auxiliary-anchor uses without altering Core transitions."""
    def __init__(self,out,anchors):
        self.out=Path(out);self.anchors=anchors;self.seen=set();self.pending=None;self.proofs=[]

    def prepare(self,buffer,run):
        prior=digest(run.state.to_dict());initial=self.anchors.commitment()['rows']
        published=buffer.prepare(run.state,run.state.data_version+1,formation=False)
        self.pending=None
        if self.anchors.commitment()['rows']==initial:return published
        affected=[sid for sid in sorted(self.anchors.m.adapter.protected(run.state))
            if buffer.rings.get(sid) is None or run.state.feed['series'][sid]['signal_basis_anchor'][0] not in buffer.axis]
        need(affected and published.bars==buffer.current.bars and len(buffer.axis)==300
             and list(published.window_features['sessions'])==list(buffer.axis)
             and digest(run.state.to_dict())==prior,'PARALLEL_ANCHOR_ONLY_AUXILIARY_NO_PRIOR_BAR_OR_WINDOW_CHANGE')
        novel=[]
        for sid in affected:
            bar=published.signal_basis_anchors[sid];record=self.anchors.records[sid]
            need(bar.session==record.session<=run.state.last_processed_session<buffer.current.day
                 and bar.raw_close==record.raw_close and bar.signal_close==record.signal_close,
                 'PARALLEL_ACTUAL_HISTORICAL_SOURCE_ANCHOR_MATCH')
            if (sid,record.session) not in self.seen:novel.append(sid)
        if not novel:return published
        try:self.anchors.original(buffer,run.state,run.state.data_version+1,formation=False)
        except self.anchors.m.adapter.TemporalViolation as error:
            need(str(error).startswith('LIVE_ANCHOR_OUTSIDE_WINDOW: '),'PARALLEL_EXACT_ORIGINAL_EXPIRED_ANCHOR_REFUSAL')
            original_error=str(error)
        else:raise ValueError('PARALLEL_ORIGINAL_ANCHOR_GUARD_DID_NOT_REFUSE')
        falsifiers=[];before=self.anchors.commitment()
        for sid in novel:
            record=self.anchors.records[sid];anchor=run.state.feed['series'][sid]['signal_basis_anchor']
            for label,bad in (('MISSING_SOURCE',None),('WRONG_RAW_BASIS',record.model_copy(update={'raw_close':record.raw_close+1.0}))):
                if bad is None:self.anchors.records.pop(sid)
                else:self.anchors.records[sid]=bad
                try:
                    try:self.anchors.retained(buffer,run.state,sid,anchor)
                    except ValueError:pass
                    else:raise AssertionError('PARALLEL_ANCHOR_FALSIFIER_WAS_ACCEPTED:'+label)
                finally:self.anchors.records[sid]=record
                falsifiers.append(dict(security_id=sid,case=label,refused=True))
        need(self.anchors.commitment()==before and digest(run.state.to_dict())==prior,
             'PARALLEL_ACTUAL_ANCHOR_FALSIFIERS_NO_STATE_OR_EVENT_WRITES')
        self.pending=dict(session=buffer.current.day,prior_state_sha256=run.state.state_hash,
            original_refusal=original_error,security_ids=novel,source_falsifiers=falsifiers,
            historical_auxiliary_only=True,current_bars_unchanged=True,window_dates=300)
        return published

    def after(self,prior,next_run):
        if self.pending is None:return
        need(prior.state.state_hash==self.pending['prior_state_sha256']
             and next_run.state.last_processed_session==self.pending['session'],
             'PARALLEL_ACTUAL_ANCHOR_CANONICAL_TRANSITION_ADJACENCY')
        self.pending.update(status='ACTUAL_CANONICAL_DIAGNOSTIC_ANCHOR_USE_QUALIFIED',
            next_state_sha256=next_run.state.state_hash,financial_authority=False)
        self.proofs.append(self.pending)
        self.seen.update((sid,self.anchors.records[sid].session) for sid in self.pending['security_ids'])
        save(self.out/'actual-anchor-qualification.json',dict(financial_authority=False,
            production_contacted=False,actual_uses=self.proofs))
        self.pending=None


def diagnostic_tree():
    tree=replay_tree(exact_raw('system_campaign_discovery_replay.py'));fn=tree.body[0]
    cp,=[n for n in ast.walk(fn) if isinstance(n,ast.FunctionDef) and n.name=='checkpoint']
    index,=[i for i,n in enumerate(cp.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
              and ast.unparse(n.value.func)=='journal.write_checkpoint']
    cp.body[index:index]=ast.parse('value.update(retained_source_anchors=anchors.commitment())').body
    cp.body[index+2:index+2]=ast.parse("shutil.copyfile(book/'discovery-checkpoint.json.gz',book/(value['source_cursor']+'.json.gz'))").body
    # The first real transition is also durable, before a later unsupported event.
    loop,=[n for n in ast.walk(fn) if isinstance(n,ast.For) and ast.unparse(n.iter)=='wanted']
    prepare,=[n for n in ast.walk(loop) if isinstance(n,ast.Call) and ast.unparse(n.func)=='buffer.prepare']
    prepare.func=ast.parse('anchor_gate.prepare',mode='eval').body
    prepare.args=[ast.Name(id='buffer',ctx=ast.Load()),ast.Name(id='run',ctx=ast.Load())];prepare.keywords=[]
    index,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='next_run']
    loop.body[index+1:index+1]=ast.parse('anchor_gate.after(run,next_run)').body
    loop.body.extend(ast.parse('if len(observed)==1: checkpoint()').body)
    return fn


def main(args):
    hosted()
    from research.pooled_vacancy_funding import journal,runtime
    spec=specification(args.arm)
    need(json.loads(args.spec.read_bytes())==spec,'PARALLEL_EXACT_WORKER_SPEC')
    root,out=Path('/old'),Path('/out')
    parent=require_strict_checkpoint(journal.read_checkpoint(root/spec['selected_checkpoint']))
    check_parent(parent,spec)
    with retained_inputs(root,parent,out):
        # Canonical restore is performed by the unchanged source iterator again
        # after input contexts enter; this pre-restore only seeds anchor targets.
        initial=runtime.restore(parent['run'],policy=parent['base']['policy'],
                                input_sha256=parent['run']['input_sha256'])
        need(runtime.checkpoint(initial)==parent['run'],'PARALLEL_ACTUAL_CANONICAL_PARENT_ROUNDTRIP')
        with Anchors(out,initial.state,source_sha256=digest(parent['base']['sources']),
                input_sha256=parent['run']['input_sha256'],expected_adapter_sha256=
                parent['base']['sources']['research/pooled_input_support/adapter.py']) as anchors:
            source_iterator=iterator(anchors)
            if args.mode=='qualify':
                function=compile_body(body('system_campaign_discovery_gate.py','qualify'),
                    dict(vars(gate),source_iterator=source_iterator))
                function(root,parent,out,selected_file=spec['selected_checkpoint'])
            else:
                save(out/'strict-parent-reference.json',reference(spec))
                shutil.copyfile(root/spec['selected_checkpoint'],out/'strict-parent.json.gz')
                function=compile_body(diagnostic_tree(),dict(vars(original),
                    source_iterator=source_iterator,anchors=anchors,shutil=shutil,
                    anchor_gate=AnchorQualification(out,anchors)))
                function(root,parent,out,selected_file=spec['selected_checkpoint'],
                    strict_admission_sha256=digest(reference(spec)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--arm',required=True)
    parser.add_argument('--mode',choices=('qualify','discovery'),required=True)
    parser.add_argument('--spec',type=Path,required=True)
    main(parser.parse_args())
