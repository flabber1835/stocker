"""Source-bound exact continuation of a tainted diagnostic stream only."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

from full_system_core import hosted
from full_system_benchmark import need,save
from seal import sha256_file
from system_campaign_discovery_context import TAINT,digest,encoded,DiscoveryContext
import system_campaign_discovery_context as context_source
import system_campaign_discovery_replay as original
from system_campaign_p01_discovery_replay import replay_tree as monthly_tree
from system_campaign_p01_discovery_suffix_parent import validate_contents,verify_stream

HERE=Path(__file__).resolve().parent
REQUEST003='system-campaign-p01-discovery-request-003.json'


def exact_raw(module):
    raw=Path(module.__file__).read_bytes()
    old=json.loads((HERE/REQUEST003).read_bytes())
    need(hashlib.sha256(raw).hexdigest()==old['sources'][Path(module.__file__).name],
         'P01_SUFFIX_ORIGINAL_REPLAY_CONTEXT_BYTES_UNCHANGED')
    return raw


def iterator_tree(raw):
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='source_iterator']
    fn=deepcopy(fn)
    class Sites(ast.NodeTransformer):
        run_sites=0;cursor_sites=0
        def visit_Subscript(self,node):
            if ast.unparse(node)=="parent['run']":
                self.run_sites+=1;return ast.copy_location(ast.parse("saved['runtime_checkpoint']",mode='eval').body,node)
            if ast.unparse(node)=="parent['source_cursor']":
                self.cursor_sites+=1;return ast.copy_location(ast.parse("saved['source_cursor']",mode='eval').body,node)
            return self.generic_visit(node)
    sites=Sites();fn=sites.visit(fn)
    need(sites.run_sites==2 and sites.cursor_sites==2,'P01_SUFFIX_EXACT_RESTORE_AND_CURSOR_SITES')
    loop,=[n for n in fn.body if isinstance(n,ast.For) and ast.unparse(n.iter)=='prefix']
    append,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
              and ast.unparse(n.value.func)=='buffer.append']
    loop.body[append:append]=ast.parse('anchors.observe(packet)').body
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))


class ContinuedContext(DiscoveryContext):
    def __init__(self,output,*,source_sha256,previous,saved):
        super().__init__(output,source_sha256=source_sha256)
        raw=(Path(previous)/'discovery-events.jsonl').read_bytes();verify_stream(raw,saved['events'])
        need(not (self.output/'discovery-events.jsonl').exists(),'P01_SUFFIX_EVENTS_NEW_DISJOINT_COPY')
        with (self.output/'discovery-events.jsonl').open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        self.event_hash.update(raw);self.sequence=saved['events']['rows']
        self.chain=saved['events']['chain_sha256'];self.transitions=saved['discovery_transitions']
        events=[json.loads(line)['event'] for line in raw.splitlines()]
        self.tainted=any(event['context'].get('bypass') is True for event in events)

    def __enter__(self):
        raw=exact_raw(context_source)
        owner,=[n for n in ast.parse(raw).body if isinstance(n,ast.ClassDef) and n.name=='DiscoveryContext']
        fn,=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name=='__enter__']
        fn=deepcopy(fn)
        calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call)
               and ast.unparse(n.func)=="(self.output / 'discovery-events.jsonl').open"]
        need(len(calls)==1 and ast.literal_eval(calls[0].args[0])=='xb','P01_SUFFIX_ONE_EVENT_APPEND_MODE_SITE')
        calls[0].args=[ast.Constant('ab')]
        scope=dict(vars(context_source));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
            '<same-diagnostic-hooks-seeded-append-stream>','exec'),scope)
        return scope['__enter__'](self)


def seed_book(book,previous,saved):
    from research.pooled_vacancy_funding import journal
    book=Path(book);book.mkdir()
    lineage=book/'predecessor-checkpoints';lineage.mkdir()
    shutil.copyfile(Path(previous)/'diagnostic-book/discovery-checkpoint.json.gz',lineage/'diagnostic-prefix356.json.gz')
    for name,entry in saved['journals'].items():
        raw=(Path(previous)/'diagnostic-book'/(name+'.jsonl')).read_bytes();verify_stream(raw,entry,last=True)
        with (book/(name+'.jsonl')).open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
    (book/'retained-checkpoints').mkdir()


@contextmanager
def recovered_stream(book,saved):
    from research.pooled_vacancy_funding import journal
    with journal.Journal(book,resume=True) as stream:
        stream.verify(saved['journals'])
        tails=stream.recover(saved['journals'])
        need(not tails and stream.commitment()==saved['journals'],'P01_SUFFIX_ALL_OLD_PREFIXES_RECOVERED_ZERO_TAILS')
        yield stream


class FirstTransition:
    """Actual canonical integration, before any later diagnostic transition."""
    def __init__(self,out,anchors,saved,spec):
        self.out,self.anchors,self.saved,self.spec=Path(out),anchors,saved,spec
        self.prepared=False;self.passed=False

    def prepare(self,buffer,run):
        if self.prepared:return buffer.prepare(run.state,run.state.data_version+1,formation=False)
        need(buffer.current.day==self.spec['next_session'],'P01_SUFFIX_EXACT_FIRST_NEXT_SESSION_ADJACENCY')
        before=digest(run.state.to_dict())
        affected=[]
        for sid in sorted(self.anchors.m.adapter.protected(run.state)):
            anchor=run.state.feed['series'][sid]['signal_basis_anchor']
            if buffer.rings.get(sid) is None or anchor[0] not in buffer.axis:
                affected.append(sid)
        need(affected,'P01_SUFFIX_REPRODUCE_ACTUAL_EXPIRED_ANCHOR_NOT_SYNTHETIC_CASE')
        try:self.anchors.original(buffer,run.state,run.state.data_version+1,formation=False)
        except self.anchors.m.adapter.TemporalViolation as error:
            need(str(error).startswith('LIVE_ANCHOR_OUTSIDE_WINDOW: '),'P01_SUFFIX_EXACT_ORIGINAL_INPUT_REFUSAL')
            original_error=str(error)
        else:raise ValueError('P01_SUFFIX_ORIGINAL_GUARD_DID_NOT_REFUSE')
        falsifiers=[]
        for sid in affected:
            anchor=run.state.feed['series'][sid]['signal_basis_anchor'];record=self.anchors.records.get(sid)
            need(record is not None,'P01_SUFFIX_ANCHOR_MUST_COME_FROM_ACTUAL_FROZEN_SOURCE_PACKET')
            for name,bad in (('MISSING_SOURCE',None),('WRONG_RAW_BASIS',record.model_copy(update={'raw_close':record.raw_close+1.0})),
                             ('WRONG_SOURCE_DATE',record.model_copy(update={'session':buffer.current.day}))):
                if bad is None:self.anchors.records.pop(sid)
                else:self.anchors.records[sid]=bad
                try:
                    try:self.anchors.retained(buffer,run.state,sid,anchor)
                    except ValueError:pass
                    else:raise AssertionError('P01_SUFFIX_SOURCE_ANCHOR_FALSIFIER_NOT_REFUSED:'+name)
                finally:self.anchors.records[sid]=record
                falsifiers.append(dict(security_id=sid,case=name,refused=True))
        need(self.anchors.commitment()['rows']==0 and digest(run.state.to_dict())==before,
             'P01_SUFFIX_FALSIFIERS_NEVER_ADVANCE_STATE_OR_WRITE_ANCHOR_EVENTS')
        published=buffer.prepare(run.state,run.state.data_version+1,formation=False)
        need(published.bars==buffer.current.bars
             and not {bar.security_id for bar in published.bars}.intersection(affected),
             'P01_SUFFIX_RETAINED_ANCHOR_NEVER_APPEARS_AS_CURRENT_BAR')
        need(len(buffer.axis)==300 and published.session==buffer.current.day
             and list(published.window_features['sessions'])==list(buffer.axis),
             'P01_SUFFIX_EXACT_CURRENT_SESSION_AND_300_DATE_AXIS')
        for sid in affected:
            bar=published.signal_basis_anchors[sid];actual=self.anchors.records[sid]
            need(bar.session==actual.session<run.state.last_processed_session
                 and bar.raw_close==actual.raw_close and bar.signal_close==actual.signal_close,
                 'P01_SUFFIX_ONLY_EXACT_HISTORICAL_AUXILIARY_SOURCE_ANCHOR')
        self.affected=affected;self.prior=deepcopy(run.state.to_dict());self.prepared=True
        self.proof=dict(original_input_refusal=original_error,source_anchor_falsifiers=falsifiers,
            affected_security_ids=affected,actual_source_records={sid:self.anchors.records[sid].model_dump() for sid in affected},
            old_runtime_checkpoint_sha256=self.saved['runtime_checkpoint']['checkpoint_sha256'],
            next_session=published.session,current_bars_unchanged=True,window_dates=300)
        return published

    def after(self,prior,next_run):
        if self.passed:return
        need(self.prepared and prior.state.to_dict()==self.prior,'P01_SUFFIX_FIRST_PRIOR_STATE_UNCHANGED')
        after=next_run.state.to_dict();before=self.prior
        for sid in self.affected:
            old=[v for v in before['wealth_core']['episodes'].values() if v['security_id']==sid]
            new=[v for v in after['wealth_core']['episodes'].values() if v['security_id']==sid]
            keep=lambda rows:[{k:v[k] for k in ('security_id','slot_id','current_shares','entry_date','entry_raw_open')} for v in rows]
            need(keep(old)==keep(new),'P01_SUFFIX_NO_ANCHOR_BASED_POSITION_REMOVAL_OR_SHARE_CHANGE')
            for ep in old:
                slot=str(ep['slot_id'])
                need(before['wealth_core']['slots'][slot]==after['wealth_core']['slots'][slot],
                     'P01_SUFFIX_KEEPS_EXISTING_OCCUPIED_SLOT')
            need(before['wealth_core']['last_valid_mark_session'].get(sid)==after['wealth_core']['last_valid_mark_session'].get(sid)
                 and before['feed']['series'][sid]['signal_basis_anchor']==after['feed']['series'][sid]['signal_basis_anchor'],
                 'P01_SUFFIX_DOES_NOT_REDATE_LAST_VALID_MARK_OR_REBASE_RETAINED_ANCHOR')
            new_events=after['ledger']['events'][len(before['ledger']['events']):]
            need(all(sid not in encoded(event).decode() for event in new_events),
                 'P01_SUFFIX_NO_NEW_AFFECTED_SECURITY_FILL_OR_SETTLEMENT')
        self.proof.update(status='ACTUAL_FIRST_CANONICAL_SUFFIX_TRANSITION_QUALIFIED',financial_authority=False,
            authority=TAINT,actual_canonical_transition=True,prior_unchanged=True,
            affected_shares_slots_last_valid_marks_and_basis_preserved=True,
            no_current_quote_fill_or_settlement=True,next_state_sha256=next_run.state.state_hash,
            retained_source_anchors=self.anchors.commitment(),production_contacted=False)
        save(self.out/'retained-anchor-canonical-qualification.json',self.proof);self.passed=True


def suffix_tree(raw):
    tree=monthly_tree(raw);fn=tree.body[0]
    assignments={ast.unparse(n.targets[0]):n for n in fn.body if isinstance(n,ast.Assign) and len(n.targets)==1}
    need(ast.unparse(assignments['observed'].value)=='[]','P01_SUFFIX_ONE_EMPTY_OBSERVATION_SEED')
    assignments['observed'].value=ast.parse('list(old_days)',mode='eval').body
    assignments['chain'].value=ast.parse("saved['transition_chain_sha256']",mode='eval').body
    count=dict(mkdir=0,journal=0,context=0,prepare=0,after=0,complete=0,axis=0,remaining=0,cp=0)
    class Sites(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node.func)=='book.mkdir':
                count['mkdir']+=1;return ast.copy_location(ast.parse('seed_book(book,previous,saved)',mode='eval').body,node)
            if ast.unparse(node.func)=='journal.Journal':
                count['journal']+=1;return ast.copy_location(ast.parse('recovered_stream(book,saved)',mode='eval').body,node)
            if ast.unparse(node.func)=='DiscoveryContext':
                count['context']+=1;node.keywords.extend(ast.parse('f(previous=previous,saved=saved)',mode='eval').body.keywords)
                node.func=ast.Name(id='ContinuedContext',ctx=ast.Load())
            if ast.unparse(node.func)=='buffer.prepare':
                count['prepare']+=1;return ast.copy_location(ast.parse('first.prepare(buffer,run)',mode='eval').body,node)
            if ast.unparse(node.func)=='require_axis':
                count['axis']+=1;node.args[1]=ast.Name(id='full_wanted',ctx=ast.Load())
            if ast.unparse(node.func)=='len' and len(node.args)==1 and ast.unparse(node.args[0])=='wanted':
                count['remaining']+=1;node.args[0]=ast.Name(id='full_wanted',ctx=ast.Load())
            return self.generic_visit(node)
        def visit_Compare(self,node):
            if ast.unparse(node)=='observed == wanted':
                count['complete']+=1;node.comparators=[ast.Name(id='full_wanted',ctx=ast.Load())]
            return self.generic_visit(node)
    fn=Sites().visit(fn)
    loop,=[n for n in ast.walk(fn) if isinstance(n,ast.For) and ast.unparse(n.iter)=='wanted']
    idx,=[i for i,n in enumerate(loop.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='next_run']
    loop.body[idx+1:idx+1]=ast.parse('first.after(run,next_run)').body;count['after']=1
    # Append daily and update run/observed first; the first new transition is durably checkpointed immediately.
    loop.body.append(ast.parse("if len(observed)==len(old_days)+1: checkpoint()").body[0])
    cp,=[n for n in ast.walk(fn) if isinstance(n,ast.FunctionDef) and n.name=='checkpoint']
    site,=[i for i,n in enumerate(cp.body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and ast.unparse(n.value.func)=='journal.write_checkpoint']
    cp.body[site:site]=ast.parse('value.update(diagnostic_predecessor=diagnostic_reference,retained_source_anchors=anchors.commitment())').body
    cp.body[site+2:site+2]=ast.parse("shutil.copyfile(book/'discovery-checkpoint.json.gz',book/'retained-checkpoints'/(value['source_cursor']+'.json.gz'))").body
    count['cp']=1
    need(count==dict(mkdir=1,journal=1,context=1,prepare=1,after=1,complete=1,axis=1,remaining=1,cp=1),
         'P01_SUFFIX_EVERY_DECLARED_CONTINUATION_SITE_EXACTLY_ONCE')
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))


def replay(root,parent,output,*,selected_file,strict_admission_sha256,previous,spec,anchors):
    hosted()
    saved=validate_contents(previous,spec)
    old_days=[json.loads(line)['session'] for line in (Path(previous)/'diagnostic-book/daily.jsonl').read_bytes().splitlines()]
    need(len(old_days)==spec['transitions'] and old_days[-1]==spec['selected_session'],
         'P01_SUFFIX_EXACT_OLD_DAILY_AXIS_SEED')
    from research.pooled_input_support import bundle
    axis=bundle.axis();full_wanted=axis[axis.index(parent['source_cursor'])+1:axis.index(spec['target_end'])+1]
    need(full_wanted[:len(old_days)]==old_days and len(full_wanted)==spec['cumulative_expected_sessions']
         and full_wanted[len(old_days)]==spec['next_session'],'P01_SUFFIX_FULL_FROZEN_ORDERED_DATE_AXIS')
    diagnostic_reference=dict(schema='research.p01-diagnostic-suffix-reference/1',financial_authority=False,
        run_id=spec['run_id'],head=spec['head'],artifact_id=spec['artifact_id'],
        checkpoint_sha256=spec['diagnostic_checkpoint_sha256'],runtime_checkpoint_sha256=spec['runtime_checkpoint_sha256'],
        transitions=spec['transitions'],source_cursor=spec['selected_session'],spec_sha256=sha256_file(HERE/'system-campaign-p01-discovery-suffix-predecessor.json'))
    first=FirstTransition(output,anchors,saved,spec)
    scope=dict(vars(original),saved=saved,anchors=anchors)
    exec(compile(iterator_tree(exact_raw(original)),'<same-inputs-exact-diagnostic-runtime-and-cursor>','exec'),scope)
    scope.update(previous=Path(previous),old_days=old_days,full_wanted=full_wanted,seed_book=seed_book,
        recovered_stream=recovered_stream,ContinuedContext=ContinuedContext,first=first,
        diagnostic_reference=diagnostic_reference,shutil=shutil)
    save(Path(output)/'diagnostic-predecessor-admission.json',dict(reference=diagnostic_reference,
        exact_runtime_restore_required=True,all_old_prefixes_and_zero_tails_verified=True,
        unchanged_original_three_case_gate_reused=True,no_financial_state_adoption=True,production_contacted=False))
    exec(compile(suffix_tree(exact_raw(original)),'<exact-diagnostic-suffix-no-financial-schema-adoption>','exec'),scope)
    return scope['replay'](root,parent,output,selected_file=selected_file,strict_admission_sha256=strict_admission_sha256)
