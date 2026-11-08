def build_target(arm, plan, old_target, root):
    folder = R / plan['folder']
    capture = folder / plan['capture']
    out = ext(capture / 'verified-output')
    selection = checked(folder / plan['selection_file'], plan['selection_sha256'])
    manifest = checked(capture / 'authenticated-manifest.json', plan['manifest_sha256'])
    summary = checked(capture / 'capture-review.json', plan['capture_review_sha256'])
    receipt = checked(capture / 'public-receipt.json', plan['receipt_sha256'])
    spec = checked(out / 'spec.json', plan['spec_sha256'])
    verify_root(root, arm, plan, spec)
    archive = capture / 'artifact.zip'
    need(ext(archive).stat().st_size == plan['zip_bytes'] and file_sha(archive) == plan['zip_sha256'], 'EXACT_IMMUTABLE_FINANCIAL_ARCHIVE')
    need(selection == plan['selection'] and selection['run_id'] == plan['run_id'] and (selection['head'] == plan['head']) and (len(selection['arms']) == len(set(selection['arms'])) == len(selection['artifacts'])) and ({v['arm'] for v in selection['artifacts']} == set(selection['arms'])) and ([v for v in selection['artifacts'] if v['arm'] == arm] == [dict(arm=arm, id=plan['artifact_id'], bytes=plan['zip_bytes'], sha256=plan['zip_sha256'])]), 'EXACT_IMMUTABLE_FINANCIAL_SOURCE_CLOCK')
    need((manifest['arm'], int(manifest['run_id']), manifest['head'], manifest['stage']) == (arm, plan['run_id'], plan['head'], 'campaign-factual-suffix') and manifest['request_sha256'] == receipt['request_sha256'] == plan['request_sha256'] and (manifest['protocol_sha256'] == old_target['protocol_sha256']), 'EXACT_MANIFEST_SOURCE_CLOCK_AND_REQUEST')
    members = manifest['members']
    need(len(members) == plan['members'] and sum((v['bytes'] for v in members.values())) == plan['logical_bytes'], 'EXACT_AUTHENTICATED_MANIFEST_COUNTS')
    for name, expected in members.items():
        relative = PurePosixPath(name)
        need(not relative.is_absolute() and '..' not in relative.parts and (':' not in name) and ('\\' not in name), 'SAFE_AUTHENTICATED_MANIFEST_MEMBER')
        path = out.joinpath(*relative.parts)
        need(path.stat().st_size == expected['bytes'] and file_sha(path) == expected['sha256'], 'EXACT_AUTHENTICATED_MEMBER:' + name)
    checked(out / 'request.json', plan['request_sha256'])
    need(members['book/checkpoint.json.gz']['sha256'] == plan['checkpoint_file_sha256'], 'EXACT_SELECTED_CHECKPOINT_FILE')
    cp = json.loads(gzip.decompress((out / 'book/checkpoint.json.gz').read_bytes()))
    need((cp['completed'], cp['source_cursor'], cp['sha256'], cp['run']['checkpoint_sha256'], cp['run']['state_sha256'], cp['run']['input_sha256']) == (plan['completed'], plan['cursor'], plan['outer'], plan['inner'], plan['state'], plan['input_sha256']) and cp['base'] == spec['base'] and (cp['completed'] - spec['measured_closes'] == plan['new_days']) and (cp['repairs'] == spec['repairs']) and (cp['run']['input_sha256'] == spec['input_sha256']), 'EXACT_SAVED_OWN_CHECKPOINT_AND_UNCHANGED_SOURCE_EPOCH')
    need(file_sha(out / 'source-bindings.json') == plan['source_binding_sha256'] == spec['source_binding_sha256'], 'EXACT_OWN_SOURCE_BINDINGS')
    review = checked(out / 'stopped-review/core-review.json', plan['review_sha256'])
    need(review['checkpoint_sha256'] == cp['sha256'] and review['counts'] == dict(formation=126, daily=plan['completed']) and (review['all_prefixes_verified'] is review['all_daily_factors_and_chains_verified'] is True) and (review['complete'] is False) and (review['production_contacted'] is False), 'EXACT_SAVED_HOSTED_PARTIAL_REVIEW_NO_COMPLETION_AUTHORITY')
    need(summary['artifact_id'] == plan['artifact_id'] and summary['outer_sha256'] == plan['outer'] and (summary['financial_checkpoint_sessions'] == plan['completed']) and (summary['new_committed_sessions'] == plan['new_days']) and (summary['through'] == plan['cursor']) and (summary['financial_authority'] is summary['independently_root_admitted'] is False) and (summary['canonical_runtime_executed_locally'] is False) and (summary['review_error'] is None), 'EXACT_INDEPENDENTLY_CAPTURED_NOT_YET_ADMITTED_PREFIX')
    need(receipt['arm'] == arm and int(receipt['run_id']) == plan['run_id'] and (receipt['head'] == plan['head']) and (receipt['status'] == summary['status'] == 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT') and (receipt['performance_admitted'] is receipt['production_contacted'] is False), 'EXACT_ORIGINAL_PARTIAL_PUBLIC_RECEIPT')
    public = {}
    with zipfile.ZipFile(ext(archive)) as zipped:
        names = zipped.namelist()
        asset = receipt['encrypted_output']
        need(len(names) == len(set(names)) == 5 and set(names) == {'campaign-factual-' + arm + '.json', 'full-core-staging.json', 'ephemeral-runner-capacity.json', 'resume-export-qualification-' + arm + '.json', asset['name']} and (zipped.getinfo(asset['name']).file_size == asset['bytes']), 'EXACT_FIVE_PUBLIC_ENCRYPTED_ARCHIVE_MEMBERS')
        for name in names:
            if name == asset['name']:
                continue
            data = zipped.read(name)
            public[name] = dict(bytes=len(data), sha256=sha(data))
        need(sha(zipped.read('campaign-factual-' + arm + '.json')) == plan['receipt_sha256'], 'EXACT_PUBLIC_RECEIPT_MEMBER')
    target = deepcopy(old_target)
    for name in ('base', 'journals', 'repairs'):
        target[name] = deepcopy(cp[name])
    target.update(archive_format='FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1', arm=arm, artifact_id=plan['artifact_id'], run_id=plan['run_id'], head=plan['head'], measured_closes=plan['completed'], selected_session=plan['cursor'], monthly_seed_root_admission_sha256=plan['seed_root'], outer_sha256=plan['outer'], inner_sha256=plan['inner'], state_sha256=plan['state'], input_sha256=plan['input_sha256'], source_binding_sha256=plan['source_binding_sha256'], encrypted_output=deepcopy(receipt['encrypted_output']), receipt_sha256=plan['receipt_sha256'], receipt_status=receipt['status'], request_sha256=plan['request_sha256'], original_request_member=deepcopy(members['request.json']), review_sha256=plan['review_sha256'], selected_checkpoint='book/checkpoint.json.gz', selected_file=deepcopy(members['book/checkpoint.json.gz']), zip_bytes=plan['zip_bytes'], zip_sha256=plan['zip_sha256'], manifest=dict(member_count=plan['members'], raw_member_bytes=plan['logical_bytes']), prior_stops={name: deepcopy(receipt[name]) for name in ('preflight', 'worker', 'reviewer')}, public_members=public, financial_authority=False, financial_predecessor_admitted=False, reuse_closed_hosted_prefix_review=True)
    for name in ('readonly_full_financial_target', 'initial_prefix_reporting', 'initial_monthly_seed'):
        target.pop(name, None)
    target['inspections'] = {}
    for name, phase, role, exit_code in (('parent-preflight/worker-inspect.json', 'preflight', 'preflight', 0), ('worker-inspect.json', 'worker', 'worker', 1), ('stopped-review/worker-inspect.json', 'review', 'reviewer', 0)):
        data = (out / name).read_bytes()
        value = json.loads(data)
        state = value['State']
        need(value['Name'] == f"/capital-system-resume-{arm.lower()}-{phase}-{plan['run_id']}-1" and state['Running'] is state['OOMKilled'] is False and (state['ExitCode'] == exit_code) and (receipt[role]['stopped'] is True) and (receipt[role]['oom_killed'] is False) and (receipt[role]['exit_code'] == exit_code) and (value['Config']['User'] == '1001:1001') and (not any((m['Destination'] == '/correlation-prefix' for m in value['Mounts']))), 'EXACT_ARCHIVED_STOPPED_OWNER_AND_PHASE')
        target['inspections'][name] = dict(id=value['Id'], name=value['Name'], exit_code=exit_code, user=value['Config']['User'], sha256=sha(data), correlation_prefix_mounted=False)
    tails = {name: (out / 'book' / (name + '.jsonl')).stat().st_size - entry['bytes'] for name, entry in cp['journals'].items()}
    need(all((v >= 0 for v in tails.values())) and all((review['preserved_tails'][name]['bytes'] == value for name, value in tails.items())), 'EXACT_UNCOMMITTED_TAILS_EXCLUDED_FROM_SELECTED_CHECKPOINT')
    return (target, dict(arm=arm, source_clock=dict(run_id=plan['run_id'], head=plan['head'], artifact_id=plan['artifact_id']), selected_checkpoint_sha256=plan['outer'], completed=plan['completed'], source_cursor=plan['cursor'], new_financial_rows=plan['new_days'], monthly_seed_root_admission_sha256=plan['seed_root'], manifest_members=plan['members'], uncommitted_tail_bytes=tails, transport_sha256=sha(raw(target)), financial_authority=False, root_admission_changed=False))
