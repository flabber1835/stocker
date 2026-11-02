"""One dated closing-proxy scope; all other canonical ownership is untouched."""
from copy import deepcopy
import ast
from fractions import Fraction
import json
import math
import inspect
from pathlib import Path

from p01_factual_batch_guard import ActionGuard,roles
from p01_native_resume_contract import (SOURCE,IAC,END,FIRST,NATIVE_SHA,need,sha,digest,specification)
from system_campaign_discovery_context import material

SOURCE_MODULES={'sentinel/core/kernel.py':'sentinel__core__kernel.py.txt',
    'sentinel/controller/terminal_returns.py':'sentinel__controller__terminal_returns.py.txt',
    'shared/stock_strategy_shared/wealth_core/terminal.py':'shared__stock_strategy_shared__wealth_core__terminal.py.txt',
    'shared/stock_strategy_shared/wealth_core/adapter.py':'shared__stock_strategy_shared__wealth_core__adapter.py.txt'}


def source_shape(files,expected):
    """Pure source inspection; this never imports or calls canonical code."""
    need(set(files)==set(SOURCE_MODULES) and all(sha(v)==expected[k] for k,v in files.items()),
         'EXACT_FROZEN516_ACTION_AND_CLOSING_SOURCE_BYTES')
    trees={k:ast.parse(v) for k,v in files.items()}
    def fn(key,name):
        matches=[n for n in trees[key].body if isinstance(n,ast.FunctionDef) and n.name==name]
        need(len(matches)==1,'ONE_EXACT_CANONICAL_SOURCE_FUNCTION_'+name);return matches[0]
    kernel=fn('sentinel/core/kernel.py','advance_session')
    calls=[n for n in ast.walk(kernel) if isinstance(n,ast.Call)]
    plans=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='plan_session']
    witnesses=[n for n in calls if isinstance(n.func,ast.Attribute) and n.func.attr=='values'
        and isinstance(n.func.value,ast.Name) and n.func.value.id=='terminal_returns']
    need(len(plans)==len(witnesses)==1 and plans[0].lineno<witnesses[0].lineno,
         'CANONICAL_CLOSING_WITNESS_AFTER_ORDINARY_SESSION_PLAN')
    terminal=fn('shared/stock_strategy_shared/wealth_core/terminal.py','apply_terminal')
    empty=[n for n in terminal.body if isinstance(n,ast.If) and ast.dump(n.test)==
        ast.dump(ast.parse('not held',mode='eval').body)]
    need(len(empty)==1 and any(isinstance(n,ast.Constant) and n.value=='NOT_HELD' for n in ast.walk(empty[0]))
         and any(isinstance(n,ast.Return) for n in empty[0].body),'EXACT_UNHELD_TERMINAL_EARLY_RETURN')
    economic=[n for n in ast.walk(terminal) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
        and n.func.id in ('resolve_settlement','_apply_cash','_apply_conversion','_apply_write_off')]
    need(economic and all(n.lineno>empty[0].end_lineno for n in economic),
         'UNHELD_RETURN_PRECEDES_ANY_CASH_SETTLEMENT_OR_EPISODE_APPLICATION')
    adapter='shared/stock_strategy_shared/wealth_core/adapter.py'
    transform=fn(adapter,'_transform_pending_for_terminal')
    independent=[n for n in ast.walk(transform) if isinstance(n,ast.If) and ast.dump(n.test)==
        ast.dump(ast.parse('po.security_id != terms.security_id',mode='eval').body)]
    need(len(independent)==1 and any(isinstance(n,ast.Continue) for n in independent[0].body)
         and any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='append'
            and len(n.args)==1 and isinstance(n.args[0],ast.Name) and n.args[0].id=='po'
            for n in ast.walk(independent[0])),'OTHER_SECURITY_PENDING_OBJECT_PRESERVED_BY_CANONICAL_TRANSFORM')
    step=fn(adapter,'step_session')
    decisions=[n for n in ast.walk(step) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='decide']
    need(len(decisions)==1 and any(k.arg=='admission_veto_security_ids' and isinstance(k.value,ast.Name)
         and k.value.id=='terminated' for k in decisions[0].keywords),'EXISTING_TERMINAL_ADMISSION_VETO_REMAINS_CANONICAL')
    functions=(('sentinel/core/kernel.py',kernel),
        ('shared/stock_strategy_shared/wealth_core/terminal.py',terminal),
        (adapter,transform),(adapter,step),
        ('sentinel/controller/terminal_returns.py',fn('sentinel/controller/terminal_returns.py','values')))
    return dict(source_files={k:sha(v) for k,v in files.items()},
        function_preimages={key+':'+node.name:dict(sha256=sha(ast.get_source_segment(files[key].decode(),node).encode()),
            first_line=node.lineno,last_line=node.end_lineno) for key,node in functions},
        ordinary_plan_line=plans[0].lineno,closing_witness_line=witnesses[0].lineno,
        unheld_return_line=empty[0].lineno,pending_identity_branch_line=independent[0].lineno,
        closing_witness_after_ordinary_plan=True,unheld_returns_before_cash_or_settlement=True,
        other_security_pending_preserved=True,existing_terminal_admission_veto_unchanged=True,
        canonical_source_or_function_modified=False)


