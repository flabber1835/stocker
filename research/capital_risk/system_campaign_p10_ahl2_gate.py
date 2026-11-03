"""Hosted changed-input old refusal and complete native FAST/REFERENCE gate."""
import ast
from copy import deepcopy
from dataclasses import replace
import gzip
import json
from pathlib import Path

from system_campaign_p10_ahl2_contract import (SID, CURSOR, NEXT, NATIVE, AFFECTED, TAINT,
    encoded, digest, sha, need, function, physical_tree)
from system_campaign_p10_ahl2_epoch import prepare_epoch, write_json
from system_campaign_p10_ahl2_input import document_bytes, expected_document, load
from system_campaign_p10_ahl2_observe import Observer, cash_postcondition
from system_campaign_p10_ahl2_replay import replay
from system_campaign_p10_ahl2_wire import object_bytes

STATUS = 'P10_OWN_FOURTH_INPUT_CHANGED_PATH_QUALIFIED'


def records(path):
    path = Path(path)
    result = []
    for p in sorted((path / 'actual-runtime-path').glob('*.json.gz')):
        result.append(object_bytes(p.read_bytes(), gzip_declared=True, expanded_limit=256*1024**2))
    return result


def actual_v_guard_falsifier(observer, source_root, binding):
    """Only the disposable mutant loses a guard; the actual run keeps it."""
    from full_system_core import hosted
    hosted()
    from stock_strategy_shared.wealth_core import capital_risk
    need(observer.risk_sample is not None, 'P10_ACTUAL_CANONICAL_NATIVE_GUARD_SAMPLE_REQUIRED')
    ep, bar, day, cfg = observer.risk_sample
    bad = replace(bar, signal_sessions=tuple('1900-01-01' for _ in range(21)))
    original_ep = deepcopy(ep)
    try:
        observer.original_risk(ep, bars=[bad], session=day, cfg=cfg)
    except ValueError as error:
        need(str(error) == 'REFUSED_VOLATILITY_CAUSAL_AXIS' and ep == original_ep,
             'P10_ORIGINAL_ACTUAL_V_GUARD_REFUSES_BAD_AXIS_WITHOUT_MUTATION')
    else:
        raise ValueError('P10_ORIGINAL_V_GUARD_FALSIFIER_NOT_REFUSED')
    raw = (Path(source_root) / 'shared/stock_strategy_shared/wealth_core/capital_risk.py').read_bytes()
    need(sha(raw) == binding.source_binding['all_sources']['shared/stock_strategy_shared/wealth_core/capital_risk.py'],
         'P10_ACTUAL_GUARD_REMOVAL_EXACT_OWN_SOURCE')
    fn = function(raw, 'volatility_stop')
    original_function_sha256 = sha(ast.dump(fn, include_attributes=False).encode())
    guard, = [n for n in ast.walk(fn) if isinstance(n, ast.If) and ast.unparse(n.test) ==
              'bar is None or list(bar.signal_sessions or ()) != axis or len(bar.closes) < 21']
    guard.test = ast.Constant(False)
    mutant_function_sha256 = sha(ast.dump(fn, include_attributes=False).encode())
    scope = dict(vars(capital_risk))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<DISPOSABLE-guard-removal-falsifier-only>', 'exec'), scope)
    mutant_ep = deepcopy(original_ep)
    mutant_result = scope['volatility_stop'](mutant_ep, bars=[bad], session=day, cfg=cfg)
    need(capital_risk.volatility_stop is observer.original_risk,
         'P10_GUARD_REMOVAL_NEVER_INSTALLED_ON_REAL_MODULE_OR_SUFFIX')
    return dict(case='actual_native21_causal_axis_predicate_removal', original_refused=True,
                mutant_would_accept=True, original_module_unchanged=True,
                source_sha256=sha(raw), original_function_ast_sha256=original_function_sha256,
                mutant_function_ast_sha256=mutant_function_sha256, session=day,
                original_bar=observer.material(bar), bad_axis_bar=observer.material(bad),
                original_prior_episode=observer.material(original_ep),
                original_after_refusal_episode=observer.material(ep),
                mutant_after_episode=observer.material(mutant_ep), mutant_result=mutant_result,
                original_error='REFUSED_VOLATILITY_CAUSAL_AXIS', mutant_installed_on_real_module=False)


