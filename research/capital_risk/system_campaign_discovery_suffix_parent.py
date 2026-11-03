"""Exact stopped diagnostic-prefix admission; no financial state admission."""
import ast
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
from system_campaign_discovery_context import TAINT, CHECKPOINT, digest
from system_campaign_parallel_discovery import compile_body
import system_campaign_factual_admit as crypto
import system_campaign_p02_close_diagnostics as stops

HERE = Path(__file__).parent
ANCHOR_SPEC = 'system-campaign-discovery-suffix-anchor-predecessors.json'
SPINOFF_SPEC = 'system-campaign-discovery-suffix-spinoff-predecessors.json'
PRIOR = 'system-campaign-parallel-discovery-request-001.json'
PRIOR_SHA = '863f6c7983fc2cdc1a86bd58a9c4987744d180e8bb56568608eda77d29f85fcd'
REMAINING_SPEC = 'system-campaign-discovery-suffix-remaining-predecessors.json'
ARMS = ('P03', 'P05', 'P06', 'P07', 'P09', 'P10', 'P11')


def specification(arm):
    need(arm in ARMS, 'SUFFIX_ONLY_OWN_AUTHENTICATED_UNFINISHED_DISCOVERY')
    if arm in ('P09', 'P10', 'P11'):
        value = json.loads((HERE / REMAINING_SPEC).read_bytes())['arms'][arm]
        need(value['arm'] == arm and value['authority'] == TAINT and value['financial_authority'] is False
             and value['cumulative_expected_sessions'] == value['financial_strict_predecessor']['expected_remaining_sessions']
             and value['expected_remaining_sessions'] == value['cumulative_expected_sessions'] - value['transitions']
             and value['strict_parent_outer_sha256'] == value['financial_strict_predecessor']['outer_sha256']
             and value['native_horizon'] == {'P09':1, 'P10':21, 'P11':10}[arm],
             'SUFFIX_EXACT_REVIEWED_REMAINING_OWN_PREFIX_AND_NATIVE_HORIZON')
        return value
    name = ANCHOR_SPEC if arm in ('P03', 'P05') else SPINOFF_SPEC
    value = json.loads((HERE / name).read_bytes())['arms'][arm]
    need(value['arm'] == arm and value['run_id'] == 41353642064
         and value['head'] == 'ec3a08ced74326449554842011a68a879054485a'
         and value['authority'] == TAINT and value['financial_authority'] is False
         and value['cumulative_expected_sessions'] == value['financial_strict_predecessor']['expected_remaining_sessions']
         and value['expected_remaining_sessions'] == value['cumulative_expected_sessions'] - value['transitions']
         and value['strict_parent_outer_sha256'] == value['financial_strict_predecessor']['outer_sha256'],
         'SUFFIX_EXACT_ORIGINAL_OWN_DIAGNOSTIC_AND_DISTINCT_FINANCIAL_PARENTS')
    return value


def exact_source(module):
    need(sha256_file(HERE / PRIOR) == PRIOR_SHA, 'SUFFIX_EXACT_ORIGINAL383_REQUEST')
    raw = Path(module.__file__).read_bytes()
    need(hashlib.sha256(raw).hexdigest() == json.loads((HERE / PRIOR).read_bytes())['sources'][Path(module.__file__).name],
         'SUFFIX_ORIGINAL_AUTHENTICATED_TRANSPORT_SOURCE')
    return raw


def verify_prefix(raw, commitment, *, last=False):
    prefix = raw[:commitment['bytes']]
    need(len(prefix) == commitment['bytes'] and hashlib.sha256(prefix).hexdigest() == commitment['prefix_sha256']
         and (not prefix or prefix.endswith(b'\n')), 'SUFFIX_EXACT_COMMITTED_PREFIX_WITH_RETAINED_UNSENT_TAIL')
    if last:
        lines = prefix.splitlines(keepends=True)
        need((hashlib.sha256(lines[-1]).hexdigest() if lines else None) == commitment['last_record_sha256'],
             'SUFFIX_EXACT_LAST_COMMITTED_JOURNAL_RECORD')
    return prefix


def verify_chain(raw, commitment, *, anchor=False):
    prefix = verify_prefix(raw, commitment)
    chain = digest(dict(authority=TAINT, stream='retained-anchor-events.jsonl')) if anchor else digest(dict(authority=TAINT))
    key = 'record' if anchor else 'event'; rows = []
    for sequence, line in enumerate(prefix.splitlines()):
        value = json.loads(line); record = value[key]
        need(record['sequence'] == sequence and record['authority'] == TAINT, 'SUFFIX_EXACT_EVENT_SEQUENCE_AUTHORITY')
        chain = digest(dict(previous=chain, **{key: record}))
        need(chain == value['chain_sha256'], 'SUFFIX_EXACT_COMMITTED_EVENT_CHAIN')
        rows.append(record)
    need(len(rows) == commitment['rows'] and chain == commitment['chain_sha256'], 'SUFFIX_EXACT_EVENT_ROWS_AND_CHAIN')
    return rows