def source_contract(binding):
    from full_system_core import hosted
    hosted()
    from sentinel.core import kernel
    from sentinel.controller import terminal_returns
    from stock_strategy_shared.wealth_core import terminal,adapter
    modules=(kernel,terminal_returns,terminal,adapter)
    files={name:Path(module.__file__).read_bytes() for name,module in zip(SOURCE_MODULES,modules)}
    return source_shape(files,binding.source_map['successor_all_sources'])


def native_seam_scope(state,session):
    if session!=END:return []
    value=state if isinstance(state,dict) else state.__dict__
    wealth=value['wealth_core'];pending=value['pending'];ledger=value['ledger'];median=value['median5']
    need(type(wealth.get('episodes')) is dict and type(pending) is list
         and all(type(p) is dict and type(p.get('security_id')) is str for p in pending),
         'FULL_NATIVE_SOURCE_ROLE_AND_PENDING_SCHEMA')
    held=[e for e in wealth['episodes'].values() if e['security_id']==SOURCE]
    need(not held,'NATIVE_CLOSING_PROXY_CANNOT_SETTLE_SOURCE_HOLDING')
    need(not any(e.get('exit_pending',False) for e in held),'NATIVE_SOURCE_EXIT_FLAG_UNSUPPORTED')
    need(not any(p['security_id']==SOURCE for p in pending),'NATIVE_SOURCE_ANY_PENDING_INTENT_UNSUPPORTED')
    need(type(ledger) is dict and set(ledger)=={'events','receivables'} and type(ledger['receivables']) is list
         and all(type(r) is dict and type(r.get('security_id')) is str for r in ledger['receivables']),
         'EXACT_REGISTERED_LEDGER_CLAIM_SCHEMA')
    need(not any(r['security_id']==SOURCE for r in ledger['receivables']),'NATIVE_SOURCE_OUTSTANDING_RECEIVABLE_UNSUPPORTED')
    for key in ('unresolved_terminals','terminal_pending_terms','terminal_pending_sessions'):
        need(type(wealth.get(key,{})) is dict and SOURCE not in wealth.get(key,{}),'NATIVE_SOURCE_UNRESOLVED_CLAIM_UNSUPPORTED')
    return [dict(scope_id='MTCH2_JUNE30_UNHELD_CLOSING_WITNESS_ONLY',session=session,security_id=SOURCE,
        unheld=True,all_source_pending_absent=True,source_exit_flags_absent=True,source_receivables_absent=True,
        source_selected=SOURCE in median['selected'],no_unresolved_terminal_claim=True)]


