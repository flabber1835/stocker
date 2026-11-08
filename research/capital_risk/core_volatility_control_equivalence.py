"""Hosted diagnostic forks of this experiment's own control, never CAGR roots."""
import ast
from copy import deepcopy
from dataclasses import asdict
import gzip
import importlib
import json
import os
from pathlib import Path
import re
import shutil

from core_volatility_source import need, sha, identity
from full_system_core import hosted, arguments
from full_system_benchmark import save

SOURCES = {
    'AAAP': ('core_volatility_aaap', 'dbadcfed382f9f319f47be15a92f5102dae413b079a4d821bbbf6937ef977807', 'own_position', '554122275008038119'),
    'SODA': ('core_volatility_completion_facts', '4a05bfe66f4efba9f68150105681658660fea541bf4aaf57b468b0440b234dfc', 'own_scope', '580777104042893954'),
    'SONC': ('core_volatility_sonc_facts', '2612441898fc8e0ae798a801d435bcc4aa12a9340388cb3868ea438a1223a2c6', 'own_scope', '789689535963205828'),
    'BEL': ('core_volatility_cash_facts', '9d683313945fda7f523933a52c8b4cef55b1c9c4e1e8a6556132ac3f10325c43', 'own_scope', '882904858327189489'),
}
WINDOWS = {
    'AAAP': ('2018-01-31', 21, 8, '2018-02-12', ('AAAP',), 'book', 'aaap-model-book'),
    'DECEMBER': ('2018-11-30', 232, 5, '2018-12-10', ('SODA', 'SONC'), 'december-book', 'december-model-book'),
    'BEL': ('2019-03-29', 312, 14, '2019-04-18', ('BEL',), 'bel-book', 'bel-model-book'),
}
MAXIMUM = sum(2*value[2] for value in WINDOWS.values())


def control_scope(cp, arm, expected_outer, window, model):
    day, count, *_ = WINDOWS[window]
    need(arm == 'CONTROL' and cp['sha256'] == expected_outer and cp['completed'] == count
         and cp['source_cursor'] == day, 'EXACT_OWN_CONTROL_HISTORICAL_PARENT')
    sid = SOURCES[model][3]
    state = cp['run']['state']
    positions = [e for e in state['wealth_core']['episodes'].values() if e['security_id'] == sid]
    pending = [p for p in state['pending'] if p.get('security_id') == sid]
    if model == 'AAAP':
        need(not positions and not pending, 'CONTROL_AAAP_UNOWNED_AND_UNORDERED')
    return deepcopy(positions)


def compiler(model, expected_outer, window):
    """DATA compilation only: original function bodies, explicit own-control role."""
    name, commitment, guard, _ = SOURCES[model]
    original = importlib.import_module(name)
    raw = Path(original.__file__).read_bytes()
    need(sha(raw) == commitment, 'UNCHANGED_ORIGINAL_INPUT_AND_OBSERVER_SOURCE:'+model)
    tree = ast.parse(raw)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('prepare', 'observer')]
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    need(len(nodes) == 2 and {n.name for n in nodes} == {'prepare', 'observer'}, 'EXACT_REUSED_FUNCTION_BODIES')
    namespace = dict(vars(original), __file__=__file__)
    def scope(cp, arm, name=None):
        need(name in (None, model), 'EXACT_CONTROL_CLOSED_CASE_ROLE')
        return control_scope(cp, arm, expected_outer, window, model)
    namespace[guard] = scope
    exec(compile(ast.Module(body=imports+nodes, type_ignores=[]), '<unchanged-input-body-own-control-role>', 'exec'), namespace)
    return namespace['prepare'], namespace['observer']


def historical_spec(root, expected, window):
    from research.pooled_vacancy_funding.journal import read_checkpoint
    from research.pooled_vacancy_funding import backtest, runtime
    path = root/expected['path']
    need(path.resolve().is_relative_to((root/'book').resolve())
         and sha(path.read_bytes()) == expected['file_sha256'], 'AUTHENTICATED_OWN_HISTORICAL_CHECKPOINT_FILE')
    cp = read_checkpoint(path)
    need(cp['sha256'] == expected['outer_sha256'] and cp['base']['sources'] == backtest.source_files(),
         'OWN_HISTORICAL_SOURCE_AND_OUTER_IDENTITY')
    for model in WINDOWS[window][4]:
        control_scope(cp, 'CONTROL', expected['outer_sha256'], window, model)
    run = runtime.restore(cp['run'], policy=cp['base']['policy'],
                          input_sha256=backtest.input_hash(cp['base'], cp['repairs']))
    need(runtime.checkpoint(run) == cp['run'], 'STRICT_CONTROL_HISTORICAL_ROUNDTRIP')
    return path, cp


