"""Hosted-only explicit neutral ordinary-input augmentation of the retained book."""
import ast
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

import system_campaign_ordinary_augmentation_data as data


def hosted():
    from full_system_core import hosted as check
    check()


def write_exact(path, raw):
    path = Path(path)
    if path.exists():data.need(path.read_bytes() == raw, 'AUGMENTATION_EXACT_EXISTING_RESOURCE')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)


def stage(root, target, cp, plan, phase):
    """Copy authenticated source documents only; no checkpoint construction."""
    root, target = Path(root), Path(target)
    origin = json.loads((root/data.original.ORIGIN).read_bytes())
    from system_campaign_financial_additional_sensor_review import stage_inputs
    import system_campaign_financial_additional_sensor_runtime as original
    checkpoint=root/original.ORIGIN_DIR/'cp0.json.gz'
    data.need(data.sha(checkpoint.read_bytes()) == origin['cp0_gzip_sha256'],
              'AUGMENTATION_AUTHENTICATED_ORIGINAL_CP0_GZIP')
    cp0 = original.read_cp(checkpoint)
    stage_inputs(root,target,cp0,phase)
    from system_campaign_zogenix_facts import PRIVATE
    names = {PRIVATE:origin['input_files'][PRIVATE]}
    names[data.original.ORIGIN] = data.sha((root/data.original.ORIGIN).read_bytes())
    for d in cp['repairs']:names['book/repairs/'+d['filename']] = d['sha256']
    for name, pin in names.items():
        raw = (root/data.safe(name)).read_bytes()
        data.need(data.sha(raw) == pin, 'AUGMENTATION_EXACT_STAGED_INPUT_BYTES')
        write_exact(target/name, raw)
    return names


def future_api(plan, validate, phase):
    import system_campaign_financial_future as f
    from system_campaign_qualified_own_cash_literals import QualifiedOriginalCashLiterals
    raw = Path(f.__file__).read_bytes()
    data.need(data.sha(raw) == plan['source_files'][Path(f.__file__).name],
              'AUGMENTATION_EXACT_ORDINARY_COMPILER_GENERATION')
    namespace = dict(vars(f))
    tree = ast.Module(body=[n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), '<unchanged-ordinary-augmentation-compiler>', 'exec'), namespace)
    first, second = plan['literal_sources']
    def selected(arm, *, cursor=None):
        data.need((arm, cursor) == (plan['arm'], plan['parent_cursor']), 'AUGMENTATION_EXACT_LITERAL_PHASE')
        codec = QualifiedOriginalCashLiterals(data.HERE/first['catalog_file'])
        return codec, first['catalog_file'], f.catalog_terms(codec, tuple(first['selected_tickers']))
    namespace['selected'] = selected
    key = plan['arm'], plan['parent_cursor']
    namespace['SUPPLEMENTAL_PHASES'] = {key:((second['module'],second['class_name'],'PATH',
        second['catalog_file'],second['catalog_sha256'],second['validator_sha256'],
        tuple(second['selected_tickers'])),)}
    def typed_input_valid(root, cp, entry):
        modeled = validate(root, cp, phase,
            origin=json.loads((Path(root)/data.original.ORIGIN).read_bytes()), input_hash=canonical_hash())
        return entry in [phase['original_branch_descriptor'], *modeled]
    namespace['typed_input_valid'] = typed_input_valid
    fn = data.remaining_tree(raw)
    exec(compile(ast.Module(body=[fn],type_ignores=[]), '<full-typed-visitor-in-ordinary-input-composition>', 'exec'), namespace)
    return namespace


def canonical_hash():
    hosted()
    from research.pooled_vacancy_funding import backtest
    return backtest.input_hash


def prepare(cp, root, out, plan, phase, validate):
    hosted();data.parent_scope(cp, plan)
    target = out/data.DIRECTORY
    data.need(not target.exists(), 'AUGMENTATION_FRESH_PREPARATION_NAMESPACE')
    target.mkdir()
    stage(root,target,cp,plan,phase)
    api = future_api(plan, validate, phase)
    path, loaded = api['prepare'](cp,target,plan['arm'])
    material = json.loads((target/api['hydration_name'](cp)).read_bytes())
    data.need([t['ticker'] for t in material['terms']] == plan['expected_tickers']
         and all(t['added']['kind'] == 'CASH_MERGER' for t in material['terms'])
         and loaded.earliest_affected_session > cp['source_cursor'], 'AUGMENTATION_EXACT_NEW_CASH_INPUTS')
    write_exact(out/data.OVERLAY,path.read_bytes())
    return loaded, api