class SourceObserver:
    def __init__(self,binding,rows):
        self.binding=binding;self.rows=rows;self.records=[]

    def apply(self,packet,loaded):
        changed=self.original(packet,loaded)
        # Canonical startup reloads archived descriptors into fresh registered
        # codec objects. The delegated codec above authenticates registration;
        # bind this last descriptor by its exact type/hash, not object lifetime.
        last=self.binding.objects[-1]
        if (isinstance(loaded,type(last)) and loaded.sha256==last.sha256==
                self.binding.parent['repairs'][-1]['sha256'] and packet.day==END):
            from research.bounded_20y.run import vendor
            terms=[t for t in changed.terminal if t.security_id==SOURCE]
            need(len(terms)==1 and digest(material(terms[0]))==NATIVE_SHA,'EXACT_NATIVE_POST_ALL11_TERMINAL')
            bars={}
            for key,row in self.rows.items():
                expected=vendor(row);matches=[b for b in changed.bars if b.security_id==row['security_id']]
                need(len(matches)==1 and material(matches[0])==material(expected),'ALL_QUOTE_FIELDS_PRESERVED_POST_ELEVEN_CODECS')
                bars[row['security_id']]=material(matches[0])
            source=next(b for b in changed.bars if b.security_id==SOURCE);term=terms[0]
            need(term.cash_per_share==source.raw_close and source.raw_close is not None
                 and math.isfinite(source.raw_close) and source.raw_close>0 and source.volume>0,
                 'EXACT_NATIVE_PROXY_EQUALS_CURRENT_POSITIVE_VOLUME_CLOSE')
            self.records.append(dict(session=END,post_all11_terminal=material(term),native_term_sha256=NATIVE_SHA,
                actual_source_bars=bars,raw_source_row_sha256={k:digest(v) for k,v in self.rows.items()},
                proxy_equals_current_raw_close=True,source_volume_positive=True,
                phase='CLOSING_WITNESS_ONLY_NOT_LEGAL_CASH_OR_OPENING_FILL',packet_mutated_by_observer=False))
        return changed

    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from research.pooled_vacancy_funding import backtest
        self.backtest=backtest;self.original=backtest.apply_repair;backtest.apply_repair=self.apply;return self

    def __exit__(self,*args):self.backtest.apply_repair=self.original


