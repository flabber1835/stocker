"""Finite actual FIN340 P03 full17 read-only monthly reporting declaration."""
import ast, gzip, json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from system_campaign_bounded_sensor_input import need, sha, digest
HERE = Path(__file__).parent
FACT = 'P03-FIN345-full18-reporting-fact-v1.json'
FACT_SHA = '63f4f9f7cb7fbbb7fba0ea83e6bab6a5eaaaf323b28f1d0f2eafd57e13e0b9f7'
REQUEST = 'P03-FIN345-full18-reporting-source-request.json'
REQUEST_SHA = '46219b384b6a09c9f98a2ea3611139143684e379738e1ad5ef88585b0d1a08a7'
ROOT = 'bff8b5f2dea2bba80ed2da03053e95246cce401db749c4a0d4f54302cd5f2877'
OUTER = '50529edab057a7f1a835f3ebb6e947efc5b4f10b64ca941d12f212cd709d1f8a'
TAG = 'research.leadership-branch-uncertainty-input/1'
MODE = 'READONLY_NEW_FINANCIAL_PREFIX_AND_REPORTING_ADMISSION'
FIELD = 'selected_p03_full18_reporting_bridges'
MARKER = 'p03_full18_readonly_reporting_bridge'

def encoded(v):
    return (json.dumps(v, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()

def source_names():
    return (Path(__file__).name, FACT, REQUEST)

def fact():
    raw = (HERE / FACT).read_bytes()
    need(sha(raw) == FACT_SHA, 'P03_REPORT_EXACT_ACTUAL_FULL17_FACT')
    value = json.loads(raw)
    raw = (HERE / REQUEST).read_bytes()
    need(sha(raw) == REQUEST_SHA == value['captured_request_sha256'], 'P03_REPORT_EXACT_CAPTURED_FIN340_REQUEST')
    request = json.loads(raw)
    need(request['schema'] == 'research.system-campaign-accurate-resume-request/211' and request['execution_mode'] == 'OWN_ADMITTED_FINANCIAL_CONTINUATION' and (request['financial_resume_authorized'] is True) and (request['selected_bounded_models']['P03'] == value['captured_bounded_declaration']) and (value['captured_bounded_declaration']['root_admission_sha256'] == ROOT) and ((value['retained_rows'], value['new_financial_rows'], value['total_committed_proof_rows']) == (70, 19, 89)) and (value['readonly_reporting_only'] is True) and (value['root_admitted'] is value['financial_resume_authorized'] is value['actual_state_serialized'] is False) and (value['financial_transitions_reexecuted'] == 0), 'P03_REPORT_EXACT_ORIGINAL503_DECLARATION_AND_NO_NEW_AUTHORITY')
    return value

def selected(spec):
    return isinstance(spec, dict) and spec.get('arm') == 'P03' and (spec.get('outer_sha256') == OUTER)

def validate_target(spec):
    need(selected(spec), 'P03_REPORT_ONLY_ACTUAL_SAVED524_TARGET')
    value = fact()
    target = value['target']
    plain = {k: v for k, v in spec.items() if k != MARKER}
    need('root_admission' not in spec and 'root_admission_sha256' not in spec and (spec.get('financial_authority') is spec.get('financial_predecessor_admitted') is False) and (spec.get('monthly_seed_root_admission_sha256') == ROOT) and (len(spec.get('repairs', [])) == 18), 'P03_REPORT_UNADMITTED_FULL17_TARGET_OLD503_MONTHLY_SEED')
    need(encoded(plain) == encoded(target), 'P03_REPORT_EVERY_EXACT_TRANSPORT_TARGET_FIELD')
    need(spec['input_sha256'] == digest(dict(base=spec['base'], repairs=spec['repairs'])), 'P03_REPORT_WHOLE_CURRENT17_INPUT_HASH')
    return value

def declaration(spec):
    validate_target(spec)
    return dict(schema='research.p03-full18-readonly-reporting-bridge/1', arm='P03', target_outer_sha256=OUTER, completed=543, source_cursor='2020-02-28', full_inputs=18, monthly_seed_root_admission_sha256=ROOT, fact_file=FACT, fact_sha256=FACT_SHA, captured_request_sha256=REQUEST_SHA, retained_rows=70, new_financial_rows=19, original_B19_and_typed_DOVA_codecs_retained=True, actual_full_input_visitor_required=True, whole_monthly_reproduction_unchanged=True, financial_reuse_seed_installed=False, financial_resume_authorized=False, financial_transitions_reexecuted=0, root_admitted=False)

def qualify_target(spec):
    expected = declaration(spec)
    need(MARKER not in spec or spec[MARKER] == expected, 'P03_REPORT_NO_FOREIGN_MARKER')
    return dict(deepcopy(spec), **{MARKER: expected})

def request_declaration(spec, request):
    need(encoded(spec) == encoded(qualify_target(spec)), 'P03_REPORT_EXPLICIT_QUALIFIED_TARGET_REQUIRED')
    expected = declaration(spec)
    need(request['execution_mode'] == MODE and request['financial_resume_authorized'] is False and (request['readonly_partial_review'] is True) and (request['readonly_source_witnesses'] is False) and (type(request['maximum_parallel_financial_workers']) is int) and (request['maximum_parallel_financial_workers'] == 0) and (request.get('selected_p03_thor_qualification_reuse', {}) == {}) and (request.get(FIELD, {}).get('P03') == expected), 'P03_REPORT_ONLY_EXPLICIT_READONLY_ZERO_FINANCIAL_REQUEST')
    return expected

def expected_request(original, *, execution_mode, selected_arms, target_lookup):
    result = original()
    declared = {}
    if execution_mode == MODE:
        for arm in selected_arms:
            target = target_lookup(arm)
            if selected(target):
                need(encoded(target) == encoded(qualify_target(target)), 'P03_REPORT_TARGET_QUALIFIED_BEFORE_REQUEST')
                declared[arm] = declaration(target)
    result[FIELD] = declared
    for name in source_names():
        pin = sha((HERE / name).read_bytes())
        need(name not in result['sources'] or result['sources'][name] == pin, 'P03_REPORT_NO_REPLACED_SOURCE_PIN')
        result['sources'][name] = pin
    return result

def source_contract(module):
    value = fact()
    for name, pin in value['frozen_sources'].items():
        need(sha((HERE / name).read_bytes()) == pin, 'P03_REPORT_FROZEN_WHOLE_RUNTIME_SOURCE:' + name)
    for name, expected in value['original_AST'].items():
        actual = {n.name: sha(ast.dump(n, include_attributes=False).encode()) for n in ast.parse((HERE / name).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name in expected}
        need(actual == expected, 'P03_REPORT_WHOLE_ORIGINAL_DRIVER_RETENTION_AND_MONTHLY_AST:' + name)
    need(Path(module.__file__).resolve() == (HERE / 'system_campaign_financial_resume.py').resolve(), 'P03_REPORT_ACTUAL_DRIVER_MODULE')

def active_bounded_context(module):
    import system_campaign_financial_partial as partial
    import system_campaign_financial_uncertainty as legacy
    import system_campaign_bounded_sensor_runtime_v2 as dova
    for fn, name in ((partial.retained_models, 'retained_models'), (partial.model_context, 'model_context'), (module.financial_inputs, 'financial_inputs')):
        target = getattr(fn, '__wrapped__', fn)
        need(target.__module__ == dova.__name__ and target.__code__.co_name == name and (Path(target.__code__.co_filename).resolve() == Path(dova.__file__).resolve()), 'P03_REPORT_ACTUAL_COMPLETE_TYPED_CONTEXT_BINDING:' + name)
    need(legacy.run.__module__ == dova.__name__, 'P03_REPORT_FINANCIAL_THOR_REUSE_NOT_INSTALLED_IN_READONLY')

@contextmanager
def entry_context(module, spec, *, mode, old, request):
    from full_system_core import hosted
    hosted()
    if not selected(spec):
        yield
        return
    request_declaration(spec, request)
    need(mode == 'preflight', 'P03_REPORT_READONLY_PREFLIGHT_ONLY_NO_FINANCIAL_OR_REVIEW_ENTRY')
    source_contract(module)
    active_bounded_context(module)
    from system_campaign_discovery_context import require_strict_checkpoint
    from system_campaign_bounded_sensor_runtime_v2 import reporting_contract
    raw = (Path(old) / spec['selected_checkpoint']).read_bytes()
    need(dict(bytes=len(raw), sha256=sha(raw)) == spec['selected_file'], 'P03_REPORT_ACTUAL_TARGET_GZIP_BYTES')
    cp = require_strict_checkpoint(json.loads(gzip.decompress(raw)))
    need(cp['sha256'] == OUTER and cp['repairs'] == spec['repairs'] and (len(cp['repairs']) == 18), 'P03_REPORT_ACTUAL_UNPROJECTED_FULL17_CHECKPOINT')
    reporting_contract(old, cp, spec)
    yield