def validate_checkpoint(cp, spec):
    need(cp['schema'] == spec.get('checkpoint_schema', CHECKPOINT) and cp['authority'] == TAINT and cp['financial_authority'] is False
         and cp['account_performance_computed'] is False
         and cp['strict_parent_outer_sha256'] == spec['strict_parent_outer_sha256']
         and cp['source_cursor'] == spec['selected_session'] and cp['discovery_transitions'] == spec['transitions']
         and cp['journals'] == spec['journals'] and cp['events'] == spec['events']
         and cp['retained_source_anchors'] == spec['retained_source_anchors']
         and cp['event_chain_sha256'] == spec['events']['chain_sha256']
         and cp['transition_chain_sha256'] == spec['transition_chain_sha256'], 'SUFFIX_EXACT_DIAGNOSTIC_CP_NOT_RELABELLED')
    run = cp['runtime_checkpoint']
    if spec['arm'] == 'P10':
        need(cp['sha256'] == digest({k:v for k,v in cp.items() if k != 'sha256'})
             and cp['input_descriptors'] == spec['input_descriptors']
             and cp['diagnostic_input_epoch'] == spec['diagnostic_input_epoch']
             and cp['original_diagnostic_checkpoint_sha256'] == spec['original_diagnostic_checkpoint_sha256']
             and cp['source_binding_sha256'] == spec['source_binding_sha256'],
             'SUFFIX_P10_SAME_EXISTING_FOUR_INPUTS_AND_SINGLE_EPOCH')
    need(digest({k:v for k,v in run.items() if k != 'checkpoint_sha256'}) == run['checkpoint_sha256'] == spec['runtime_checkpoint_sha256']
         and digest(run['state']) == run['state_sha256'] == spec['state_sha256']
         and run['state']['last_processed_session'] == spec['selected_session']
         and run['input_sha256'] == spec['input_sha256'], 'SUFFIX_EXACT_INNER_RUNTIME_STATE_INPUT_BINDINGS')
    return cp


def stopped(value, entry, spec):
    if spec['arm'] in ('P09', 'P10', 'P11'):
        h,c = value['HostConfig'],value['Config']
        need(value['Id'] == entry['id'] and value['Name'] == entry['name']
             and str(spec['run_id']) in value['Name'] and spec['arm'].lower() in value['Name']
             and not value['State']['Running'] and not value['State']['OOMKilled']
             and value['State']['ExitCode'] == entry['metadata']['exit_code'], 'SUFFIX_EXACT_RETAINED_OWN_ACTUAL_STOP')
        need(value['Image'] == 'sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d'
             and h['NetworkMode'] == 'none' and h['Memory'] == h['MemorySwap'] == 8*1024**3
             and h['NanoCpus'] == 2000000000 and h['ReadonlyRootfs'] and h['PidsLimit'] == 64
             and h['CapDrop'] == ['ALL'] and any(x.startswith('no-new-privileges') for x in h['SecurityOpt']),
             'SUFFIX_RETAINED_ACTUAL_OFFLINE_RESOURCE_FENCES')
        mounts = {x['Destination']:x for x in value['Mounts'] if x['Type'] == 'bind'}
        need(sorted(mounts) == entry['mounts'] and mounts['/out']['RW']
             and all(not x['RW'] for n,x in mounts.items() if n != '/out')
             and c['WorkingDir'] == '/variant' and c['Cmd'] == entry['command']
             and not any(x.partition('=')[0] in {'GH_TOKEN','GITHUB_TOKEN',crypto.__dict__.get('SECRET','CAPITAL_RISK_RESEARCH_KEY_20261027')}
                         and x.partition('=')[2] for x in c['Env']), 'SUFFIX_RETAINED_EXACT_ENTRYPOINT_MOUNTS_NO_CREDENTIALS')
        return
    fn, = [n for n in ast.parse(exact_source(stops)).body if isinstance(n, ast.FunctionDef) and n.name == 'stopped']
    names = [n for n in ast.walk(fn) if isinstance(n, ast.Constant) and n.value == '/capital-system-factual-p02-']
    need(len(names) == 1, 'SUFFIX_ONE_OLD_STOP_NAMESPACE_SITE')
    names[0].value = '/capital-system-parallel-discovery-' + spec['arm'].lower() + '-'
    cmd, = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == "c['Cmd']"]
    mode = 'qualify' if entry['role'] == 'qualify' else 'discovery'
    cmd.comparators = [ast.parse(repr(['-B','-u','/driver/system_campaign_parallel_discovery_run.py',
        '--mode',mode,'--arm',spec['arm'],'--spec','/out/spec.json']), mode='eval').body]
    compile_body(fn, vars(stops))(value, entry['metadata'], entry['role'], str(spec['run_id']), PRIOR)
    need(value['Id'] == entry['id'] and value['Name'] == entry['name'], 'SUFFIX_EXACT_OLD_CONTAINER_IDENTITY')