class NativeGuard(ActionGuard):
    def __init__(self,book,*,qualified=None,reused=None):
        need(reused is not None and reused['target_independence_qualified'] is True
             and reused['held_target_holding_qualified'] is True,'EXACT_ADMITTED_COMPONENT_REQUIRED')
        super().__init__(book,target_independence_qualified=True,held_target_holding_qualified=True)
        self.qualified=qualified;self.native_seam_checks=[];self.closing_proofs=[]
        self.witness_calls=[]

    def witness(self,*,prior,published):
        need(inspect.currentframe().f_back.f_code is self.kernel.advance_session.__code__,
             'CLOSING_SENSOR_ONLY_AT_EXACT_CANONICAL_KERNEL_CALLSITE')
        value=self.original_witness(prior=prior,published=published)
        if published.session==END:
            terms=[t for t in published.terminal_events if t.security_id==SOURCE]
            bars=[b for b in published.bars if b.security_id==SOURCE]
            need(len(terms)==len(bars)==1 and digest(material(terms[0]))==NATIVE_SHA
                 and terms[0].cash_per_share==bars[0].raw_close,'ACTUAL_CURRENT_CLOSE_NATIVE_WITNESS_PREIMAGE')
            anchor=prior.feed['series'][SOURCE]['signal_basis_anchor']
            need(anchor[0]==prior.last_processed_session and Fraction(str(anchor[1]))>0
                 and Fraction(str(anchor[2]))>0,'EXACT_OWNED_PRIOR_CLOSING_SIGNAL_RAW_BASIS')
            expected=float(Fraction(str(bars[0].raw_close))*Fraction(str(bars[0].split_ratio))
                           *Fraction(str(anchor[2]))/Fraction(str(anchor[1])))
            selected=SOURCE in prior.median5['selected']
            need((selected and value.get(SOURCE)==expected) or (not selected and SOURCE not in value),
                 'EXACT_CANONICAL_CLOSING_SENSOR_CURRENT_CLOSE_ONLY')
            self.witness_calls.append(dict(session=END,source_selected=selected,prior_signal_basis_anchor=deepcopy(anchor),
                actual_terminal_witness=value.get(SOURCE),expected_current_close_normalized=expected if selected else None,
                current_close_equivalence=True,actual_canonical_kernel_callsite_verified=True))
        return value

    def relevant(self,state,packet):
        result=super().relevant(state,packet)
        if packet.day!=END:return result
        result=deepcopy(result) if result else dict(terminal=[],spinoff=[])
        known={digest(t) for t in result['terminal']}
        for term in packet.terminal:
            if term.security_id==SOURCE and digest(material(term)) not in known:result['terminal'].append(material(term))
        need(any(t['security_id']==SOURCE for t in result['terminal']),'NATIVE_SOURCE_PRE_EVENT_REPORTING_REQUIRED')
        return result

    def advance(self,run,published):
        day=published.session
        need(day in FIRST,'ONLY_JUNE30_TRANSITION_AUTHORIZED')
        self.pre_event(run,day);checks=native_seam_scope(run.state,day)
        terms=[t for t in published.terminal_events if t.security_id==SOURCE]
        bars=[b for b in published.bars if b.security_id==SOURCE]
        need(len(terms)==len(bars)==1 and digest(material(terms[0]))==NATIVE_SHA
             and terms[0].cash_per_share==bars[0].raw_close,'ACTUAL_CURRENT_CLOSE_NATIVE_WITNESS_PREIMAGE')
        previous=self.runtime.checkpoint(run);old_ledger=deepcopy(run.state.ledger)
        # The frozen ordinary guard retains all18 future scopes and native
        # source constraints. None is weakened by this one-day wrapper.
        following=super().advance(run,published)
        need(len(self.witness_calls)==1,'ONE_ACTUAL_POST_PLAN_CLOSING_WITNESS_CALL')
        native_seam_scope(following.state,day)
        need(following.state.ledger['events'][:len(old_ledger['events'])]==old_ledger['events']
             and not any(e.get('security_id')==SOURCE for e in following.state.ledger['events'][len(old_ledger['events']):]),
             'UNHELD_PROXY_CANNOT_POST_CASH_CONVERSION_OR_SOURCE_LEDGER_EVENT')
        checkpoint=self.runtime.checkpoint(following)
        restored=self.runtime.restore(checkpoint,policy=following.policy,input_sha256=following.input_sha256)
        need(self.runtime.checkpoint(restored)==checkpoint,'ACTUAL_ONE_DAY_ENTIRE_CANONICAL_RUNTIME_RESTORE')
        row=dict(session=day,prior_state_sha256=previous['state_sha256'],state_sha256=checkpoint['state_sha256'],
                 before=roles(run.state),after=roles(following.state))
        if self.qualified is not None:need([row]==self.qualified,'FRESH_FINANCE_ENTIRE_QUALIFIED_ONE_DAY_STATE_AND_ROLES')
        self.observed.append(row);self.native_seam_checks.extend(checks)
        self.components.append(dict(session=day,prior_checkpoint=previous,publication=material(published),checkpoint=checkpoint))
        self.closing_proofs.append(dict(**self.witness_calls[0],source_ledger_events_added=0,source_claims_or_pending_created=False,
            financial_state_or_input_modified_by_guard=False))
        return following

    def __enter__(self):
        super().__enter__()
        from sentinel.core import kernel
        from sentinel.controller import terminal_returns
        self.kernel,self.terminal_returns=kernel,terminal_returns
        self.original_witness=terminal_returns.values;terminal_returns.values=self.witness
        return self

    def __exit__(self,*args):
        self.terminal_returns.values=self.original_witness
        return super().__exit__(*args)
