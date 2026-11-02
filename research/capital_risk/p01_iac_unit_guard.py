"""Dated old-unit scope, pre-prepare durability, and full unit-window evidence."""
import ast
from copy import deepcopy
import math
from pathlib import Path

from p01_factual_batch_guard import ActionGuard,roles
from p01_iac_unit_contract import SOURCE,CHILD,OLD_MATCH,EVENT,FIRST,END,need,sha,digest
from p01_iac_unit_codec import number
from system_campaign_discovery_context import material

MODULES=('shared/stock_strategy_shared/wealth_core/feed.py',
    'research/pooled_input_support/adapter.py','sentinel/core/window_material.py',
    'shared/stock_strategy_shared/wealth_core/window_signals.py','sentinel/core/kernel.py',
    'shared/stock_strategy_shared/wealth_core/adapter.py','sentinel/core/spinoffs.py',
    'sentinel/core/session.py','shared/stock_strategy_shared/wealth_core/live.py',
    'shared/stock_strategy_shared/wealth_core/state.py')


def source_shape(files,expected):
    need(set(files)==set(MODULES) and all(sha(v)==expected[n] for n,v in files.items()),
         'EXACT_ACTUAL516_UNIT_NORMALIZER_AND_ACTION_SOURCE')
    trees={n:ast.parse(v) for n,v in files.items()}
    def find(path,name):
        nodes=trees[path].body
        for part in name.split('.'):
            node,=[n for n in nodes if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name==part]
            nodes=node.body
        return node
    feature=find('shared/stock_strategy_shared/wealth_core/window_signals.py','feature')
    windows=[n for n in ast.walk(feature) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
        and n.func.attr=='signal_window']
    need(len(windows)==1 and len(windows[0].args)==1 and isinstance(windows[0].args[0],ast.Constant),
         'EXACT_SOURCE_FEATURE_WINDOW_LENGTH')
    series=find(MODULES[0],'SecuritySeries')
    defaults={n.target.id:ast.literal_eval(n.value) for n in series.body if isinstance(n,ast.AnnAssign)
        and isinstance(n.target,ast.Name) and n.target.id in ('vendor_basis_multiplier','signal_basis_multiplier')}
    need(defaults==dict(vendor_basis_multiplier=1.0,signal_basis_multiplier=1.0),'EXACT_PINNED_RESTORE_DEFAULTS')
    canonical=find(MODULES[0],'build_signal_series')
    loop,=[n for n in canonical.body if isinstance(n,ast.For)]
    need(isinstance(loop.body[0],ast.AugAssign) and isinstance(loop.body[0].op,ast.Mult)
         and ast.unparse(loop.body[0].target)=='factor'
         and ast.unparse(loop.body[0].value)=='float(b.split_ratio)',
         'CANONICAL_FORWARD_FACTOR_OPERATION_ORDER')
    need('float(b.raw_close) * factor' in ast.unparse(loop.body[1]),'CANONICAL_RAW_TIMES_FACTOR_OPERATION')
    append=find(MODULES[0],'SecuritySeries.append')
    assignments=[n for n in ast.walk(append) if isinstance(n,ast.Assign)
        and any(ast.unparse(t)=='self.split_factor' for t in n.targets)]
    need(len(assignments)==1 and ast.unparse(assignments[0].value)
         =='float(bar.signal_close) * self.signal_basis_multiplier / float(bar.raw_close)',
         'PUBLISHED_SIGNAL_OVERRIDES_SPLIT_ONLY_FACTOR')
    kernel=find('sentinel/core/kernel.py','advance_session');calls=[n for n in ast.walk(kernel) if isinstance(n,ast.Call)]
    def lines(name):return [n.lineno for n in calls if ast.unparse(n.func)==name]
    spin,=lines('apply_supported_entitlements');plan,=lines('plan_session');witness,=lines('terminal_returns.values')
    need(spin<plan<witness,'EXACT_SPIN_PREFLIGHT_PLAN_AND_CLOSING_ORDER')
    selected=((MODULES[0],'build_signal_series'),(MODULES[0],'SecuritySeries.append'),
        ('sentinel/core/session.py','_feed_from_dict'),('sentinel/core/window_material.py','Signal.bar'),
        ('research/pooled_input_support/adapter.py','Buffer.prepare'),
        ('shared/stock_strategy_shared/wealth_core/window_signals.py','feature'))
    return dict(source_files={n:sha(v) for n,v in files.items()},window_length=windows[0].args[0].value,
        defaults=defaults,source_map_files_exact=True,spin_before_plan_before_witness=True,
        function_preimages={n+':'+name:sha(ast.get_source_segment(files[n].decode(),find(n,name)).encode())
            for n,name in selected},canonical_factor_then_raw=True,published_split_only_insufficient=True)