def validate_contents(root, spec, inventory=None):
    root = Path(root)
    if inventory is not None:
        need(len(inventory) == spec['inventory_members'] and digest(inventory) == spec['inventory_sha256'],
             'SUFFIX_COMPLETE_ORIGINAL_AUTHENTICATED_INVENTORY')
    path = root / spec['diagnostic_checkpoint']
    need(path.stat().st_size == spec['checkpoint_bytes'] and sha256_file(path) == spec['diagnostic_checkpoint_sha256'],
         'SUFFIX_EXACT_OLD_COMPRESSED_CP_BYTES')
    cp = validate_checkpoint(json.loads(gzip.decompress(path.read_bytes())), spec)
    for name, entry in spec['full_current_streams'].items():
        data = (root / name).read_bytes()
        need(len(data) == entry['bytes'] and hashlib.sha256(data).hexdigest() == entry['sha256'],
             'SUFFIX_ALL_COMPLETE_OLD_JOURNALS_EVENTS_ANCHORS_AND_UNSENT_TAILS')
    for name, commitment in cp['journals'].items():
        verify_prefix((root / 'diagnostic-book' / (name + '.jsonl')).read_bytes(), commitment, last=True)
    verify_chain((root / 'discovery-events.jsonl').read_bytes(), cp['events'])
    anchors = verify_chain((root / 'retained-anchor-events.jsonl').read_bytes(), cp['retained_source_anchors'], anchor=True)
    need(sha256_file(root / 'source-bindings.json') == spec['source_binding_sha256'],
         'SUFFIX_EXACT_ORIGINAL_SOURCE_BINDINGS')
    for row in anchors:
        need(row['source_sha256'] == digest(spec['financial_strict_predecessor']['base']['sources'])
             and row['input_sha256'] == spec['input_sha256']
             and row['source_anchor_sha256'] == digest(row['source_anchor']), 'SUFFIX_COMMITTED_SOURCE_ANCHORS_SOURCE_INPUT_BOUND')
    if spec['arm'] in ('P09', 'P10', 'P11'):
        proof = spec['original_qualification']; path = root / proof['file']
        need(path.stat().st_size == proof['bytes'] and sha256_file(path) == proof['sha256'],
             'SUFFIX_REUSE_AUTHENTICATED_COMPLETED_OWN_QUALIFICATION_BYTES')
        if spec['arm'] == 'P10':
            for name, entry in spec['epoch_files'].items():
                path = root / name
                need(path.stat().st_size == entry['bytes'] and sha256_file(path) == entry['sha256'],
                     'SUFFIX_P10_EXISTING_RAW_INPUTS_AND_EPOCH_BYTES')
        for name, entry in spec['inspections'].items():
            need(sha256_file(root/name) == entry['sha256'], 'SUFFIX_EXACT_ACTUAL_OLD_STOP_INSPECTION_BYTES')
            stopped(json.loads((root/name).read_bytes()), entry, spec)
        return cp
    qpath = root / 'qualification/discovery-canonical-qualification.json'
    need(sha256_file(qpath) == spec['original_qualification_sha256'], 'SUFFIX_REUSED_ACTUAL_ORIGINAL_CANONICAL_GATE_BYTES')
    proof = json.loads(qpath.read_bytes())
    need(proof['status'] == 'QUALIFIED' and proof['synthetic_canonical_transitions'] == 3
         and proof['strict_parent_outer_sha256'] == spec['strict_parent_outer_sha256']
         and proof['strict_parent_bytes_unchanged'] and proof['actual_strict_checkpoint_rejection']
         and proof['original_runtime_hook_restored'] and not proof['actual_discovery_started'],
         'SUFFIX_REUSE_ONLY_ACTUAL_COMPLETED_OWN_CANONICAL_GATE')
    if spec.get('original_anchor_qualification'):
        entry = spec['original_anchor_qualification']; path = root / 'actual-anchor-qualification.json'
        need(path.stat().st_size == entry['bytes'] and sha256_file(path) == entry['sha256'], 'SUFFIX_ALL_OLD_ANCHOR_PROOF_BYTES')
    for name, entry in spec['inspections'].items():
        need(sha256_file(root / name) == entry['sha256'], 'SUFFIX_EXACT_ACTUAL_OLD_STOP_INSPECTION_BYTES')
        stopped(json.loads((root / name).read_bytes()), entry, spec)
    return cp


