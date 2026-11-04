"""Authenticate stopped financial evidence and reproduce recorded reporting only."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
import gzip
import json
from pathlib import Path
import re
import zipfile
from contextlib import contextmanager, nullcontext

from full_system_benchmark import need, save
from full_system_core import hosted
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from stage import PROTOCOL, IMAGE
from system_campaign_facts import digest, sha
from system_campaign_discovery_context import require_strict_checkpoint
from system_campaign_parallel_discovery import check_parent
import system_campaign_factual_admit as crypto

HERE = Path(__file__).parent
ORIGINALS = 'system-campaign-parallel-discovery-parents.json'
CRYPTO_SHA = '63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
FORMAT = 'FINANCIAL_RESUME_FIVE_MEMBER_ZIP/1'
ROOTS = 'system-campaign-financial-admitted-parents.json'
ADMISSIONS = {
    'P04': '58036453b01d009fc05f3626e735bc16c0bd1787f2ca951aeeb936ac57a4da45',
    'P07': '46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d',
    'P10': '4560175cf063336c5e192a4ffed31c90914e354b30c1d8c806b8dbee47c0ade7',
}
PRIOR_ADMISSIONS = {
    'P04': '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492',
    'P07': '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa',
    'P10': 'c3e9784fdaee742284dc4f7d90aaecbcb541cb50f699dabbb17e8c250f68815c',
}
ADMISSION_CLOCKS = {
    'P04': {
        '58036453b01d009fc05f3626e735bc16c0bd1787f2ca951aeeb936ac57a4da45': (41789942448, '1a4773b535f6aa2e9ab6e49adcfb247f062d4e52'),
        '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        '7177334f71ec924d37810189a9c8f94e6f00073f5808a3aa1ec4647801a51986': (41776035604, 'e5bc98c38b4b1983de82ff30dc77711f7f9cc31c'),
        'c0e9c671daa7a620f8d0fede0ba548a6edf5d669da99a083a7df65aebd301156': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P07': {
        '46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d': (41787444086, 'b089f323d9537e34011325a2884d9ad44555db1c'),
        '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        'c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P10': {
        '4560175cf063336c5e192a4ffed31c90914e354b30c1d8c806b8dbee47c0ade7': (41779617448, 'db16788d7f7eecd65e87cc9283e5b0110beee48f'),
        'b98f7dcd4a9a9cff118c53c290cf68794e30b49c2b0e1ca06fd77b3c8bd5b1b9': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
        'c3e9784fdaee742284dc4f7d90aaecbcb541cb50f699dabbb17e8c250f68815c': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
    },
}



def authorized_spec(entry, arm):
    """Separate root continuation authority from immutable transport provenance."""
    a, t = entry['admission'], entry['transport']
    raw = (json.dumps(a, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    need(arm in ADMISSIONS and sha(raw) == entry['admission_sha256']
         and entry['admission_sha256'] in ADMISSION_CLOCKS[arm],
         'FINANCIAL_EXACT_ROOT_ADMISSION_BYTES')
    readonly_run, readonly_head = ADMISSION_CLOCKS[arm][entry['admission_sha256']]
    need(a['schema'] == 'research.root-financial-continuation-admission/1'
         and a['status'] == 'ADMITTED_EXACT_FINANCIAL_CONTINUATION_CHECKPOINT'
         and a['arm'] == t['arm'] == arm and a['financial_continuation_authorized'] is True
         and a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is False
         and a['all_new_cash_shares_receivables_and_raw_marks_verified'] is True
         and a['all_new_funded_factors_and_financial_chains_verified'] is True
         and a['all_new_monthly_and_retry_state_verified'] is True
         and a['financial_source_epoch_unchanged'] is a['input_adoptions_fully_state_neutral'] is True
         and a['production_contacted'] is a['local_canonical_runtime_executed'] is False
         and a['readonly_run_id'] == readonly_run and a['readonly_head'] == readonly_head
         and t['archive_format'] == FORMAT
         and t['financial_authority'] is t['financial_predecessor_admitted'] is False,
         'FINANCIAL_ONLY_SEPARATE_ROOT_CONTINUATION_AUTHORITY')
    for key in ('base', 'journals', 'repairs', 'selected_checkpoint', 'selected_file',
                'outer_sha256', 'inner_sha256', 'state_sha256', 'input_sha256', 'source_binding_sha256'):
        need(a[key] == t[key], 'FINANCIAL_EXACT_ADMITTED_OWN_' + key.upper())
    need(a['completed'] == t['measured_closes'] and a['source_cursor'] == t['selected_session']
         and a['financial_artifact_id'] == t['artifact_id'] and a['financial_run_id'] == t['run_id']
         and a['financial_head'] == t['head'] and a['financial_zip_sha256'] == t['zip_sha256']
         and a['financial_cipher_sha256'] == t['encrypted_output']['sha256'],
         'FINANCIAL_EXACT_CLOSED_TRANSPORT_AND_AXIS')
    return dict(deepcopy(t), root_admission=deepcopy(a), root_admission_sha256=entry['admission_sha256'])


def root_spec(arm, admission_sha256=None):
    bundle = json.loads((HERE / ROOTS).read_bytes())
    need(bundle['schema'] == 'research.root-admitted-financial-parents/1'
         and bundle['full_financial_validation_completed'] is False, 'FINANCIAL_ROOT_BUNDLE_SCOPE')
    need(arm in ADMISSIONS, 'FINANCIAL_EXACT_ADMITTED_ARM')
    selected = ADMISSIONS[arm] if admission_sha256 is None else admission_sha256
    need(selected in ADMISSION_CLOCKS[arm], 'FINANCIAL_EXACT_HISTORICAL_ROOT_SELECTION')
    entry = bundle['arms'][arm] if selected == ADMISSIONS[arm] else bundle['historical_roots'][selected]
    need(entry['admission_sha256'] == selected, 'FINANCIAL_EXACT_SELECTED_ROOT_HASH')
    return authorized_spec(entry, arm)


def validate_root_spec(spec):
    transport = {k: v for k, v in spec.items() if k not in ('root_admission', 'root_admission_sha256')}
    need(authorized_spec(dict(transport=transport, admission=spec['root_admission'],
         admission_sha256=spec['root_admission_sha256']), spec['arm']) == spec,
         'FINANCIAL_EXACT_ROOT_SPEC')


def reporting_seed(spec):
    """Select an independently admitted own seed, never arbitrary newer state."""
    if 'monthly_seed_root_admission_sha256' in spec:
        original = root_spec(spec['arm'], spec['monthly_seed_root_admission_sha256'])
        need(spec['monthly_seed_root_admission_sha256'] == original['root_admission_sha256'],
             'PARTIAL_EXACT_MONTHLY_ROOT_ADMISSION')
    else:
        original = json.loads((HERE / ORIGINALS).read_bytes())['arms'][spec['arm']]
    need(original['arm'] == spec['arm'] and original['base'] == spec['base']
         and original['measured_closes'] < spec['measured_closes']
         and original['selected_session'] < spec['selected_session'], 'PARTIAL_OWN_EARLIER_MONTHLY_SOURCE_SEED')
    return original


def retained_models(root, parent, spec):
    schemas = [json.loads((Path(root) / 'book/repairs' / d['filename']).read_bytes())['schema']
               for d in parent['repairs']]
    declared = spec.get('retained_uncertainty_model')
    if declared is None:
        return all(s == 'terminal-repair/1' for s in schemas)
    from system_campaign_financial_branches import INPUT, validate_input
    need(spec['arm'] == 'P07' and declared == INPUT and schemas.count(INPUT) == 1
         and all(s in ('terminal-repair/1', INPUT) for s in schemas), 'PARTIAL_ONLY_EXACT_SELECTED_RETAINED_MODEL')
    validate_input(Path(root), parent)
    return True


def model_context(root, parent, spec):
    if spec.get('retained_uncertainty_model') is None:
        return nullcontext()
    from system_campaign_financial_branches import Codec, evidence
    return Codec(evidence(Path(root)))


def retention_tree():
    """Retain every frozen retainer statement except two declared codec sites."""
    import system_campaign_parallel_discovery_run as original
    raw = Path(original.__file__).read_bytes()
    request = json.loads((HERE / 'system-campaign-parallel-discovery-request-001.json').read_bytes())
    need(sha(raw) == request['sources']['system_campaign_parallel_discovery_run.py'],
         'PARTIAL_UNCHANGED_FROZEN_INPUT_RETAINER')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'retained_inputs']

    class SelectedModel(ast.NodeTransformer):
        guard = codec = 0

        def visit_Expr(self, node):
            if (isinstance(node.value, ast.Call) and any(isinstance(a, ast.Constant)
                    and a.value == 'PARALLEL_NO_UNSELECTED_CONDITIONAL_INPUT_MODELS' for a in node.value.args)):
                self.guard += 1
                node.value.args[0] = ast.parse('retained_models(root, parent, selected_spec)', mode='eval').body
                return node
            if isinstance(node.value, ast.Yield):
                self.codec += 1
                return [ast.parse('stack.enter_context(model_context(root, parent, selected_spec))').body[0], node]
            return self.generic_visit(node)

    adapter = SelectedModel()
    fn = adapter.visit(fn)
    need(adapter.guard == adapter.codec == 1, 'PARTIAL_EXACT_TWO_RETAINED_MODEL_SITES')
    return ast.fix_missing_locations(fn)


@contextmanager
def financial_inputs(root, parent, output, spec):
    import system_campaign_parallel_discovery_run as original
    if spec.get('retained_uncertainty_model') is None:
        with original.retained_inputs(root, parent, output):
            yield
        return
    fn = retention_tree()
    namespace = dict(vars(original), retained_models=retained_models, model_context=model_context, selected_spec=spec)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<source-bound-financial-input-retainer>', 'exec'), namespace)
    with namespace['retained_inputs'](root, parent, output):
        yield


def public_names(spec, archive):
    """This runs before GCM in the unchanged reader; public bytes are pinned."""
    names = archive.namelist()
    public = spec['public_members']
    need(len(names) == len(set(names)) == 5 and len(public) == 4
         and set(public) == {spec['receipt_name'], 'full-core-staging.json',
             'ephemeral-runner-capacity.json', 'resume-export-qualification-' + spec['arm'] + '.json'}
         and set(names) == set(public) | {spec['encrypted_output']['name']},
         'PARTIAL_EXACT_FIVE_UNIQUE_ZIP_MEMBERS')
    for name, expected in public.items():
        need(archive.getinfo(name).file_size == expected['bytes'] < 2 * 1024**2,
             'PARTIAL_PUBLIC_MEMBER_BOUND')
        raw = archive.read(name)
        need(dict(bytes=len(raw), sha256=sha(raw)) == expected, 'PARTIAL_EXACT_PUBLIC_BYTES')
    receipt = json.loads(archive.read(spec['receipt_name']))
    need(receipt['status'] == spec['receipt_status'] == 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
         and receipt['performance_admitted'] is False
         and {k: receipt[k] for k in spec['prior_stops']} == spec['prior_stops'],
         'PARTIAL_ACTUAL_PRIOR_STATUS_AND_STOPS')
    marker = json.loads(archive.read('resume-export-qualification-' + spec['arm'] + '.json'))
    need(marker == dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED',
         arm=spec['arm'], financial_sessions_advanced=0, credentials_saved=False),
         'PARTIAL_ACTUAL_EXPORT_PROBE')
    staging = json.loads(archive.read('full-core-staging.json'))
    need(staging['status'] == 'STAGING_PASSED' and staging['run_id'] == str(spec['run_id'])
         and staging['source_commit'] == spec['head'] and staging['protocol_sha256'] == PROTOCOL
         and staging['runtime_image'] == IMAGE and staging['execution_image'] == EXECUTION_IMAGE
         and staging['source_files_verified'] == 514 and staging['members_verified'] == 591
         and staging['authenticated_before_parsing'] is True and staging['offline_image_source_verified'] is True
         and staging['runtime_index_config_layer_chain_verified'] is True and staging['replay_started'] is False,
         'PARTIAL_ACTUAL_FROZEN_STAGING')
    return set(public) | {spec['encrypted_output']['name']}


def admission_tree():
    """Adapt exactly two format sites; retain every original authentication guard."""
    raw = Path(crypto.__file__).read_bytes()
    need(sha(raw) == CRYPTO_SHA, 'PARTIAL_UNCHANGED_ORIGINAL_CRYPTO_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'admit']

    class Format(ast.NodeTransformer):
        members = review = 0

        def visit_Set(self, node):
            if ast.unparse(node) == "{spec['receipt_name'], 'full-core-staging.json', asset['name']}":
                self.members += 1
                return ast.copy_location(ast.parse('public_names(spec, z)', mode='eval').body, node)
            return self.generic_visit(node)

        def visit_BinOp(self, node):
            if ast.unparse(node) == "dest / 'core-review.json'":
                self.review += 1
                return ast.copy_location(ast.parse("dest / 'stopped-review/core-review.json'", mode='eval').body, node)
            return self.generic_visit(node)

    adapter = Format()
    fn = adapter.visit(fn)
    need(adapter.members == adapter.review == 1, 'PARTIAL_EXACTLY_TWO_FORMAT_SITES')
    return ast.fix_missing_locations(fn)


def admit(spec, root, key, inspector):
    need(spec['archive_format'] == FORMAT and spec['financial_authority'] is False
         and spec['financial_predecessor_admitted'] is False
         and spec['manifest']['raw_member_bytes'] < 1024**3,
         'PARTIAL_READONLY_UNADMITTED_TARGET_SCOPE')
    namespace = dict(vars(crypto), public_names=public_names)
    fn = admission_tree()
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<source-bound-financial-format-adapter>', 'exec'), namespace)
    destination = namespace['admit'](spec, root, key, max_zip_bytes=512 * 1024**2)
    for name, expected in spec['inspections'].items():
        value = json.loads((destination / name).read_bytes())
        need(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', expected['user']) is not None,
             'PARTIAL_POSITIVE_ORIGINAL_UID_GID')
        inspector(expected['name'].removeprefix('/'), expected['id'], value=value,
            run_id=str(spec['run_id']), user=expected['user'],
            correlation_prefix=expected['correlation_prefix_mounted'])
        state = value['State']
        need(state['Running'] is False and state['OOMKilled'] is False
             and type(state['ExitCode']) is int and state['ExitCode'] == expected['exit_code'],
             'PARTIAL_ACTUAL_ARCHIVED_POSITIVE_STOP')
    review = json.loads((destination / 'stopped-review/core-review.json').read_bytes())
    need(review['all_prefixes_verified'] is True and review['all_daily_factors_and_chains_verified'] is True
         and review['checkpoint_sha256'] == spec['outer_sha256']
         and review['counts'] == dict(formation=126, daily=spec['measured_closes']),
         'PARTIAL_ORIGINAL_FULL_PREFIX_REVIEW')
    raw = (destination / 'request.json').read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['original_request_member']
         and sha(raw) == spec['request_sha256'], 'PARTIAL_ORIGINAL_REQUEST_MEMBER')
    from ephemeral_runner_capacity import validate_prepared_receipt
    with zipfile.ZipFile(destination.parent / 'predecessor.zip') as archive:
        capacity = json.loads(archive.read('ephemeral-runner-capacity.json'))
    validate_prepared_receipt(capacity, head=spec['head'], run_id=str(spec['run_id']),
        source_sha256=json.loads(raw)['sources']['ephemeral_runner_capacity.py'])
    return destination


def reproduce_reports(stats, parent, current, daily, reports, following):
    """Only recorded NAV/report values are ingested; this is not a financial run."""
    need(len(daily) == current['completed'] - parent['completed'] > 0
         and following > current['source_cursor'] == daily[-1]['session'], 'PARTIAL_REPORTING_SUFFIX_AXIS')
    dates = [r['session'] for r in daily] + [following]
    actual = []
    for index, row in enumerate(daily):
        report = stats.advance(row['session'], {k: Decimal(v) for k, v in row['comparison_navs'].items()},
            core_target=str(row['decision']['target_core_exposure']), month_end=dates[index + 1][:7] != row['session'][:7])
        if report:
            actual.append(report)
    stored = deepcopy(reports)
    for report in stored:
        report.pop('slot_retries')
    need(actual == stored and stats.to_dict() == current['stats'],
         'PARTIAL_ALL_NEW_REPORTS_AND_ENTIRE_STATS_EXACT')
    return dict(new_daily_records=len(daily), new_reports=len(reports),
                all_new_monthly_reports_exact=True, all_monthly_checkpoint_state_exact=True)


def monthly_reproduction(evidence, out, spec, current):
    hosted()
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    from research.pooled_input_support.bundle import axis
    need(sha256_file(HERE / ORIGINALS) == spec['original_parent_index_sha256'],
         'PARTIAL_EXACT_RETAINED_ORIGINAL_INDEX')
    original = reporting_seed(spec)
    path = evidence / 'book/predecessor-checkpoints' / (original['outer_sha256'] + '.json.gz')
    raw = path.read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == original['selected_file'],
         'PARTIAL_EXACT_ORIGINAL_MONTHLY_SEED_GZIP')
    parent = require_strict_checkpoint(json.loads(gzip.decompress(raw)))
    check_parent(parent, original)
    need(parent['base'] == current['base'], 'PARTIAL_SAME_MONTHLY_SOURCE_BASE')

    def rows(name):
        raw = (evidence / 'book' / (name + '.jsonl')).read_bytes()
        before, after = parent['journals'][name], current['journals'][name]
        need(after['bytes'] >= before['bytes'] and sha(raw[:before['bytes']]) == before['prefix_sha256']
             and sha(raw[:after['bytes']]) == after['prefix_sha256'], 'PARTIAL_REPORTING_ORIGINAL_AND_CURRENT_PREFIXES')
        return [json.loads(line) for line in raw[before['bytes']:after['bytes']].splitlines()]

    daily, reports = rows('daily'), rows('monthly')
    measured = [d for d in axis() if '2018-01-02' <= d <= '2026-07-31']
    need(len(measured) == 2156 and measured == sorted(set(measured))
         and measured[parent['completed']:current['completed']] == [r['session'] for r in daily],
         'PARTIAL_EXACT_FROZEN_NEW_REPORTING_AXIS')
    following = measured[current['completed']] if current['completed'] < 2156 else '2026-08-03'
    with localcontext() as context:
        context.prec = 50
        proof = reproduce_reports(MonthlyStats.from_dict(parent['stats']), parent, current, daily, reports, following)
    source = Path('/variant/research/pooled_vacancy_funding/monthly.py')
    need(sha256_file(source) == current['base']['sources']['research/pooled_vacancy_funding/monthly.py'],
         'PARTIAL_ACTUAL_MONTHLY_IMPLEMENTATION_SOURCE')
    proof.update(schema='research.partial-exact-linux-monthly-reproduction/1', passed=True,
        arm=spec['arm'], parent_sha256=parent['sha256'], checkpoint_sha256=current['sha256'],
        completed=current['completed'], source_cursor=current['source_cursor'], next_session=following,
        monthly_source_sha256=sha256_file(source), complete_stored_reports_sha256=digest(reports),
        entire_monthly_journal_sha256=sha256_file(evidence / 'book/monthly.jsonl'),
        financial_transitions_reexecuted=0, financial_authority=False)
    save(out / 'monthly-reproduction.json', proof)
    return proof