def source_contract(binding):
    from full_system_core import hosted
    hosted()
    files={n:(Path('/variant')/n).read_bytes() for n in MODULES}
    return source_shape(files,binding.source_map['successor_all_sources'])


def unit_scope(state,session):
    if session!=EVENT:return []
    value=state if isinstance(state,dict) else state.to_dict()
    wealth,pending,ledger=value['wealth_core'],value['pending'],value['ledger']
    need(type(wealth['episodes']) is dict and type(wealth['slots']) is dict and type(pending) is list
         and all(type(p) is dict and type(p.get('security_id')) is str for p in pending),
         'FULL_SOURCE_EPISODES_SLOTS_AND_ALL_PENDING_SCHEMA')
    held=[e for e in wealth['episodes'].values() if e['security_id']==SOURCE]
    need(not held,'OLD_UNIT_SOURCE_HOLDING_UNSUPPORTED')
    need(not any(p['security_id']==SOURCE for p in pending),'OLD_UNIT_SOURCE_ANY_PENDING_UNSUPPORTED')
    need(not any(e.get('exit_pending',False) for e in held),'OLD_UNIT_SOURCE_EXIT_FLAG_UNSUPPORTED')
    ticker=value['feed']['series'].get(SOURCE,{}).get('ticker')
    reservations=[s for s in wealth['slots'].values() if s.get('reserved_for')==SOURCE
        or s.get('reserved_for') is None and ticker and s.get('reserved_ticker')==ticker]
    need(not reservations,'OLD_UNIT_SOURCE_RESERVATION_OR_ORPHAN_RESERVATION_UNSUPPORTED')
    need(set(ledger)=={'events','receivables'} and type(ledger['receivables']) is list
         and all(type(r) is dict and type(r.get('security_id')) is str for r in ledger['receivables']),
         'EXACT_SOURCE_LEDGER_CLAIM_SCHEMA')
    need(not any(r['security_id']==SOURCE for r in ledger['receivables']),'OLD_UNIT_SOURCE_RECEIVABLE_UNSUPPORTED')
    for key in ('unresolved_terminals','terminal_pending_terms','terminal_pending_sessions','terminal_carry_audit'):
        need(type(wealth.get(key,{})) is dict and SOURCE not in wealth.get(key,{}),'OLD_UNIT_SOURCE_UNRESOLVED_OR_CARRY_CLAIM')
    targets={sid:dict(episodes={k:deepcopy(e) for k,e in wealth['episodes'].items() if e['security_id']==sid},
        pending=[deepcopy(p) for p in pending if p['security_id']==sid],
        reservations=[deepcopy(s) for s in wealth['slots'].values() if s.get('reserved_for')==sid],
        receivables=[deepcopy(r) for r in ledger['receivables'] if r['security_id']==sid]) for sid in (CHILD,OLD_MATCH)}
    return [dict(session=session,source_security_id=SOURCE,source_unheld=True,source_any_pending_absent=True,
        source_exit_flags_absent=True,source_reservations_absent=True,source_claims_absent=True,
        source_selected=SOURCE in value['median5']['selected'],independent_target_roles=targets)]


def role_record(previous,following,session):
    return dict(session=session,prior_state_sha256=previous['state_sha256'],state_sha256=following['state_sha256'],
        before=roles_from_dict(previous['state']),after=roles_from_dict(following['state']))


def roles_from_dict(state):
    return dict(episodes=deepcopy(state['wealth_core']['episodes']),pending=deepcopy(state['pending']),
        selected=deepcopy(state['median5']['selected']))