def parser_falsifiers(binding, observer, out):
    from research.pooled_vacancy_funding import backtest
    out = Path(out)
    tested = []
    for name, mutate in (
        ('missing_cash', lambda x:x['add'][0].pop('cash_per_share')),
        ('wrong_predecessor', lambda x:x.update(predecessor_checkpoint_sha256='0'*64)),
        ('consumed_date', lambda x:x['suppress'][0].update(session=CURSOR)),
        ('wrong_added_date', lambda x:x['add'][0].update(session=NATIVE))):
        value = expected_document(binding.spec)
        mutate(value)
        path = out / (name + '.json')
        path.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
        try:
            load(path, binding.spec, backtest.load_repair)
        except ValueError:
            tested.append(dict(case=name, exact_own_input_refused=True))
        else:
            raise ValueError('P10_EXACT_INPUT_FALSIFIER_NOT_REFUSED:' + name)
    value = expected_document(binding.spec)
    value['suppress'][0]['term_sha256'] = '0'*64
    path = out / 'wrong_native_hash.json'
    path.write_bytes((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    obj = backtest.load_repair(path, resume_session=CURSOR,
        predecessor_checkpoint_sha256=binding.spec['runtime_checkpoint_sha256'])
    packet = observer.packet_samples[NATIVE]
    before = deepcopy(packet)
    try:
        backtest.apply_repair(packet, obj)
    except ValueError as error:
        need(str(error).startswith('suppressed original terminal differs:') and packet == before,
             'P10_ACTUAL_CANONICAL_NATIVE_PREIMAGE_GUARD_AND_SOURCE_IMMUTABILITY')
    else:
        raise ValueError('P10_WRONG_NATIVE_TERM_FALSIFIER_NOT_REFUSED')
    tested.append(dict(case='wrong_native_hash', actual_canonical_apply_refused=True, source_unchanged=True))
    return tested


def synthetic_supported_cash(binding):
    """Explicit toy quantity; never claims the actual P10 held quantity."""
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core import v5, terminal
    from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    cfg = runtime.config(binding.parent['base']['policy'])
    core = PortfolioState.fresh(9000., n_slots=cfg.n_slots,
        entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
    core.episodes[0] = HoldingEpisode(SID, 'SYNTHETIC_AHL2', 'SYNTHETIC', 0, NATIVE, NATIVE,
        10., 10., 7, 7)
    core.slots[0].occupied_by = SID
    ledger = Ledger()
    terms = terminal.terminal_terms_from_dict(expected_document(binding.spec)['add'][0])
    before, events = deepcopy(core.to_dict()), deepcopy(ledger.to_dict())
    result = terminal.apply_terminal(core, terms, ledger=ledger, session=AFFECTED, cfg=cfg, phase='OPEN')
    proof = cash_postcondition(before, core.to_dict(), events, ledger.to_dict(),
        expected_document(binding.spec)['add'][0], result)
    once = deepcopy((core.to_dict(), ledger.to_dict()))
    second = terminal.apply_terminal(core, terms, ledger=ledger, session=AFFECTED, cfg=cfg, phase='OPEN')
    need(second['reason'] == 'NOT_HELD' and (core.to_dict(), ledger.to_dict()) == once,
         'P10_SUPPORTED_CANONICAL_CASH_SETTLEMENT_ONCE_ONLY')
    return dict(schema='research.p10-synthetic-supported-cash/1', synthetic=True,
        full_core_before=before, full_core_after=core.to_dict(), full_ledger_before=events,
        full_ledger_after=ledger.to_dict(), postcondition=proof, once_only=True,
        actual_held_quantity_claimed=False, financial_authority=False)


def qualification_valid(summary, spec):
    need(summary['status'] == STATUS and summary['schema'] == 'research.p10-ahl2-changed-qualification/1'
         and summary['financial_authority'] is False and summary['qualifier_state_adopted'] is False
         and summary['original_diagnostic_file_sha256'] == spec['diagnostic_checkpoint_sha256']
         and type(summary['candidate_transitions']) is int and summary['candidate_transitions'] == 10
         and summary['qualified_through'] == AFFECTED and summary['first_session'] == NEXT
         and summary['full_FAST_REFERENCE_publication_runtime_event_proof_equal'] is True
         and summary['actual_old_refusal_reproduced'] is True and summary['all21_guard_preserved'] is True,
         'P10_ACTUAL_CHANGED_FULL_GATE_BEFORE_FRESH_SUFFIX')
    restored = summary.get('actual_new_canonical_roundtrips')
    need(type(restored) is list and len(restored) == 20 and all(type(r) is dict
         and set(r) == {'mode','session','checkpoint_sha256','state_sha256','full_state_equal'}
         and r['mode'] in ('FAST','REFERENCE') and type(r['session']) is str and r['full_state_equal'] is True
         and all(type(r[k]) is str and len(r[k]) == 64 and all(c in '0123456789abcdef' for c in r[k])
                 for k in ('checkpoint_sha256','state_sha256')) for r in restored),
         'P10_ALL20_NEW_FULL_CANONICAL_ROUNDTRIPS_REQUIRED_BEFORE_SUFFIX')
    for mode in ('FAST','REFERENCE'):
        days = [r['session'] for r in restored if r['mode'] == mode]
        need(len(days) == len(set(days)) == 10 and days == sorted(days) and days[0] == NEXT and days[-1] == AFFECTED,
             'P10_EACH_TRANSPORT_ALL_CHANGED_SOURCE_SESSIONS_CANONICALLY_RESTORED')
    return summary


def qualify(root, previous, out, spec, *, source_root=Path('/variant')):
    from full_system_core import hosted
    hosted()
    from system_campaign_p10_ahl2_parent import read_checkpoint
    binding_source = json.loads((Path(previous) / 'source-bindings.json').read_bytes())
    physical_tree(source_root, binding_source, spec)  # Before canonical codec registration.
    from system_campaign_parallel_discovery_run import retained_inputs
    parent = read_checkpoint(Path(root) / spec['financial_strict_predecessor']['selected_checkpoint'])
    out = Path(out)
    paths, bindings, observers = {}, {}, {}
    for label, new_input, mode in (('old-refusal', False, 'FAST'), ('fast', True, 'FAST'), ('reference', True, 'REFERENCE')):
        target = out / label
        target.mkdir()
        with retained_inputs(root, parent, target):
            binding = prepare_epoch(root, previous, target, spec, new_input=new_input, source_root=source_root)
            observer = Observer(binding)
            try:
                replay(binding, mode=mode, processing_end=AFFECTED, observer=observer)
            except ValueError as error:
                if label != 'old-refusal':
                    raise
                need(str(error) == 'REFUSED_VOLATILITY_CAUSAL_AXIS', 'P10_REPRODUCE_EXACT_ACTUAL_OLD_REFUSAL')
            else:
                need(label != 'old-refusal', 'P10_OLD_INPUT_MUST_REPRODUCE_ORIGINAL_REFUSAL')
        paths[label] = records(target)
        bindings[label], observers[label] = binding, observer
    old, fast, reference = (paths[k] for k in ('old-refusal', 'fast', 'reference'))
    need(len(old) == len(fast) == len(reference) == 10 and old[-1]['session'] == AFFECTED
         and old[-1]['refusal']['message'] == 'REFUSED_VOLATILITY_CAUSAL_AXIS'
         and old[-1]['refusal']['committed'] is False
         and old[-1]['prior'] == old[-1]['refused_prior_after_checkpoint'],
         'P10_ACTUAL_OLD_NINE_SUCCESSFUL_AND_FAILED_TENTH')
    # Complete full material records, not only state hashes or selected fields.
    need(fast == reference and encoded(fast) == encoded(reference),
         'P10_ALL_CHANGED_FULL_PUBLICATIONS_PRIORS_RUNTIME_COMPONENTS_EXACT')
    for name in ('discovery-events.jsonl', 'retained-anchor-events.jsonl', 'anchor-qualifications/index.jsonl',
                 'diagnostic-book/daily.jsonl', 'diagnostic-input-epochs.jsonl', 'zero-input-epoch.json'):
        need((out / 'fast' / name).read_bytes() == (out / 'reference' / name).read_bytes(),
             'P10_ALL_CHANGED_CANONICAL_EVENT_PROOF_EPOCH_PATH_BYTES_EQUAL:' + name)
    fast_proofs = {p.name:p.read_bytes() for p in (out / 'fast/anchor-qualifications').glob('*.json')}
    ref_proofs = {p.name:p.read_bytes() for p in (out / 'reference/anchor-qualifications').glob('*.json')}
    need(fast_proofs == ref_proofs, 'P10_ALL_CHANGED_IMMUTABLE_ANCHOR_PROOF_FILES_EQUAL')
    # New input capability includes actual full-state restoration, not only output hashes.
    from research.pooled_vacancy_funding import runtime, backtest
    roundtrips = []
    for label in ('fast', 'reference'):
        target = out / ('roundtrip-' + label)
        target.mkdir()
        with retained_inputs(root, parent, target):
            b = bindings[label]
            for d in b.descriptors:
                obj = backtest.load_repair(b.out / 'book/repairs' / d['filename'],
                    resume_session=d['resume_session'], predecessor_checkpoint_sha256=d['predecessor_checkpoint_sha256'])
                need(obj.sha256 == d['sha256'], 'P10_ALL_FOUR_CANONICAL_INPUTS_PARSED_BEFORE_NEW_FULL_RESTORE')
            for record in paths[label]:
                cp = record['checkpoint']
                restored = runtime.checkpoint(runtime.restore(cp, policy=parent['base']['policy'],
                    input_sha256=b.run.input_sha256))
                need(restored == cp and encoded(restored) == encoded(cp), 'P10_EVERY_CHANGED_FULL_CANONICAL_STATE_ROUNDTRIP')
                roundtrips.append(dict(mode=label.upper(), session=record['session'],
                    checkpoint_sha256=cp['checkpoint_sha256'], state_sha256=cp['state_sha256'], full_state_equal=True))
    old_tail = (Path(previous) / 'diagnostic-book/daily.jsonl').read_bytes()[spec['journals']['daily']['bytes']:]
    rows = [json.loads(line) for line in old_tail.splitlines()]
    need(len(rows) == 9 and [r['checkpoint']['state_sha256'] for r in old[:-1]] == [r['state_sha256'] for r in rows],
         'P10_ACTUAL_REPRODUCED_OLD_TAIL_STATE_WITNESSES_NOT_ADOPTED')
    fast_binding, fast_observer = bindings['fast'], observers['fast']
    negatives = out / 'negative-proofs'
    negatives.mkdir()
    falsifiers = parser_falsifiers(fast_binding, fast_observer, negatives)
    falsifiers.append(actual_v_guard_falsifier(fast_observer, source_root, fast_binding))
    write_json(out / 'supported-cash-component.json', synthetic_supported_cash(fast_binding))
    summary = dict(schema='research.p10-ahl2-changed-qualification/1', status=STATUS,
        authority=TAINT, financial_authority=False, qualifier_state_adopted=False,
        original_diagnostic_file_sha256=spec['diagnostic_checkpoint_sha256'],
        predecessor_input_sha256=spec['input_sha256'], successor_input_sha256=fast_binding.run.input_sha256,
        candidate_transitions=10, qualified_through=AFFECTED, first_session=NEXT,
        full_FAST_REFERENCE_publication_runtime_event_proof_equal=True,
        actual_old_refusal_reproduced=True, all21_guard_preserved=True,
        actual_first_affected_state=fast[-1]['checkpoint']['state_sha256'],
        changed_full_path_sha256=digest(fast), falsifiers=falsifiers,
        actual_new_canonical_roundtrips=roundtrips,
        source_contract=fast_binding.source_contract, actual_held_roles_and_quantities_from_hosted_path=True,
        old_crypto_native_qualification_or_accounting_reexecuted=False)
    qualification_valid(summary, spec)
    write_json(out / 'qualification-summary.json', summary)
    return summary