def fork(previous, destination, selected_path, cp):
    """Copy a selected prefix; preserve the whole original artifact read-only."""
    need(not destination.exists(), 'NEW_DIAGNOSTIC_FORK')
    destination.mkdir()
    shutil.copyfile(selected_path, destination/'checkpoint.json.gz')
    shutil.copyfile(previous/'book/identity.json', destination/'identity.json')
    repairs = destination/'repairs'
    repairs.mkdir()
    os.chmod(repairs, 0o700)
    for descriptor in cp['repairs']:
        source = previous/'book/repairs'/descriptor['filename']
        need(sha(source.read_bytes()) == descriptor['sha256'], 'UNCHANGED_SELECTED_REPAIR_BYTES')
        target = repairs/descriptor['filename']
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
    for stream, commitment in cp['journals'].items():
        with (previous/'book'/(stream+'.jsonl')).open('rb') as f:
            raw = f.read(commitment['bytes'])
        need(len(raw) == commitment['bytes'] and sha(raw) == commitment['prefix_sha256'], 'EXACT_DIAGNOSTIC_COMMITTED_PREFIX')
        (destination/(stream+'.jsonl')).write_bytes(raw)
    for group in ('month-end', 'pre-event', 'predecessor-checkpoints'):
        target = destination/group
        target.mkdir()
        for path in sorted((previous/'book'/group).glob('*.json.gz')):
            if re.match(r'^\d{4}-\d{2}-\d{2}-', path.name) and path.name[:10] > cp['source_cursor']:
                continue
            value = json.loads(gzip.decompress(path.read_bytes()))
            if value['source_cursor'] <= cp['source_cursor']:
                shutil.copyfile(path, target/path.name)


def first_difference(a, b, path='$'):
    """Exact typed DATA comparison; no identity/state fields are hidden."""
    if type(a) is not type(b):
        return path+':type'
    if isinstance(a, dict):
        if set(a) != set(b):
            return path+':keys'
        return next((d for k in sorted(a) if (d := first_difference(a[k], b[k], path+'.'+k))), None)
    if isinstance(a, list):
        if len(a) != len(b):
            return path+':length'
        return next((d for i, (x, y) in enumerate(zip(a, b)) if (d := first_difference(x, y, path+'['+str(i)+']'))), None)
    return None if a == b else path


def financial_difference(a, b):
    a, b = deepcopy(a), deepcopy(b)
    for row in (a, b):
        for key in ('input_sha256', 'chain_sha256'):
            row.pop(key)
    return first_difference(a, b)


def differential(left, right, window):
    from research.pooled_vacancy_funding.journal import read_checkpoint
    a, b = read_checkpoint(left/'checkpoint.json.gz'), read_checkpoint(right/'checkpoint.json.gz')
    day, initial, steps, end, *_ = WINDOWS[window]
    differences, counts = [], {}
    for stream in ('formation', 'daily'):
        rows = []
        for root, cp in ((left, a), (right, b)):
            commitment = cp['journals'][stream]
            with (root/(stream+'.jsonl')).open('rb') as f:
                raw = f.read(commitment['bytes'])
            need(len(raw) == commitment['bytes'] and sha(raw) == commitment['prefix_sha256'], 'DIAGNOSTIC_COMMITTED_PREFIX')
            rows.append([json.loads(line) for line in raw.splitlines()])
        counts[stream] = [len(v) for v in rows]
        if len(rows[0]) != len(rows[1]):
            differences.append(dict(stream=stream, path='$:length'))
        for index, (old, modeled) in enumerate(zip(*rows)):
            difference = financial_difference(old, modeled)
            if difference:
                differences.append(dict(stream=stream, index=index, session=old.get('session'), path=difference))
    endpoints = a['completed'] == b['completed'] == initial+steps and a['source_cursor'] == b['source_cursor'] == end
    for name, x, y in (('complete_strategy_state', a['run']['state'], b['run']['state']),
                       ('state_sha256', a['run']['state_sha256'], b['run']['state_sha256']),
                       ('account_economics', a['economics'], b['economics']), ('monthly_stats', a['stats'], b['stats'])):
        if difference := first_difference(x, y):
            differences.append(dict(stream=name, path=difference))
    exact = endpoints and not differences and counts == {'formation': [126, 126], 'daily': [initial+steps, initial+steps]}
    return {'window': window, 'exact_noop': exact, 'counts': counts, 'endpoints_reproduced': endpoints,
            'differences': differences, 'reference_checkpoint_sha256': a['sha256'], 'model_checkpoint_sha256': b['sha256'],
            'reference_state_sha256': a['run']['state_sha256'], 'model_state_sha256': b['run']['state_sha256'],
            'ignored_top_level_fields': ['input_sha256', 'chain_sha256'],
            'financial_continuation_authorized': False, 'performance_admitted': False}