def window_record(buffer,published,codec,window_length):
    day=published.session;ring=buffer.rings.get(SOURCE)
    signal=[s for s in published.window_features['signals'] if s['security_id']==SOURCE]
    if not signal:return dict(session=day,source_present=False,unit_factor_not_applied_to_other_ids=True)
    need(len(signal)==1 and ring is not None,'EXACT_CURRENT_SOURCE_RING_AND_SIGNAL')
    axis=list(buffer.axis);origin=buffer.index-len(axis)+1
    indices=ring.indices[-window_length:];sessions=[axis[i-origin] for i in indices]
    value=lambda x:None if math.isnan(x) else x
    closes=[value(x) for x in ring.values['signal_close'][-window_length:]]
    raws=[value(x) for x in ring.values['raw_close'][-window_length:]]
    volumes=[value(x) for x in ring.values['volume'][-window_length:]];hashes=[]
    need(len(indices)==len(closes)==len(raws)==len(volumes)==window_length,'EXACT_FULL_SOURCE_UNIT_FEATURE_WINDOW')
    for date,close,raw,volume in zip(sessions,closes,raws,volumes):
        row=codec.domain.rows[date];expected=number(row['signal_close']) if date<EVENT else codec.domain.days[date]['logical_signal_close']
        need(close==expected and raw==number(row['raw_close']) and volume==number(row['raw_compatible_volume']),
             'ENTIRE_RING_LOGICAL_SIGNAL_RAW_VOLUME_AND_UNIT_DATE_DOMAINS')
        hashes.append(digest(row))
    need(signal[0]['closes'][-1]==closes[-1] and signal[0]['raw_close']==raws[-1],
         'CURRENT_PUBLICATION_FEATURE_SIGNAL_AND_RAW_DOMAINS')
    return dict(session=day,source_present=True,window_length=window_length,indices=list(indices),sessions=sessions,
        logical_signal_closes=closes,raw_closes=raws,raw_compatible_volumes=volumes,native_row_sha256=hashes,
        actual_publication_signal=deepcopy(signal[0]),full_window_before_feature_bound=True,
        raw_liquidity_domain_unchanged=True)


def anchor_record(state,prepared):
    result=deepcopy(prepared);series=state.feed['series'].get(SOURCE)
    result['source_series_retained']=series is not None
    if series is not None and prepared['source_present']:
        logical=prepared['logical_signal_closes'][-1];raw=prepared['raw_closes'][-1]
        need(series.get('signal_basis_multiplier',1.0)==series.get('vendor_basis_multiplier',1.0)==1.0,
             'EXACT_QUALIFIED_RETAINED_SOURCE_MULTIPLIERS')
        need(series['signal_closes'][-1]==logical and series['signal_basis_anchor']==[prepared['session'],raw,logical],
             'ACTUAL_OWNED_LOGICAL_SIGNAL_AND_ANCHOR')
        if raw is not None and raw>0:need(series['split_factor']==logical/raw,'EXACT_CANONICAL_PUBLISHED_SIGNAL_FACTOR_QUOTIENT')
        result['actual_retained_basis']=dict(split_factor=series['split_factor'],
            signal_basis_multiplier=series.get('signal_basis_multiplier',1.0),vendor_basis_multiplier=series.get('vendor_basis_multiplier',1.0),
            signal_basis_anchor=deepcopy(series['signal_basis_anchor']))
    return result