def pause(cp, out, args, rows, path, earliest):
    import system_campaign_financial_uncertainty as u
    fn = data.pause_tree(u.__file__)
    namespace = dict(vars(u))
    exec(compile(ast.Module(body=[fn],type_ignores=[]), '<original-neutral-adoption-distinct-ordinary-filename>', 'exec'), namespace)
    return namespace['paused_own_adoption'](cp,out,args,rows,path,earliest,data.ADOPTION)


def receipt(root, cp, plan):
    return data.validated_receipt(root, cp, plan, input_hash=canonical_hash())


def adopt(cp, out, args, rows, spec, old, phase, plan, validate):
    hosted()
    if data.suffix(cp,plan):
        receipt(out,cp,plan)
        return cp
    loaded, api = prepare(cp, old, out, plan, phase, validate)
    source = (old/spec['selected_checkpoint']).read_bytes()
    data.need(data.sha(source) == plan['parent_checkpoint_gzip_sha256']
         and len(source) == plan['parent_checkpoint_gzip_bytes'], 'AUGMENTATION_EXACT_AUTHENTIC_PARENT_GZIP')
    write_exact(out/data.DIRECTORY/'parent-checkpoint.json.gz',source)
    successor = pause(cp,out,args,rows,out/data.OVERLAY,loaded.earliest_affected_session)
    data.need(successor['repairs'][:22] == cp['repairs'] and len(successor['repairs']) == 23
         and successor['base'] == cp['base'], 'AUGMENTATION_ONE_EXPLICIT_NEUTRAL_ORDINARY_SUFFIX')
    data.need(api['review_input'](cp,out/data.DIRECTORY,plan['arm']) == loaded.earliest_affected_session,
              'AUGMENTATION_INDEPENDENT_INPUT_RECONSTRUCTION_BEFORE_FINANCE')
    files = {p.relative_to(out).as_posix():data.sha(p.read_bytes())
             for p in (out/data.DIRECTORY).rglob('*') if p.is_file()}
    files[data.OVERLAY] = data.sha((out/data.OVERLAY).read_bytes())
    for name in (data.ADOPTION+'/checkpoint.json.gz',data.ADOPTION+'/proof.json',
                 data.ADOPTION+'-correlation-inputs.jsonl.gz'):
        files[name] = data.sha((out/name).read_bytes())
    value = dict(schema=data.SCHEMA,passed=True,catalog_sha256=data.sha((data.HERE/data.CATALOG).read_bytes()),
        parent_root_admission_sha256=plan['parent_root_admission_sha256'],parent_outer_sha256=cp['sha256'],
        parent_inner_sha256=cp['run']['checkpoint_sha256'],parent_descriptors=deepcopy(cp['repairs']),
        adopted_descriptors=deepcopy(successor['repairs']),new_descriptor=deepcopy(successor['repairs'][-1]),
        adopted_outer_sha256=successor['sha256'],adopted_input_sha256=successor['run']['input_sha256'],
        earliest_affected_session=loaded.earliest_affected_session,
        observation_seed_sha256=data.sha(b''.join(rows)),observation_seed_bytes=len(b''.join(rows)),
        input_files=files,financial_state_unchanged=True,financial_sessions_advanced=0,
        canonical_financial_source_changed=False)
    write_exact(out/data.RECEIPT,data.encoded(value))
    validate(out,successor,phase,origin=json.loads((out/data.original.ORIGIN).read_bytes()),input_hash=canonical_hash())
    return successor


