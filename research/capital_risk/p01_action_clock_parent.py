"""Authenticate exact own438 once; reuse its admitted accounting content reference."""
import ast
import gzip
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import digest, sha
from system_campaign_parallel_discovery import compile_body
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE = Path(__file__).parent
SPEC = 'p01_action_clock_predecessor.json'
PRIOR = 'system-campaign-p01-accurate-request-001.json'
PRIOR_SHA = '70cb685834aa55378375978e97fac0d012729aa0586f7f18ea9fede9925aa8f8'


def specification():
    value = json.loads((HERE/SPEC).read_bytes())
    from p01_action_clock_contract import proposal
    proposal(value)
    need(value['schema'] == 'research.p01-admitted-accurate-predecessor/1'
         and value['arm'] == 'P01' and value['run_id'] == 41361011187
         and value['artifact_id'] == 13105356546 and value['selected_session'] == '2019-09-27'
         and value['measured_closes'] == 438 and len(value['repairs']) == 8
         and value['current_tails_zero'] and not value['diagnostic_state_adopted']
         and value['independent_review_sha256'] == '34ccec76f1e6bd247972260f42476271b4a0fca4e6be6e5a6f894331ca22188c',
         'P01_CLOCK_ONLY_INDEPENDENTLY_ADMITTED_OWN438')
    return value


def reference(spec):
    need(spec == specification(), 'P01_CLOCK_EXACT_OWN438_DESCRIPTOR')
    return dict(schema='research.p01-action-clock-parent-reference/1',
        descriptor_sha256=sha256_file(HERE/SPEC), run_id=spec['run_id'], head=spec['head'],
        artifact_id=spec['artifact_id'], zip_sha256=spec['zip_sha256'],
        selected_outer_sha256=spec['outer_sha256'], selected_file=spec['selected_file'],
        selected_inner_sha256=spec['inner_sha256'], selected_state_sha256=spec['state_sha256'],
        selected_input_sha256=spec['input_sha256'], source_binding_sha256=spec['source_binding_sha256'],
        journals_sha256=digest(spec['journals']), repairs_sha256=digest(spec['repairs']),
        admitted_accounting_review_sha256=spec['independent_review_sha256'],
        completed_accounting_audit_repeated=False, financial_authority=False)


def exact_source(module):
    need(sha256_file(HERE/PRIOR) == PRIOR_SHA, 'P01_CLOCK_EXACT402_REQUEST')
    request = json.loads((HERE/PRIOR).read_bytes())
    need(len(request['sources']) == 402 and all(sha256_file(HERE/n) == h
         for n, h in request['sources'].items()), 'P01_CLOCK_ALL402_PRIOR_BYTES_UNCHANGED')
    need(sha256_file(Path(module.__file__)) == request['sources'][Path(module.__file__).name],
         'P01_CLOCK_EXACT_OLD_TRANSPORT_OR_STOP_SOURCE')
    return Path(module.__file__).read_bytes()


def old_stop(value, metadata, role, spec):
    fn, = [n for n in ast.parse(exact_source(stops)).body
           if isinstance(n, ast.FunctionDef) and n.name == 'stopped']
    names = [n for n in ast.walk(fn) if isinstance(n, ast.Constant)
             and n.value == '/capital-system-factual-p02-']
    need(len(names) == 1, 'P01_CLOCK_ONE_OLD_STOP_NAMESPACE_SITE')
    names[0].value = '/capital-system-p01-accurate-'
    cmd, = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == "c['Cmd']"]
    mode = 'review' if role == 'review' else 'economic'
    cmd.comparators = [ast.parse(repr(['-B','-u','/driver/system_campaign_p01_accurate_run.py',
        '--mode',mode,'--spec','/out/spec.json']), mode='eval').body]
    compile_body(fn, vars(stops))(value, metadata, role, str(spec['run_id']), PRIOR)
    expected = spec['actual_stops']['reviewer' if role == 'review' else 'worker']
    need(value['Id'] == expected['id'] and value['State']['ExitCode'] == expected['exit_code'] == 0
         and metadata['exit_code'] == 0, 'P01_CLOCK_EXACT_ACTUAL_SUCCESSFUL_PARENT_STOPS')


