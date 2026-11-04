"""Authenticate stopped financial evidence and reproduce recorded reporting only."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
import gzip
import json
from pathlib import Path
import re
from types import SimpleNamespace
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
FRESH_FORMAT = 'FRESH_CANDIDATE_SIX_MEMBER_ZIP/1'
FRESH_REQUEST = 'system-campaign-fresh-origin-request.json'
FRESH_TARGET_SHA = '0aaa2967a245b4eefc9097fd84b6227a0f99717c65dc88b21b2736aeecdf2d1d'
FRESH_REQUEST_SHA = '13d68690a7e940bc52d1060098a04d577932f292b30418a29cbfc2346f242b0d'
INITIAL_PREFIX_TARGETS = {
    'P03': '6ddbfef83b3f4d69922cd65deabe7ab8d54db983fca9652c89c0e4948e99fb18',
    'P05': 'd56ad992d8086d0815cbeabc57dd2bec5971e9bff051e2bd65ab4d37799c3faf',
    'P06': '651d13b0bbc442d44f4735374c56bdb2e49b6d6275b5f7e2d875705c0db75436',
    'P11': '14678692a6ed71a18c7ded8b66e4146148a8608403fcfb9a05c744797c3e869e',
}
INITIAL_PREFIX_AXES = {
    'P03': (82, '2018-04-30'),
    'P05': (21, '2018-01-31'),
    'P06': (21, '2018-01-31'),
    'P11': (21, '2018-01-31'),
}
ROOTS = 'system-campaign-financial-admitted-parents.json'
ADMISSIONS = {
    'P03': '65b4309305ed9a62a6dfd9db12070d124dcc7e5efcc1a582555386ff5c7dbd9c',
    'P11': '33320498ba5db684738471b48b0ed3e66ebf78fe5b2b9dc24a34be047cdbf3ed',
    'P06': '45a6bf68f61ddd5eaa2852faddc26dea4541b49d5e477c614416dd13f4172bb2',
    'P05': 'cdd16c9f0b0ceef3cd8122ef586e23c43c2ebfe662d7cd0a9cb38430a271781a',
    'P00': 'a666dc395e4c3d6e84ae7402967e28befa65052d84d6da68d5df52b8bc9970bc',
    'P04': 'c43253a987d6e930f3a60b14e85a52fd0c05f768c6113132d0448d1fc8d99a9a',
    'P07': '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3',
    'P10': '3e73749345802edc681eb20d1adbaf741bebab3df9ea7bcc7ff4ac453a50b0e9',
}
COMPLETED_ADMISSIONS = {'P04': '301789ec44be3eabc3d4c7985a456f48f46f35b6db976ef60902ba93644d04e9', 'P00': '65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83', 'P10': '6e20b57099843380d9436d7a60c25c313abe53785f9db40049f59b411c9e8105'}
COMPLETION_METADATA = {
    'P04': ((41873209115, 'bc86a3c7b929e405aa0513d75b35850752579847', 13344609868), (186, 372, 9, 103)),
    'P00': ((41850177338, '7f8a9902b8e334ec155e6155f3df444c456c73eb', 13336350083), (273, 546, 13, 103)),
    'P10': ((41813568077, '9689c5fecc5462a5d65370fc5564fe447a8a92f8', 13313801504), (564, 1128, 27, 103)),
}
PRIOR_ADMISSIONS = {
    'P04': '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492',
    'P07': '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa',
    'P10': 'c3e9784fdaee742284dc4f7d90aaecbcb541cb50f699dabbb17e8c250f68815c',
}
ADMISSION_CLOCKS = {
    'P03': {'65b4309305ed9a62a6dfd9db12070d124dcc7e5efcc1a582555386ff5c7dbd9c': (41880115517, '2e9c7f584e3c351eb80f7ce5e6fb6d41c1c18768')},
    'P11': {'33320498ba5db684738471b48b0ed3e66ebf78fe5b2b9dc24a34be047cdbf3ed': (41869499928, '4615284d77f1edef54abadaeccc877bf21c9bdb2'), '6d6cb4beb530ba6f26323cc4c988984631639f4439728144e4e6f11c5787128c': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P06': {'45a6bf68f61ddd5eaa2852faddc26dea4541b49d5e477c614416dd13f4172bb2': (41869499928, '4615284d77f1edef54abadaeccc877bf21c9bdb2'), 'f7421f89b0f7af3abac7cec3c475eb19a18b0c3cfe7094929e55248121125e18': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P05': {'cdd16c9f0b0ceef3cd8122ef586e23c43c2ebfe662d7cd0a9cb38430a271781a': (41878282620, '5e3c556b1023053f214daf0a77c8a4fc3491b439'), 'b5135e817ef9359ce83922fbe9200cfc32033628d2ff98fec1673e8d9ebd2197': (41846392431, 'c5a96301d911d6657494738161d88152d7690fd3')},
    'P00': {'a666dc395e4c3d6e84ae7402967e28befa65052d84d6da68d5df52b8bc9970bc': (41834686720, 'eb872aebb9d724162d6ace803501fac383c799c4'), 'c08cec7a7dc2b9fe84f9318c81b2874f25ae45fd9126f80e00deee70ee3f4694': (41796544434, '3035b8c9b70af4174fc0e83b9a85f6853a754795')},
    'P04': {
        'c43253a987d6e930f3a60b14e85a52fd0c05f768c6113132d0448d1fc8d99a9a': (41855117019, '375fc428e0b119bc5b705be8f41bed0df7c516b2'),
        'd3840804886e14e60bb193b8123b29c282be82ca049e18107b33423a7b210521': (41839831877, '3d9d0d4b8b96f7d5b5e3c667a35d6ece77ac1e16'),
        'dfcd3aee60ebd3ea7fdc073454af662170a14960f9b034cae6177431ea6c8e2c': (41827835979, '08382e11758c1813f5d40747108564064638cbbb'),
        '58036453b01d009fc05f3626e735bc16c0bd1787f2ca951aeeb936ac57a4da45': (41789942448, '1a4773b535f6aa2e9ab6e49adcfb247f062d4e52'),
        '11c64d8c83d26c8e381ddc4e306829e896f3996c423c394d50c5b2d2d0307492': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        '7177334f71ec924d37810189a9c8f94e6f00073f5808a3aa1ec4647801a51986': (41776035604, 'e5bc98c38b4b1983de82ff30dc77711f7f9cc31c'),
        'c0e9c671daa7a620f8d0fede0ba548a6edf5d669da99a083a7df65aebd301156': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P07': {
        '672a0a0a7560d1b3d4658e6c0e79c3f4259391ac4a7f2d3ecb58e505f5132ef3': (41889291908, 'b5a640008abec4ae92f53ee556d9bf571219ec08'),
        'f7f86bf917f7d2718c8e360a4e1d1de2c2d90d6dd94406e581c6712201a8b776': (41852967218, '5b12190964523b300bc587a811a18076124ace22'),
        '2293655ea9e4c520c66e016a33c9d33b78f12ceb09c50a371bc84b76c0eef543': (41825451226, '0f026df6b4358280479417857bf0521f5cd2685b'),
        '30552e338938b213e0dcfe5ef06ca6defcca8d0627126cf39cfd63b2982c9e03': (41819198754, 'b190e5f67b7f3ef24eeb7d6f7631b2c97b010c87'),
        '46fd68cb0d747c8c5ca004e979f49f89c02d505ef69069af7e086bd18b18268d': (41787444086, 'b089f323d9537e34011325a2884d9ad44555db1c'),
        '760e41a64a8e2fdf497c96919a5aef9eaa34a9faddee26bc9b5cee843b2ab8fa': (41754595229, 'cec7f49da4edf5ca4dd760e3b593451624c1d063'),
        'c3b3695de955721404aa8b1eb04f2f272efa4f3bd01c8bdd5fac10b92995811c': (41769843340, 'eb7d24f2466498062d0b32054ab086fc3d243253'),
    },
    'P10': {
        '3e73749345802edc681eb20d1adbaf741bebab3df9ea7bcc7ff4ac453a50b0e9': (41795159693, '03aa7a123ad3d34ddcc07ce348e32357b43c7f89'),
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
         and t['archive_format'] in (FORMAT, FRESH_FORMAT)
         and t['financial_authority'] is t['financial_predecessor_admitted'] is False,
         'FINANCIAL_ONLY_SEPARATE_ROOT_CONTINUATION_AUTHORITY')
    if t['archive_format'] == FRESH_FORMAT:
        initial_reporting_seed(t)
        need(arm == 'P00' and a['initial_empty_origin_verified'] is True
             and a['historical_p00_state_or_returns_reused'] is False
             and a['initial_formation_records'] == 126 and a['new_daily_records'] == 169
             and a['parent_root_admission_sha256'] is None
             and a['fresh_empty_origin_proof_sha256'] == t['public_members']['fresh-origin-admission-P00.json']['sha256'],
             'FINANCIAL_ONLY_EXACT_NEW_FRESH_P00_ORIGIN_ADMISSION')
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


def completed_result(arm):
    """Read exact completed research scoring authority, never continuation authority."""
    entry = json.loads((HERE / ROOTS).read_bytes())['completed_financial_roots'][arm]
    return authorized_completion(entry, arm)


def authorized_completion(entry, arm):
    a, t = entry['admission'], entry['transport']
    raw = (json.dumps(a, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    need(arm in COMPLETED_ADMISSIONS and sha(raw) == entry['admission_sha256'] == COMPLETED_ADMISSIONS[arm],
         'FINANCIAL_EXACT_COMPLETED_RESEARCH_ADMISSION_BYTES')
    need(a['schema'] == 'research.root-completed-financial-result-admission/1'
         and a['status'] == 'ADMITTED_COMPLETE_FINANCIAL_RESEARCH_RESULT' and a['arm'] == t['arm'] == arm
         and a['full_financial_validation_completed'] is a['performance_scoring_authorized'] is True
         and a['financial_continuation_authorized'] is False and full_target(t)
         and a['completed'] == t['measured_closes'] == 2156
         and a['source_cursor'] == t['selected_session'] == '2026-07-31'
         and a['parent_root_admission_sha256'] == t['monthly_seed_root_admission_sha256'] == ADMISSIONS[arm]
         and (a['readonly_run_id'], a['readonly_head'], a['readonly_artifact_id']) ==
             COMPLETION_METADATA[arm][0]
         and all(a[k] is True for k in ('all_new_cash_shares_receivables_and_raw_marks_verified',
             'all_new_funded_factors_and_financial_chains_verified', 'all_new_monthly_and_retry_state_verified',
             'financial_source_epoch_unchanged', 'input_adoptions_fully_state_neutral', 'empty_uncommitted_tails_verified'))
         and a['production_contacted'] is a['local_canonical_runtime_executed'] is False
         and (a['new_daily_records'], a['independent_accounting_snapshots'], a['new_monthly_reports'], a['total_monthly_reports'])
             == COMPLETION_METADATA[arm][1], 'FINANCIAL_COMPLETE_RESEARCH_SCORING_ONLY_SCOPE')
    for key in ('base', 'journals', 'repairs', 'selected_checkpoint', 'selected_file', 'outer_sha256',
                'inner_sha256', 'state_sha256', 'input_sha256', 'source_binding_sha256'):
        need(a[key] == t[key], 'FINANCIAL_COMPLETED_EXACT_OWN_' + key.upper())
    need(a['financial_artifact_id'] == t['artifact_id'] and a['financial_run_id'] == t['run_id']
         and a['financial_head'] == t['head'] and a['financial_zip_sha256'] == t['zip_sha256']
         and a['financial_cipher_sha256'] == t['encrypted_output']['sha256'],
         'FINANCIAL_COMPLETED_EXACT_TRANSPORT_PROVENANCE')
    return deepcopy(a)


def validate_root_spec(spec):
    transport = {k: v for k, v in spec.items() if k not in ('root_admission', 'root_admission_sha256')}
    need(authorized_spec(dict(transport=transport, admission=spec['root_admission'],
         admission_sha256=spec['root_admission_sha256']), spec['arm']) == spec,
         'FINANCIAL_EXACT_ROOT_SPEC')


def reporting_seed(spec):
    """Select an independently admitted own seed, never arbitrary newer state."""
    if spec.get('initial_prefix_reporting') is not None:
        return initial_prefix_seed(spec)
    if spec.get('archive_format') == FRESH_FORMAT:
        return initial_reporting_seed(spec)
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


def initial_prefix_seed(spec):
    """Reporting only for exact existing own prefixes on their declared axes."""
    need(spec.get('arm') in INITIAL_PREFIX_TARGETS
         and digest(spec) == INITIAL_PREFIX_TARGETS[spec['arm']],
         'PARTIAL_EXACT_EXISTING_INITIAL_PREFIX_TARGET')
    seed = spec['initial_monthly_seed']
    need(spec['initial_prefix_reporting'] is True and spec['archive_format'] == FORMAT
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and (spec['measured_closes'], spec['selected_session']) == INITIAL_PREFIX_AXES[spec['arm']]
         and seed['arm'] == spec['arm'] and seed['measured_closes'] == 0
         and seed['selected_session'] == '2017-06-30'
         and all(seed['journals'][n]['bytes'] == 0 for n in ('daily', 'monthly')),
         'PARTIAL_ONLY_ORIGINAL_ZERO_MEASUREMENT_REPORTING_SEED')
    return dict(deepcopy(seed), base=deepcopy(spec['base']))


def initial_reporting_seed(spec):
    """This grants only reporting review of the one genuine fresh export."""
    if 'root_admission' in spec:
        validate_root_spec(spec)
        spec = {k: v for k, v in spec.items() if k not in ('root_admission', 'root_admission_sha256')}
    need(digest(spec) == FRESH_TARGET_SHA and spec['archive_format'] == FRESH_FORMAT
         and spec['arm'] == 'P00' and spec['measured_closes'] == 169
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False,
         'PARTIAL_EXACT_FRESH_INITIAL_REPORTING_TARGET')
    return dict(deepcopy(spec['initial_monthly_seed']), base=deepcopy(spec['base']))


def review_name(spec):
    need(spec['archive_format'] in (FORMAT, FRESH_FORMAT), 'PARTIAL_DECLARED_ARCHIVE_FORMAT')
    return 'core-review.json' if spec['archive_format'] == FRESH_FORMAT else 'stopped-review/core-review.json'


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
    if spec['archive_format'] == FRESH_FORMAT:
        return fresh_public_names(spec, archive)
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
    status = ('COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT' if full_target(spec)
              else 'PARTIAL_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT')
    need(receipt['status'] == spec['receipt_status'] == status
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


def full_target(spec):
    """An explicit complete transport is reporting evidence, never a resume seed."""
    if 'readonly_full_financial_target' not in spec:
        return False
    need(spec['readonly_full_financial_target'] is True and spec['archive_format'] == FORMAT
         and spec['measured_closes'] == 2156 and spec['selected_session'] == '2026-07-31'
         and spec['receipt_status'] == 'COMPLETE_FINANCIAL_HOSTED_REVIEWED_PENDING_ROOT'
         and spec['financial_authority'] is spec['financial_predecessor_admitted'] is False
         and all(spec['prior_stops'][role]['stopped'] is True
                 and type(spec['prior_stops'][role]['exit_code']) is int
                 and spec['prior_stops'][role]['exit_code'] == 0
                 and spec['prior_stops'][role]['oom_killed'] is False
                 for role in ('preflight', 'worker', 'reviewer')),
         'PARTIAL_ONLY_EXPLICIT_SUCCESSFUL_COMPLETE_READONLY_TARGET')
    return True


def fresh_public_names(spec, archive):
    initial_reporting_seed(spec)
    names, public = archive.namelist(), spec['public_members']
    need(len(names) == len(set(names)) == 6 and len(public) == 5
         and set(public) == {spec['receipt_name'], 'full-core-staging.json',
             'ephemeral-runner-capacity.json', 'fresh-origin-admission-P00.json',
             'fresh-origin-export-qualification-P00.json'}
         and set(names) == set(public) | {spec['encrypted_output']['name']},
         'PARTIAL_EXACT_SIX_UNIQUE_FRESH_MEMBERS')
    for name, expected in public.items():
        need(archive.getinfo(name).file_size == expected['bytes'] < 2 * 1024**2,
             'PARTIAL_PUBLIC_MEMBER_BOUND')
        raw = archive.read(name)
        need(dict(bytes=len(raw), sha256=sha(raw)) == expected, 'PARTIAL_EXACT_PUBLIC_BYTES')
    raw = (HERE / FRESH_REQUEST).read_bytes()
    need(sha(raw) == FRESH_REQUEST_SHA and dict(bytes=len(raw), sha256=sha(raw)) == spec['fresh_request_member'],
         'PARTIAL_DISTINCT_CLOSED_FRESH_REQUEST_BYTES')
    fresh = json.loads(raw)
    import system_campaign_candidate_job as candidate
    original = candidate.expected_request()
    need(fresh['arm'] == 'P00' and fresh['index'] == 0 and fresh['fresh_origin'] is True
         and fresh['parameters'] == original['initial_candidates'][0]['parameters']
         and fresh['candidate_id'] == original['initial_candidates'][0]['id']
         and fresh['original_candidate_request_sha256'] == spec['request_sha256']
         and fresh['inherited_financial_rows'] == 0
         and fresh['prior_checkpoint_imported'] is fresh['historical_result_reused'] is False,
         'PARTIAL_ONLY_CLOSED_EMPTY_P00_ORIGIN')
    proof = json.loads(archive.read('fresh-origin-admission-P00.json'))
    need(proof == spec['fresh_origin_admission'] and proof['request_sha256'] == sha(raw)
         and proof['previous_book_selected'] is proof['financial_runtime_executed'] is False
         and proof['old_p00_performance_is_not_completion_authority'] is True,
         'PARTIAL_REUSE_EXACT_CLOSED_FRESH_ORIGIN_PROOF')
    receipt = json.loads(archive.read(spec['receipt_name']))
    need(receipt['status'] == spec['receipt_status'] == 'PARTIAL_CANDIDATE_PREFIX_REVIEWED'
         and receipt['candidate_id'] == fresh['candidate_id'] and receipt['performance_admitted'] is False
         and {k: receipt[k] for k in spec['prior_stops']} == spec['prior_stops']
         and all(receipt[k]['stopped'] is True and type(receipt[k]['exit_code']) is int
                 and receipt[k]['oom_killed'] is False for k in ('worker', 'reviewer'))
         and receipt['reviewer']['exit_code'] == 0,
         'PARTIAL_ACTUAL_FRESH_STATUS_AND_STOPS')
    need(json.loads(archive.read('fresh-origin-export-qualification-P00.json')) == dict(
         status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED', arm='P00',
         financial_sessions_advanced=0, credentials_saved=False), 'PARTIAL_ACTUAL_FRESH_EXPORT_PROBE')
    staging = json.loads(archive.read('full-core-staging.json'))
    need(staging['status'] == 'STAGING_PASSED' and staging['run_id'] == str(spec['run_id'])
         and staging['source_commit'] == spec['head'] and staging['protocol_sha256'] == PROTOCOL
         and staging['runtime_image'] == IMAGE and staging['execution_image'] == EXECUTION_IMAGE
         and staging['source_files_verified'] == 514 and staging['members_verified'] == 591
         and staging['manifest_sha256'] == fresh['frozen_input_manifest_sha256']
         and all(staging[k] is True for k in ('authenticated_before_parsing', 'offline_image_source_verified',
                                             'runtime_index_config_layer_chain_verified'))
         and staging['replay_started'] is False, 'PARTIAL_ACTUAL_FROZEN_FRESH_STAGING')
    return set(names)


def admission_tree(review_file='stopped-review/core-review.json'):
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
                return ast.copy_location(ast.BinOp(left=ast.Name(id='dest', ctx=ast.Load()),
                    op=ast.Div(), right=ast.Constant(review_file)), node)
            return self.generic_visit(node)

    adapter = Format()
    fn = adapter.visit(fn)
    need(adapter.members == adapter.review == 1, 'PARTIAL_EXACTLY_TWO_FORMAT_SITES')
    return ast.fix_missing_locations(fn)


def admit(spec, root, key, inspector):
    need(spec['archive_format'] in (FORMAT, FRESH_FORMAT) and spec['financial_authority'] is False
         and spec['financial_predecessor_admitted'] is False
         and spec['manifest']['raw_member_bytes'] < 1024**3,
         'PARTIAL_READONLY_UNADMITTED_TARGET_SCOPE')
    namespace = dict(vars(crypto), public_names=public_names)
    fn = admission_tree(review_name(spec))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<source-bound-financial-format-adapter>', 'exec'), namespace)
    destination = namespace['admit'](spec, root, key, max_zip_bytes=512 * 1024**2)
    for name, expected in spec['inspections'].items():
        value = json.loads((destination / name).read_bytes())
        need(re.fullmatch(r'[1-9][0-9]*:[1-9][0-9]*', expected['user']) is not None,
             'PARTIAL_POSITIVE_ORIGINAL_UID_GID')
        archived_inspection(spec, expected, value, inspector)
        state = value['State']
        need(state['Running'] is False and state['OOMKilled'] is False
             and type(state['ExitCode']) is int and state['ExitCode'] == expected['exit_code'],
             'PARTIAL_ACTUAL_ARCHIVED_POSITIVE_STOP')
    review = json.loads((destination / review_name(spec)).read_bytes())
    need(review['all_prefixes_verified'] is True and review['all_daily_factors_and_chains_verified'] is True
         and review['checkpoint_sha256'] == spec['outer_sha256']
         and review['counts'] == dict(formation=126, daily=spec['measured_closes']),
         'PARTIAL_ORIGINAL_FULL_PREFIX_REVIEW')
    if full_target(spec):
        need(review['complete'] is True and review['monthly_metrics'] == 103
             and all(v == dict(bytes=0, sha256=sha(b'')) for v in review['preserved_tails'].values())
             and set(review['preserved_tails']) == {'formation', 'daily', 'monthly', 'watch'},
             'PARTIAL_COMPLETE_ENDPOINT_AND_EMPTY_TAILS')
    raw = (destination / 'request.json').read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['original_request_member']
         and sha(raw) == spec['request_sha256'], 'PARTIAL_ORIGINAL_REQUEST_MEMBER')
    from ephemeral_runner_capacity import validate_prepared_receipt
    with zipfile.ZipFile(destination.parent / 'predecessor.zip') as archive:
        capacity = json.loads(archive.read('ephemeral-runner-capacity.json'))
    capacity_sources = (json.loads((HERE / FRESH_REQUEST).read_bytes()) if spec['archive_format'] == FRESH_FORMAT
                        else json.loads(raw))['sources']
    validate_prepared_receipt(capacity, head=spec['head'], run_id=str(spec['run_id']),
        source_sha256=capacity_sources['ephemeral_runner_capacity.py'])
    return destination


def archived_inspection(spec, expected, value, inspector):
    if spec['archive_format'] == FORMAT:
        return inspector(expected['name'].removeprefix('/'), expected['id'], value=value,
            run_id=str(spec['run_id']), user=expected['user'],
            correlation_prefix=expected['correlation_prefix_mounted'])
    initial_reporting_seed(spec)
    import system_campaign_candidate_job as candidate
    raw = Path(candidate.__file__).read_bytes()
    fresh = json.loads((HERE / FRESH_REQUEST).read_bytes())
    need(sha(raw) == fresh['sources']['system_campaign_candidate_job.py'], 'PARTIAL_ORIGINAL_CANDIDATE_INSPECTOR')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'inspect']
    assignment, = [n for n in fn.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'v' for t in n.targets)]
    assignment.value = ast.Name(id='supplied', ctx=ast.Load())
    uid, gid = map(int, expected['user'].split(':'))
    ns = dict(vars(candidate), supplied=value, os=SimpleNamespace(getuid=lambda: uid, getgid=lambda: gid))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<unchanged-candidate-inspector-archived-state>', 'exec'), ns)
    ns['inspect'](expected['name'].removeprefix('/'), expected['id'])
    phase = expected['phase']
    command = ['-B', '-u', '/driver/system_campaign_candidate.py', '--mode', phase]
    if phase == 'review':
        command += ['--evidence-root', '/evidence']
    need(phase in ('economic', 'review') and value['Config']['Entrypoint'] == ['python']
         and value['Config']['Cmd'] == command and value['Config']['User'] == expected['user'],
         'PARTIAL_EXACT_ORIGINAL_CANDIDATE_ENTRYPOINT')
    return value


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


def reporting_stats(cls, parent, current, spec):
    if parent['stats'] is not None:
        return cls.from_dict(parent['stats'])
    (initial_prefix_seed if spec.get('initial_prefix_reporting') is not None else initial_reporting_seed)(spec)
    required = ('pooled', 'owned55_previous', 'compact_previous', 'spy')
    need(parent['completed'] == 0 and parent['stats'] is None
         and all(parent['journals'][n]['bytes'] == 0 for n in ('daily', 'monthly'))
         and current['base']['start'] == '2018-01-02' and current['base']['capital'] == '50000'
         and current['stats']['primary'] == 'pooled'
         and current['stats']['required_series'] == list(required)
         and set(current['stats']['series']) == set(required)
         and all(v['initial_nav'] == '50000' for v in current['stats']['series'].values()),
         'PARTIAL_ONLY_EXACT_ZERO_MEASUREMENT_REPORTING_BOOTSTRAP')
    return cls.fresh('2018-01-02', {n: '50000' for n in required},
                     primary='pooled', required_series=required)


def monthly_reproduction(evidence, out, spec, current):
    hosted()
    from research.pooled_vacancy_funding.monthly import MonthlyStats
    from research.pooled_input_support.bundle import axis
    need(sha256_file(HERE / ORIGINALS) == spec['original_parent_index_sha256'],
         'PARTIAL_EXACT_RETAINED_ORIGINAL_INDEX')
    original = reporting_seed(spec)
    path = (evidence / original['selected_checkpoint'] if spec['archive_format'] == FRESH_FORMAT
            or spec.get('initial_prefix_reporting') is True
            else evidence / 'book/predecessor-checkpoints' / (original['outer_sha256'] + '.json.gz'))
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
    source = Path('/variant/research/pooled_vacancy_funding/monthly.py')
    need(sha256_file(source) == current['base']['sources']['research/pooled_vacancy_funding/monthly.py'],
         'PARTIAL_ACTUAL_MONTHLY_IMPLEMENTATION_SOURCE')
    with localcontext() as context:
        context.prec = 50
        proof = reproduce_reports(reporting_stats(MonthlyStats, parent, current, spec),
                                  parent, current, daily, reports, following)
    proof.update(schema='research.partial-exact-linux-monthly-reproduction/1', passed=True,
        arm=spec['arm'], parent_sha256=parent['sha256'], checkpoint_sha256=current['sha256'],
        completed=current['completed'], source_cursor=current['source_cursor'], next_session=following,
        monthly_source_sha256=sha256_file(source), complete_stored_reports_sha256=digest(reports),
        entire_monthly_journal_sha256=sha256_file(evidence / 'book/monthly.jsonl'),
        financial_transitions_reexecuted=0, financial_authority=False)
    save(out / 'monthly-reproduction.json', proof)
    return proof