class UnitGuard(ActionGuard):
    def __init__(self,book,codec,contract,*,qualified=None,reused=None):
        need(reused is not None and reused['target_independence_qualified'] is True
             and reused['held_target_holding_qualified'] is True,'EXACT_ADMITTED_ORDINARY_COMPONENT_SCOPE')
        super().__init__(book,target_independence_qualified=True,held_target_holding_qualified=True)
        self.codec=codec;self.contract=contract;self.qualified=qualified
        self.source_checks=[];self.unit_checks=[];self.prepared=[];self.refusals=[];self.current_windows={}

    def unknown_action(self,packet):
        return packet.day>EVENT and (any(t.security_id==SOURCE for t in packet.terminal)
            or any(s.parent_security_id==SOURCE for s in packet.spins))

    def relevant(self,state,packet):
        result=super().relevant(state,packet)
        unit_day=packet.day==EVENT or packet.day in self.codec.refusals or self.unknown_action(packet)
        unit_day=unit_day or any(b.security_id==SOURCE and b.split_ratio!=1.0 for b in packet.bars)
        if not unit_day:return result
        result=deepcopy(result) if result else dict(terminal=[],spinoff=[])
        result['unit_input_guard']=dict(source_security_id=SOURCE,session=packet.day,
            kind='CONTINUING_UNIT_REPORTING_BOUNDARY_NOT_FABRICATED_ECONOMIC_TERMINAL',
            input_refusal=deepcopy(self.codec.refusals.get(packet.day)),unknown_source_action=self.unknown_action(packet))
        return result

    def prior_saved(self,prior,day):
        current=self.journal.read_checkpoint(self.book/'checkpoint.json.gz')
        need(current['source_cursor']==prior.last_processed_session<day and current['run']['state']==prior.to_dict(),
             'CANONICAL_CURRENT_SAVED_IDENTICAL_BEFORE_UNIT_PREPARE_GUARD')
        matches=[p for p in (self.book/'pre-event').glob(day+'-*.json.gz')
            if self.journal.read_checkpoint(p)==current]
        need(len(matches)==1,'ACTUAL_NEW_PRE_EVENT_ARCHIVE_BEFORE_UNIT_PREPARE_GUARD')
        path=matches[0];current_path=self.book/'checkpoint.json.gz'
        row=dict(session=day,path=path.name,outer_sha256=current['sha256'],
            inner_sha256=current['run']['checkpoint_sha256'],state_sha256=current['run']['state_sha256'],
            prior_session=current['source_cursor'],current_saved_identical_before_guard=True,
            current_file=dict(bytes=current_path.stat().st_size,sha256=sha(current_path.read_bytes())))
        if row not in self.pre_events:self.pre_events.append(row)
        return current

    def prepare(self,buffer,prior,version,*,formation=False):
        day=buffer.current.day
        gated=day==EVENT or day in self.codec.refusals or self.unknown_action(buffer.current)
        gated=gated or any(b.security_id==SOURCE and b.split_ratio!=1.0 for b in buffer.current.bars)
        saved=False
        try:
            if gated:self.prior_saved(prior,day);saved=True
            need(day not in self.codec.refusals,'UNIT_NATIVE_BASIS_OR_PREIMAGE_REFUSAL_BEFORE_PREPARE')
            need(not self.unknown_action(buffer.current),'UNKNOWN_FUTURE_SOURCE_ACTION_REFUSES_BEFORE_PREPARE')
            unit_scope(prior,day)
        except ValueError as error:
            self.refusals.append(dict(session=day,stage='BEFORE_BUFFER_PREPARE',reason=str(error),
                current_saved_before_refusal=saved,financial_advance_authorized=False))
            raise
        result=self.original_prepare(buffer,prior,version,formation=formation)
        proof=window_record(buffer,result,self.codec,self.contract['window_length'])
        self.current_windows[day]=proof;self.prepared.append(proof)
        return result

    def advance(self,run,published):
        day=published.session;need(EVENT<=day<=END,'EXACT_SELECTED_UNIT_SUFFIX_BOUND')
        checks=unit_scope(run.state,day)
        need(day not in self.codec.refusals and day in self.current_windows,'ACTUAL_UNIT_WINDOW_PREPARED_WITHOUT_REFUSAL')
        if day==EVENT:self.pre_event(run,day)
        previous=self.runtime.checkpoint(run);old_events=deepcopy(run.state.ledger['events'])
        following=super().advance(run,published)
        checkpoint=self.runtime.checkpoint(following)
        if day==EVENT:
            added=following.state.ledger['events'][len(old_events):]
            need(following.state.ledger['events'][:len(old_events)]==old_events
                 and not any(e.get('security_id')==SOURCE or (e.get('detail') or {}).get('parent_security_id')==SOURCE for e in added),
                 'UNHELD_UNIT_EVENT_POSTS_NO_SOURCE_SHARE_CASH_OR_CHILD_PACKAGE_FLOW')
        proof=anchor_record(following.state,self.current_windows[day]);self.unit_checks.append(proof)
        self.source_checks.extend(checks)
        if day in FIRST:
            restored=self.runtime.restore(checkpoint,policy=following.policy,input_sha256=following.input_sha256)
            need(self.runtime.checkpoint(restored)==checkpoint,'ACTUAL_UNIT_TWO_SESSION_ENTIRE_CANONICAL_RESTORE')
            row=role_record(previous,checkpoint,day)
            if self.qualified is not None:need(row==self.qualified[len(self.observed)],'FRESH_UNIT_ENTIRE_FIRST_TWO_STATES_AND_ROLES')
            self.observed.append(row);self.components.append(dict(session=day,prior_checkpoint=previous,
                publication=material(published),checkpoint=checkpoint))
        return following

    def __enter__(self):
        super().__enter__();self.buffer_class=self.backtest.Buffer
        self.original_prepare=self.buffer_class.prepare
        self.buffer_class.prepare=lambda buffer,*a,**k:self.prepare(buffer,*a,**k)
        return self

    def __exit__(self,*args):
        self.buffer_class.prepare=self.original_prepare
        return super().__exit__(*args)