def admission_tree():
    fn, = [n for n in ast.parse(exact_source(crypto)).body if isinstance(n, ast.FunctionDef) and n.name == 'admit']
    boundary = [i for i,n in enumerate(fn.body) if isinstance(n, ast.For) and ast.unparse(n.target) == '(n, e)'
                and ast.unparse(n.iter) == "spec['inspections'].items()"]
    need(len(boundary) == 1, 'SUFFIX_ONE_BOUNDARY_BEFORE_FINANCIAL_ADMISSION')
    fn.body = fn.body[:boundary[0]] + ast.parse('validate_contents(dest,spec,inventory)\nreturn dest').body
    sets = [n for n in ast.walk(fn) if isinstance(n, ast.Set) and ast.unparse(n) ==
            "{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
    need(len(sets) == 1, 'SUFFIX_ONE_EXACT_EXPORT_PROBE_PUBLIC_MEMBER_SITE')
    sets[0].elts.append(ast.Constant('export-qualification.json'))
    container, = [n for n in fn.body if isinstance(n, ast.With) and ast.unparse(n.items[0].context_expr) == 'zipfile.ZipFile(archive)']
    i, = [i for i,n in enumerate(container.body) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == '(header, tag)']
    container.body[i:i] = ast.parse("need(hashlib.sha256(z.read('export-qualification.json')).hexdigest()==spec['public_probe_sha256'], 'SUFFIX_ORIGINAL_ACTUAL_EXPORT_PROBE_BYTES')").body
    return ast.fix_missing_locations(fn)


def admit(spec, root, key):
    need(spec == specification(spec['arm']), 'SUFFIX_EXACT_SELECTED_PUBLIC_SPEC')
    if spec['arm'] in ('P09', 'P10', 'P11'):
        tree = admission_tree()
        # Keep the authenticated original download/GCM/streaming extraction;
        # replace only its older archive/member bounds with exact selected ones.
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == 'need' and len(node.args) == 2:
                reason = node.args[1]
                if isinstance(reason, ast.Constant) and reason.value == 'FACTUAL_OLD_ZIP_MEMBERS':
                    node.args[0] = ast.parse('zip_valid(z,spec)', mode='eval').body
                elif isinstance(reason, ast.Constant) and reason.value == 'FACTUAL_PLAINTEXT_BOUND':
                    node.args[0] = ast.parse("len(inventory)==spec['inventory_members'] and sum(v['bytes'] for v in inventory.values())==spec['logical_bytes'] and spec['logical_bytes']<2*1024**3", mode='eval').body
        # P10's export probe has a different public filename, already committed
        # by the complete ZIP descriptor. Do not read the legacy probe filename.
        for node in ast.walk(tree):
            if isinstance(node, ast.With) and ast.unparse(node.items[0].context_expr) == 'zipfile.ZipFile(archive)':
                node.body = [n for n in node.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
                    and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)
                    and n.value.args[1].value == 'SUFFIX_ORIGINAL_ACTUAL_EXPORT_PROBE_BYTES')]
        return compile_body(ast.fix_missing_locations(tree), dict(vars(crypto),validate_contents=validate_contents,
            zip_valid=zip_valid,archive_bound=selected_archive_bound))(spec,root,key,max_zip_bytes=2*1024**3)
    return compile_body(admission_tree(), dict(vars(crypto), validate_contents=validate_contents))(spec, root, key, max_zip_bytes=1024**3)


def selected_archive_bound(spec, limit):
    need(limit == 2*1024**3 and 0 < spec['zip_bytes'] < limit,
         'SUFFIX_EXACT_SELECTED_ARCHIVE_BOUNDED_BELOW_TWO_GIB')


def zip_valid(archive, spec):
    need(len(archive.namelist()) == len(spec['zip_members']) and set(archive.namelist()) == set(spec['zip_members']),
         'SUFFIX_COMPLETE_SELECTED_ZIP_MEMBER_SET')
    for name, entry in spec['zip_members'].items():
        need(archive.getinfo(name).file_size == entry['bytes'], 'SUFFIX_EXACT_SELECTED_ZIP_MEMBER_LENGTH')
        if name == spec['encrypted_output']['name']: continue  # authenticated immediately afterwards
        h = hashlib.sha256()
        with archive.open(name) as stream:
            while raw := stream.read(1024**2): h.update(raw)
        need(h.hexdigest() == entry['sha256'], 'SUFFIX_ALL_OTHER_ZIP_ASSET_BYTES')
    return True