def verify_neutral(evidence,current,plan):
    hosted()
    from research.pooled_vacancy_funding import journal
    import system_campaign_financial_uncertainty as u
    value = receipt(evidence,current,plan)
    data.need(value is not None, 'AUGMENTATION_REVIEW_REQUIRES_EXPLICIT_RECEIPT')
    source = evidence/data.DIRECTORY/'parent-checkpoint.json.gz'
    raw = source.read_bytes()
    data.need(data.sha(raw) == plan['parent_checkpoint_gzip_sha256']
         and len(raw) == plan['parent_checkpoint_gzip_bytes'], 'AUGMENTATION_REVIEW_ORIGINAL_PARENT_BYTES')
    original_parent = journal.read_checkpoint(source)
    data.parent_scope(original_parent,plan)
    successor = u.boundary(evidence,data.ADOPTION,original_parent,data.OVERLAY,value['earliest_affected_session'])
    seed = gzip.decompress((evidence/(data.ADOPTION+'-correlation-inputs.jsonl.gz')).read_bytes())
    data.need(successor['sha256'] == value['adopted_outer_sha256']
         and successor['repairs'] == current['repairs']
         and successor['run']['input_sha256'] == current['run']['input_sha256']
         and len(seed) == value['observation_seed_bytes']
         and data.sha(seed) == value['observation_seed_sha256'], 'AUGMENTATION_REVIEW_EXACT_NEUTRAL_BOUNDARY_AND_SEED')
    return value,original_parent,successor,seed


def review_ordinary(parent, current, evidence, out, spec, plan, phase, validate):
    value,original_parent,successor,seed = verify_neutral(evidence,current,plan)
    if data.suffix(parent,plan):
        data.need(parent['repairs'] == current['repairs']
             and (Path('/old')/data.RECEIPT).read_bytes() == (evidence/data.RECEIPT).read_bytes(),
             'AUGMENTATION_RESTART_NO_READOPTION_OR_INPUT_CHANGE')
    else:
        data.parent_scope(parent,plan)
        from system_campaign_financial_resume import seed_rows
        data.need(seed == b''.join(seed_rows(Path('/old'),parent,spec)),
                  'AUGMENTATION_REVIEW_NO_ADOPTION_OBSERVATIONS')
    scratch = out/'independent-ordinary-augmentation'
    scratch.mkdir()
    stage(evidence,scratch,original_parent,plan,phase)
    api = future_api(plan,validate,phase)
    path, loaded = api['prepare'](original_parent,scratch,plan['arm'])
    for name in (api['OVERLAY'],api['hydration_name'](original_parent),'future-input-qualification.json'):
        data.need((scratch/name).read_bytes() == (evidence/data.DIRECTORY/name).read_bytes(),
                  'AUGMENTATION_REVIEW_COMPLETE_INPUT_AND_PACKET_RECONSTRUCTION')
    data.need(path.read_bytes() == (evidence/data.OVERLAY).read_bytes()
         and loaded.sha256 == value['new_descriptor']['sha256'], 'AUGMENTATION_REVIEW_EXACT_NEW_DESCRIPTOR_BYTES')
    from system_campaign_uncertainty_review import committed_rows
    terms = json.loads((evidence/data.DIRECTORY/api['hydration_name'](original_parent)).read_bytes())['terms']
    observed = {}
    for path in (evidence/'ordinary-augmentation-observation').glob('actual-future-event-20*.json'):
        day=path.stem.removeprefix('actual-future-event-')
        if day <= current['source_cursor']:observed[day]=json.loads(path.read_bytes())
    checked = data.verify_cash_events(committed_rows(evidence/'book',current,'daily'),
        current['run']['state']['ledger']['events'],observed,terms,current['source_cursor'],plan)
    write_exact(out/'ordinary-augmentation-cash-review.json',data.encoded(dict(passed=True,events=checked,
        financial_sessions_reexecuted=0,actual_quantities_and_canonical_operation_order_verified=True)))
    return True


def preserve(root, cp, out, plan):
    if not data.suffix(cp,plan):return
    receipt(root,cp,plan)
    root,out = Path(root),Path(out)
    names = {data.RECEIPT,data.OVERLAY,data.ADOPTION+'-correlation-inputs.jsonl.gz'}
    for directory in (data.DIRECTORY,data.ADOPTION):
        names.update(p.relative_to(root).as_posix() for p in (root/directory).rglob('*') if p.is_file())
    for name in names:write_exact(out/data.safe(name),(root/name).read_bytes())
    for p in (root/'ordinary-augmentation-observation').glob('actual-future-event-*.json'):
        if p.stem.removeprefix('actual-future-event-') <= cp['source_cursor']:
            write_exact(out/p.relative_to(root),p.read_bytes())