def future_packets(book, cp, overlay, window):
    from research.pooled_input_support import inputs
    from research.pooled_input_support.adapter import Packet
    from research.pooled_input_support.bundle import axis
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.repair import load_repair
    document = json.loads(overlay.read_bytes())
    allowed = {
        'AAAP': {('2018-02-01', SOURCES['AAAP'][3]), ('2018-02-09', SOURCES['AAAP'][3])},
        'DECEMBER': {('2018-12-04', SOURCES['SODA'][3]), ('2018-12-06', SOURCES['SODA'][3]), ('2018-12-07', SOURCES['SONC'][3])},
        'BEL': {('2019-04-16', SOURCES['BEL'][3]), ('2019-04-17', SOURCES['BEL'][3])},
    }[window]
    dates = {(t['session'], t['security_id']) for group in ('add', 'suppress') for t in document[group]}
    need(dates == allowed, 'ONLY_EXACT_DECLARED_INPUT_DATES')
    load = lambda p, cursor, predecessor: load_repair(p, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
    added = load(overlay, cp['source_cursor'], cp['run']['checkpoint_sha256'])
    retained = [load(book/'repairs'/v['filename'], v['resume_session'], v['predecessor_checkpoint_sha256']) for v in cp['repairs']]
    actions = inputs.load_actions(Path('/frozen/bundle'))
    count = 0
    for day in axis():
        if day <= WINDOWS[window][3]:
            continue
        packet = Packet(day, (), {}, {}, 1., {}, tuple(actions.terminal.get(day, ())), ())
        for repair in retained:
            packet = backtest.apply_repair(packet, repair)
        before = asdict(packet)
        need(asdict(backtest.apply_repair(packet, added)) == before and asdict(packet) == before, 'EVERY_LATER_PACKET_EXACTLY_UNCHANGED')
        count += 1
    return dict(later_packets_verified=count, last_affected_session=max(d for d, _ in dates), all_later_packets_equal=True)


def prepare_models(cp, root, window):
    observers, documents, terms = [], [], []
    for model in WINDOWS[window][4]:
        target = root/model
        target.mkdir()
        prepare, observe = compiler(model, cp['sha256'], window)
        extra, material = prepare(cp, target, 'CONTROL', model) if model == 'BEL' else prepare(cp, target, 'CONTROL')
        need(len(extra) == 2 and extra[0] == '--repair-overlay', 'EXPLICIT_TYPED_DIAGNOSTIC_INPUT')
        documents.append(json.loads(Path(extra[1]).read_bytes()))
        terms.extend(material['terms'])
        observers.append(observe(target, cp, material))
    document = dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=[v for d in documents for v in d['source_evidence']],
        suppress=[v for d in documents for v in d['suppress']], add=[v for d in documents for v in d['add']])
    overlay = root/'combined-overlay.json'
    save(overlay, document)
    import system_campaign_financial_future as original
    from research.pooled_vacancy_funding.repair import load_repair
    from research.pooled_input_support import inputs
    loaded = load_repair(overlay, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    audit = root/'combined-qualification'
    audit.mkdir()
    original.qualify(cp, {'terms': terms}, {}, inputs.load_actions(Path('/frozen/bundle')), loaded, overlay, audit)
    merged = {}
    for observed in observers:
        need(observed.arm == 'CONTROL' and not observed.scopes and not observed.saved and observed.current is None
             and type(observed).advance is original.ActualEvents.advance
             and type(observed).terminal is original.ActualEvents.terminal, 'UNCHANGED_CANONICAL_POSTCONDITION_DELEGATES')
        need(not set(merged).intersection(observed.terms), 'DISJOINT_DECLARED_OBSERVER_TERMS')
        merged.update(observed.terms)
    observed = observers[0]
    observed.terms, observed.out = merged, root
    need(set(merged) == {(t['session'], t['security_id']) for t in document['add']}, 'EXACT_COMBINED_OBSERVER_SCOPE')
    return overlay, observed


def run(previous, arm, maximum):
    hosted()
    need(previous == Path('/previous') and arm == 'CONTROL' and maximum == MAXIMUM, 'BOUNDED_CONTROL_DIAGNOSTIC_ONLY')
    from research.pooled_vacancy_funding import backtest
    from system_campaign_acceleration import Execution
    from system_campaign_readonly import review as canonical_review
    from system_campaign_space import DEFAULT
    from core_volatility_worker import qualify
    request = json.loads(Path('/out/request.json').read_bytes())
    binding = json.loads(Path('/out/source-bindings.json').read_bytes())
    need(binding == json.loads((previous/'source-bindings.json').read_bytes())
         and binding['experiment'] == identity('CONTROL') and binding['parameters'] == DEFAULT, 'EXACT_OWN_CONTROL_SOURCE_BINDING')
    save(Path('/out/canonical-qualification.json'), qualify('CONTROL'))
    canonical_review(previous/'book', Path('/out/parent-preflight.json'))
    results = {}
    for window, (_, _, steps, _, _, reference, modeled) in WINDOWS.items():
        selected, cp = historical_spec(previous, request['historical_checkpoints'][window], window)
        material = Path('/out')/(window.lower()+'-material')
        material.mkdir()
        overlay, observed = prepare_models(cp, material, window)
        exits = []
        for added, folder in ((False, reference), (True, modeled)):
            book = Path('/out')/folder
            fork(previous, book, selected, cp)
            with Execution('FAST', signal_closes=1) as execution:
                if added:
                    with observed:
                        code = backtest.main(arguments(book, True, steps)+['--repair-overlay', str(overlay)])
                else:
                    code = backtest.main(arguments(book, True, steps))
            exits.append(code)
            save(material/(folder+'-acceleration.json'), execution.proof())
        result = differential(Path('/out')/reference, Path('/out')/modeled, window)
        result.update(canonical_exit_codes=exits, future_input=future_packets(previous/'book', cp, overlay, window))
        result['exact_noop'] = result['exact_noop'] and exits == [0, 0]
        results[window] = result
    outcome = dict(schema='research.core-volatility-control-input-equivalence/1', diagnostic_only=True,
        exact_noop=all(v['exact_noop'] for v in results.values()), windows=results,
        financial_continuation_authorized=False, performance_admitted=False, financial_sessions_added_to_experiment=0)
    save(Path('/out/control-model-differential.json'), outcome)
    save(Path('/out/experiment-outcome.json'), outcome)


def review(previous, evidence, output):
    hosted()
    from system_campaign_readonly import review as canonical_review
    saved = json.loads((evidence/'control-model-differential.json').read_bytes())
    results = {}
    request = json.loads((evidence/'request.json').read_bytes())
    for window, (_, _, _, _, _, reference, modeled) in WINDOWS.items():
        _, cp = historical_spec(previous, request['historical_checkpoints'][window], window)
        for folder in (reference, modeled):
            canonical_review(evidence/folder, output/(folder+'-review.json'))
        result = differential(evidence/reference, evidence/modeled, window)
        exits = saved['windows'][window]['canonical_exit_codes']
        result.update(canonical_exit_codes=exits, future_input=future_packets(previous/'book', cp,
            evidence/(window.lower()+'-material/combined-overlay.json'), window))
        result['exact_noop'] = result['exact_noop'] and exits == [0, 0]
        results[window] = result
    need(results == saved['windows'] and saved['exact_noop'] == all(v['exact_noop'] for v in results.values()),
         'INDEPENDENT_CONTROL_DIFFERENTIAL_REPRODUCTION')
    save(output/'core-review.json', dict(saved, complete=False, all_prefixes_verified=True,
         all_daily_factors_and_chains_verified=True, counts={'diagnostic_transitions_requested': MAXIMUM}))


def extract_diagnostic(archive, root, key, spec):
    """Authenticate diagnostics without creating a financial continuation root."""
    from core_volatility_admit import authenticated_payload, digest
    from core_volatility_job import inspect
    from seal import sha256_file
    need(spec['status'] == 'CONTROL_INPUT_EQUIVALENCE_REVIEWED_PENDING_TRANSPORT_ADMISSION'
         and spec['arm'] == 'CONTROL' and spec['maximum'] == MAXIMUM and spec['continuation']
         and spec['control_equivalence'] and spec['worker_exit_code'] == 0, 'EXACT_DIAGNOSTIC_TRANSPORT_ROLE')
    root = Path(root)
    manifest, receipt = authenticated_payload(archive, root, key, spec)
    need(receipt['stage'] == 'OWN_CONTROL_INPUT_EQUIVALENCE' and receipt['generation'] == 7
         and receipt['worker']['stopped'] and receipt['worker']['exit_code'] == 0 and not receipt['worker']['oom_killed']
         and receipt['reviewer']['stopped'] and receipt['reviewer']['exit_code'] == 0 and not receipt['reviewer']['oom_killed'],
         'DIAGNOSTIC_POSITIVE_STOPS')
    for relative, role in (('worker-inspect.json', 'worker'), ('independent-review-stop/worker-inspect.json', 'review')):
        value = json.loads((root/relative).read_bytes())
        name = 'core-volatility-control-'+role+'-'+str(spec['run_id'])+'-1'
        inspect(name, value=value, user=spec['container_user'], maximum=MAXIMUM, continuation=True, control_equivalence=True)
        need(not value['State']['Running'] and not value['State']['OOMKilled'] and value['State']['ExitCode'] == 0,
             'ACTUAL_DIAGNOSTIC_STOP')
    proof = json.loads((root/'independent-review-stop/core-review.json').read_bytes())
    outcome = json.loads((root/'control-model-differential.json').read_bytes())
    need(proof['diagnostic_only'] and not proof['performance_admitted'] and not proof['financial_continuation_authorized']
         and proof['all_prefixes_verified'] and proof['all_daily_factors_and_chains_verified']
         and proof['windows'] == outcome['windows'] and proof['exact_noop'] == outcome['exact_noop']
         and set(proof['windows']) == set(WINDOWS), 'DIAGNOSTIC_INDEPENDENT_RESULT')
    for window, (_, _, _, _, _, reference, modeled) in WINDOWS.items():
        for folder, field in ((reference, 'reference_checkpoint_sha256'), (modeled, 'model_checkpoint_sha256')):
            cp = json.loads(gzip.decompress((root/folder/'checkpoint.json.gz').read_bytes()))
            run = cp['run']
            need(cp['sha256'] == proof['windows'][window][field] == digest({k: v for k, v in cp.items() if k != 'sha256'})
                 and run['checkpoint_sha256'] == digest({k: v for k, v in run.items() if k != 'checkpoint_sha256'})
                 and run['state_sha256'] == digest(run['state'])
                 and run['input_sha256'] == digest({'base': cp['base'], 'repairs': cp['repairs']}),
                 'EXACT_DIAGNOSTIC_CHECKPOINT_AND_STATE')
            for stream, commitment in cp['journals'].items():
                with (root/folder/(stream+'.jsonl')).open('rb') as f:
                    raw = f.read(commitment['bytes'])
                need(len(raw) == commitment['bytes'] and sha(raw) == commitment['prefix_sha256'], 'EXACT_DIAGNOSTIC_PREFIX')
    need(sha256_file(root/'source-bindings.json') == spec['source_bindings_sha256'], 'EXACT_DIAGNOSTIC_FINANCIAL_SOURCE')
    return dict(schema='research.core-volatility-control-input-admission/1', diagnostic_only=True,
                exact_noop=proof['exact_noop'], windows=proof['windows'], performance_admitted=False,
                financial_continuation_authorized=False, members_verified=len(manifest['members']),
                manifest_sha256=spec['encrypted_output']['manifest_sha256'], whole_cipher_authenticated_before_parsing=True)
