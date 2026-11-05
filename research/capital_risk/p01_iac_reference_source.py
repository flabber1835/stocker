"""Hosted input/Buffer proof against recorded reference; no financial advance."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from p01_iac_unit_contract import FIRST,INPUT,HERE,need,sha,digest,specification
from p01_iac_unit_guard import source_contract,window_record,anchor_record,unit_scope
from p01_iac_unit_recovery_guard import resolve_buffer,BACKTEST,BACKTEST_SHA,ADAPTER
from p01_iac_unit_codec import InputCodec
from p01_iac_quote_epoch import historical_epoch
from p01_iac_reference_evidence import encoded,same,validate_reference,ORIGIN,ADMISSION,APPROVED
from system_campaign_discovery_context import material

SCHEMA='research.p01-iac-reference-normalization-source-proof/1'
COMPILER_ORIGIN='NEW_HOSTED_SOURCE_COMPILER_CHECK'
REPORT_ORIGIN='NEW_READONLY_CANONICAL_REPORT_ON_RESTORED_OLD_STATE'
REPORT_RUNTIME_SHA='20f2d5bf1758d0574954b2e2e6700b6ad20c22d433a73c46112cd08d4d6735c0'


def preparation_shape(raw,expected_sha):
    """Bind the actual frozen reconstruction/call order without running it."""
    need(sha(raw)==expected_sha==BACKTEST_SHA,'REFERENCE_EXACT516_BACKTEST_PREPARATION_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='run_backtest']
    source=ast.unparse(node)
    for expression in ('offset = full_axis.index(START) - 425',
        'axis = full_axis[offset:full_axis.index(END) + 1]',
        'iterator = inputs.packets(args.bundle, args.archive, first=axis[0], last=END)',
        'buffer = adapter.Buffer()', 'packet = apply_repair(packet, repair)',
        'buffer.append(packet)', 'published = buffer.prepare(run.state, 1 if formation else run.state.data_version + 1, formation=formation)'):
        need(expression in source,'REFERENCE_EXACT_SOURCE_PACKET_AXIS_AND_PREPARE_CALLSITE')
    return dict(backtest_sha256=expected_sha,run_backtest_sha256=sha(ast.get_source_segment(raw.decode(),node).encode()),
        original_axis_offset=425,overlays_before_append=True,canonical_prepare_version=True)


def report_shape(raw,pins,accounting_raw,expected_accounting_sha):
    """Pure preimage binding for the unchanged full report callsite."""
    need(sha(raw)==REPORT_RUNTIME_SHA and sha(accounting_raw)==expected_accounting_sha,
         'REFERENCE_EXACT_UNCHANGED_FULL_REPORT_AND_ACCOUNTING_SOURCE')
    node,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='report']
    calls=[ast.unparse(n.func) for n in ast.walk(node) if isinstance(n,ast.Call)]
    need(all(name in calls for name in ('reconcile','terminal.final_report','runtime.checkpoint',
         'PortfolioState.from_dict','ledger.Ledger.from_dict','config')),
         'REFERENCE_EXACT_FULL_LEDGER_CANONICAL_REPORT_CALLS')
    names=['shared/stock_strategy_shared/wealth_core/'+n+'.py' for n in ('terminal','ledger','state','marks','funding')]
    return dict(report_origin=REPORT_ORIGIN,report_source_file='p01_iac_unit_run.py',report_source_sha256=REPORT_RUNTIME_SHA,
        report_function_sha256=sha(ast.get_source_segment(raw.decode(),node).encode()),
        canonical_source_files={n:pins[n] for n in names},independent_accounting_source_file='p01_factual_batch_accounting.py',
        independent_accounting_source_sha256=expected_accounting_sha,financial_transitions=0)


class NoAdvance:
    """Exception-safe blockers for actual runtime/kernel/strategy entry aliases."""
    def __init__(self,targets):self.targets=targets;self.calls=[];self.saved=[]
    def __enter__(self):
        try:
            for label,module,name in self.targets:
                original=getattr(module,name)
                need(callable(original),'REFERENCE_REQUIRED_ADVANCE_BLOCKER_INTERFACE')
                self.saved.append((module,name,original))
                def refuse(*args,_label=label,**kwargs):
                    self.calls.append(_label)
                    raise ValueError('REFUSED_REFERENCE_SOURCE_CHECK_FINANCIAL_ADVANCE:'+_label)
                setattr(module,name,refuse)
            return self
        except BaseException:
            self.__exit__(None,None,None);raise
    def __exit__(self,*args):
        for module,name,original in reversed(self.saved):setattr(module,name,original)
    def proof(self):
        need(self.calls==[],'REFERENCE_ZERO_RUNTIME_KERNEL_OR_STRATEGY_ADVANCE_CALLS')
        return dict(installed_entrypoints=[label for label,module,name in self.targets],attempted_calls=[],financial_transitions=0)


def check_prepared(recorded,published,before,after,window,application):
    need(same(recorded,published),'REFERENCE_WHOLE_RECORDED_PUBLICATION_EQUALS_NEW_PREPARATION')
    need(same(before,after),'REFERENCE_PREPARATION_ENTIRE_PRIOR_RUNTIME_UNCHANGED')
    need(window['session']==published['session']==application['session']
         and window['full_window_before_feature_bound'] is True
         and application['derivation_before_buffer_append'] is True,
         'REFERENCE_NEW_ACTUAL_COMPILER_RING_AND_PUBLICATION_CLOCK')
    return dict(session=published['session'],recorded_publication_sha256=digest(recorded),
        prepared_publication_sha256=digest(published),complete_typed_publication_equal=True,
        prior_runtime_sha256=digest(before),prior_runtime_unchanged=True,
        origin=COMPILER_ORIGIN,prepared_publication=deepcopy(published))


def restore_reference(binding,reference,contract):
    """New canonical restore of approved saved objects, never gate/book adoption."""
    from research.pooled_vacancy_funding import runtime
    from sentinel.core.session import SessionState
    from stock_strategy_shared.wealth_core.funding import config
    from dataclasses import asdict
    import p01_iac_unit_fixture_review as fixture
    parent=binding.parent;zero=reference['zero'];paths=reference['components'];labels=[]
    for label,checkpoint in [('old-epoch-zero',zero['epoch_checkpoint']['run']),('old-input-zero',zero['input_checkpoint']['run']),
        *[(f'old-reference/{r["session"]}/{k}',r[k]) for r in paths for k in ('prior_checkpoint','checkpoint')],
        ('old-reference-final',reference['final']['run'])]:
        run=runtime.restore(checkpoint,policy=parent['base']['policy'],input_sha256=checkpoint['input_sha256'])
        need(same(runtime.checkpoint(run),checkpoint),'REFERENCE_NEW_ACTUAL_FULL_CANONICAL_RUNTIME_RESTORE')
        labels.append(dict(label=label,runtime_sha256=digest(checkpoint)))
    checker=fixture._body('review_loaded').__globals__['synthetic_component']
    cfg=config(parent['base']['policy'])
    wires=checker(reference['component'],contract,reference['origin'],reference['rows'],
        dict(policy=parent['base']['policy'],fields=asdict(cfg),config_hash=cfg.config_hash()),binding.source_map,
        paths[0]['checkpoint']['state'],lambda value:SessionState.from_dict(deepcopy(value)).to_dict(),
        input_zero_state=zero['input_checkpoint']['run']['state'],reference_components=paths,
        qualifier_checkpoint=reference['final'],input_zero_checkpoint=zero['input_checkpoint'])
    need(len(wires)==18,'REFERENCE_ALL_EIGHTEEN_APPROVED_SYNTHETIC_WIRES')
    for index,wire in enumerate(wires):
        need(same(SessionState.from_dict(deepcopy(wire)).to_dict(),wire),'REFERENCE_NEW_CANONICAL_SYNTHETIC_WIRE_ROUNDTRIP')
        labels.append(dict(label='old-synthetic/'+str(index),state_sha256=digest(wire)))
    return dict(origin='NEW_HOSTED_CANONICAL_RESTORE_OF_OLD_RECORDED_DATA',checked=labels,
        synthetic_wires=18,financial_transitions=0,source_gate_adoption=False,financial_authority=False)


def source_check(old,out,rows,reference):
    """Reconstruct only source compilation/preparation using recorded priors."""
    from full_system_core import hosted
    hosted()
    from research.pooled_vacancy_funding import backtest,runtime
    from research.pooled_input_support import adapter,bundle,inputs
    import sentinel.core.kernel as kernel
    import stock_strategy_shared.wealth_core.live as live
    import stock_strategy_shared.wealth_core.adapter as core_adapter
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    with historical_epoch(old,out,specification()) as binding,InputCodec(rows,binding.parent) as codec:
        loaded=backtest.load_repair(HERE/INPUT,resume_session=binding.parent['source_cursor'],
            predecessor_checkpoint_sha256=binding.parent['run']['checkpoint_sha256'])
        objects=(*binding.objects,loaded);need(len(objects)==12,'REFERENCE_ALL_TWELVE_INPUTS_BEFORE_RESTORE')
        contract=source_contract(binding);cls,interface=resolve_buffer(backtest,adapter,contract)
        callsite=preparation_shape(Path(backtest.__file__).read_bytes(),binding.source_map['successor_all_sources'][BACKTEST])
        reference=dict(reference,origin=deepcopy(codec.origin),rows=rows)
        names={'runtime':runtime,'kernel':kernel,'live':live,'core_adapter':core_adapter}
        modules={'runtime':'research/pooled_vacancy_funding/runtime.py','kernel':'sentinel/core/kernel.py',
            'live':'shared/stock_strategy_shared/wealth_core/live.py','core_adapter':'shared/stock_strategy_shared/wealth_core/adapter.py'}
        pins={k:sha(Path(module.__file__).read_bytes()) for k,module in names.items()}
        need(all(pins[k]==binding.source_map['successor_all_sources'][modules[k]] for k in pins)
             and runtime.advance_session is kernel.advance_session and kernel.plan_session is live.plan_session,
             'REFERENCE_ACTUAL516_RUNTIME_KERNEL_STRATEGY_ALIAS_PINS')
        targets=[('runtime.advance',runtime,'advance'),('runtime.advance_session',runtime,'advance_session'),
            ('kernel.advance_session',kernel,'advance_session'),('kernel.plan_session',kernel,'plan_session'),
            ('live.plan_session',live,'plan_session'),('core_adapter.step_session',core_adapter,'step_session')]
        full=bundle.axis();axis=full[full.index(backtest.START)-425:full.index(backtest.END)+1]
        need(len(axis)>425 and axis[425]==backtest.START,'REFERENCE_EXACT_FROZEN_FULL_AXIS_OFFSET')
        buffer=cls();checks=[];windows=[];paths={r['session']:r for r in reference['components']}
        with NoAdvance(targets) as blocker:
            restores=restore_reference(binding,reference,contract)
            for packet in inputs.packets(Path('/frozen/bundle'),Path('/frozen/archive/corpus.zip'),first=axis[0],last=backtest.END):
                for obj in objects:packet=backtest.apply_repair(packet,obj)
                buffer.append(packet)
                if packet.day not in paths:continue
                row=paths[packet.day];prior=runtime.restore(row['prior_checkpoint'],policy=binding.parent['base']['policy'],
                    input_sha256=reference['zero']['successor_input_sha256'])
                before=runtime.checkpoint(prior);unit_scope(prior.state,packet.day)
                published=buffer.prepare(prior.state,prior.state.data_version+1,formation=False)
                window=window_record(buffer,published,codec,contract['window_length'])
                following=runtime.restore(row['checkpoint'],policy=prior.policy,input_sha256=prior.input_sha256)
                windows.append(anchor_record(following.state,window))
                matches=[a for a in codec.applied if a['session']==packet.day]
                need(len(matches)==1 and not codec.refusals,'REFERENCE_EXACT_NEW_COMPILER_APPLICATION_WITHOUT_REFUSAL')
                checks.append(check_prepared(row['publication'],material(published),before,runtime.checkpoint(prior),window,matches[0]))
                if packet.day==FIRST[-1]:break
            need([v['session'] for v in checks]==list(FIRST),'REFERENCE_TWO_ACTUAL_PREPARATIONS_ONLY')
            noadvance=blocker.proof()
        return dict(origin=COMPILER_ORIGIN,applications=deepcopy(codec.applied),refusals=[],unit_window_anchor_checks=windows,
            prepared_publications=checks,canonical_restores=restores,advance_blocker=noadvance,
            interface=interface,callsite=callsite,advance_source_files=pins,financial_transitions=0,
            source_contract=contract,origin_basis=dict(source_series=deepcopy(codec.origin),
                source_series_sha256=digest(codec.origin),original_outer_sha256=binding.parent['sha256']))