def api(root, cp, spec):
    """Isolate all bindings; original runtime, model and certificate sources stay exact."""
    hosted()
    import system_campaign_financial_additional_sensor_runtime as original
    import system_campaign_financial_additional_sensor_review as scratch
    plan = data.catalog()
    phase = data.original.selected_declaration(root,cp,spec)
    data.need(phase is not None and phase['adoption_mode'] == 'RETAINED'
         and phase['arm'] == plan['arm'], 'AUGMENTATION_EXACT_RETAINED_MODEL_SCOPE')
    raw = Path(original.__file__).read_bytes()
    data.need(data.sha(raw) == plan['source_files'][Path(original.__file__).name],
              'AUGMENTATION_IMMUTABLE_ADDITIONAL_RUNTIME')
    validate = data.validator(plan)
    namespace = dict(vars(original),data=SimpleNamespace(**dict(vars(data.original),validate_models=validate)))
    def original_boundary_hash(second, actual):
        return second['run']['input_sha256'] == canonical_hash()(second['base'],second['repairs'])
    namespace['original_boundary_hash'] = original_boundary_hash
    namespace['adopt_ordinary'] = lambda *args:adopt(*args,plan,validate)
    namespace['review_ordinary'] = lambda *args:review_ordinary(*args,plan,phase,validate)
    def ordinary_event_paths(root,p):
        return event_paths(root,namespace['observer_bindings'](root,p))
    namespace['ordinary_event_paths'] = ordinary_event_paths
    exec(compile(data.runtime_tree(raw),'<source-qualified-retained-ordinary-augmentation>','exec'),namespace)
    reconstruction = scratch.reconstruction(phase)
    namespace['ordinary_reconstruction'] = FunctionType(reconstruction.__code__,
        dict(reconstruction.__globals__,validate_origin=namespace['validate_origin']),reconstruction.__name__)
    original_qualification = namespace['verify_qualification']
    def verify(root,cp,p):
        result = original_qualification(root,cp,p)
        if data.suffix(cp,plan):verify_neutral(Path(root),cp,plan)
        return result
    namespace['verify_qualification'] = verify
    retained_preserve = namespace['preserve']
    def keep(root, cp, out, spec):
        retained_preserve(root,cp,out,spec)
        preserve(root,cp,out,plan)
    namespace['preserve'] = keep
    # This private phase object is captured by the typed visitor, never installed globally.
    future = future_api(plan,validate,phase)
    @contextmanager
    def observers(root,out,p,cp0):
        with ExitStack() as stack:
            if (Path(root)/data.RECEIPT).exists():
                from system_campaign_zogenix_sensor import isolated_function
                import system_campaign_financial_future as f
                from research.pooled_vacancy_funding import journal
                original_parent = journal.read_checkpoint(Path(root)/data.DIRECTORY/'parent-checkpoint.json.gz')
                event = f.ActualEvents.__new__(f.ActualEvents)
                init = isolated_function(f.ActualEvents.__init__,source_scopes=future['source_scopes'])
                init(event,Path(root)/data.DIRECTORY,plan['arm'],cp=original_parent)
                data.need(event.scopes == [] and all(t['kind']=='CASH_MERGER' for t in event.terms.values()),
                          'AUGMENTATION_NEW_OBSERVER_CASH_ONLY')
                event.out = Path(out)/'ordinary-augmentation-observation';event.out.mkdir(exist_ok=True)
                stack.enter_context(event)
            bound = stack.enter_context(namespace['inherited_ordinary_observers'](root,out,p,cp0))
            yield bound
    namespace['ordinary_observers'] = observers
    return SimpleNamespace(**namespace)


def event_paths(root,bindings):
    root=Path(root)
    directories=[root]
    for binding in bindings:
        name=data.safe(binding['observation_directory'])
        data.need(name.startswith('additional-inherited-ordinary-observation/')
             and len(Path(name).parts)==2, 'AUGMENTATION_ONLY_VALIDATED_ORIGINAL_OBSERVER_DIRECTORIES')
        directories.append(root/name)
    return [p for directory in directories for p in directory.glob('actual-future-event-20*.json')]