def validate_parent(spec, inventory, dest):
    need(spec == specification() and len(inventory) == 56, 'P01_CLOCK_EXACT_OWN438_INVENTORY')
    dest = Path(dest)
    need((dest/'request.json').read_bytes() == (HERE/PRIOR).read_bytes()
         and sha256_file(dest/'source-bindings.json') == spec['source_binding_sha256'],
         'P01_CLOCK_PARENT_SOURCE_AND_REQUEST')
    for role, name in [('worker','worker-inspect.json'), ('review','stopped-review/worker-inspect.json')]:
        metadata = spec['actual_stops']['reviewer' if role == 'review' else 'worker']
        old_stop(json.loads((dest/name).read_bytes()), metadata, role, spec)
    selected = dest/spec['selected_checkpoint']
    need(selected.stat().st_size == spec['selected_file']['bytes']
         and sha256_file(selected) == spec['selected_file']['sha256'], 'P01_CLOCK_SELECTED_GZIP_EXACT')
    cp = json.loads(gzip.decompress(selected.read_bytes()))
    need(cp['sha256'] == spec['outer_sha256'] and cp['run']['checkpoint_sha256'] == spec['inner_sha256']
         and cp['run']['state_sha256'] == spec['state_sha256'] and cp['run']['input_sha256'] == spec['input_sha256']
         and cp['base'] == spec['base'] and cp['journals'] == spec['journals'] and cp['repairs'] == spec['repairs']
         and cp['completed'] == 438 and cp['source_cursor'] == '2019-09-27', 'P01_CLOCK_ALL_SELECTED_BINDINGS')
    for name, entry in cp['journals'].items():
        path = dest/f'book/{name}.jsonl'
        need(path.stat().st_size == entry['bytes'] and sha256_file(path) == entry['prefix_sha256'],
             'P01_CLOCK_EXACT_COMMITTED_PREFIX_NO_TAIL')


def admission_tree():
    fn, = [n for n in ast.parse(exact_source(crypto)).body
           if isinstance(n, ast.FunctionDef) and n.name == 'admit']
    end, = [i for i, n in enumerate(fn.body) if isinstance(n, ast.For)
            and ast.unparse(n.iter) == "spec['inspections'].items()"]
    fn.body = fn.body[:end] + ast.parse('validate_parent(spec, inventory, dest)\nreturn dest').body
    members, = [n for n in ast.walk(fn) if isinstance(n, ast.Set)
                and ast.unparse(n) == "{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
    members.elts.append(ast.Constant('p01-accurate-export-qualification.json'))
    container, = [n for n in fn.body if isinstance(n, ast.With)
                  and ast.unparse(n.items[0].context_expr) == 'zipfile.ZipFile(archive)']
    at, = [i for i, n in enumerate(container.body) if isinstance(n, ast.Assign)
           and ast.unparse(n.targets[0]) == '(header, tag)']
    container.body[at:at] = ast.parse("""
need(r['status']=='ACCURATE_SEGMENT_HOSTED_REVIEW_PASSED_PENDING_CLIENT'
     and r['encrypted_output_exported'] is True, 'P01_CLOCK_SUCCESSFUL_PARENT_EXPORT')
probe_raw=z.read('p01-accurate-export-qualification.json')
need(sha(probe_raw)==r['export_qualification_sha256'], 'P01_CLOCK_EXACT_PARENT_MARKER_BYTES')
probe=json.loads(probe_raw)
need(probe['source_adapter_sha256']==json.loads((HERE/PRIOR).read_bytes())['sources']['system_campaign_p01_accurate_export.py']
     and probe['request_sha256']==spec['request_sha256']
     and probe['status']=='P01_EXPORT_ACTUAL_ENCRYPTED_ROUNDTRIP_QUALIFIED'
     and probe['synthetic_marker_only'] is True and probe['market_or_financial_state_processed'] is False,
     'P01_CLOCK_PARENT_ACTUAL_MARKER_ROUNDTRIP')
""").body
    return ast.fix_missing_locations(fn)


def admit(root, key):
    return compile_body(admission_tree(), dict(vars(crypto), validate_parent=validate_parent,
        HERE=HERE, PRIOR=PRIOR, sha=sha))(specification(), root, key, max_zip_bytes=512*1024**2)
