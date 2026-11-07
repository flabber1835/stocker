"""Exact old P10 stopped evidence admission; no financial-state adoption."""
import ast
from copy import deepcopy
import gzip
import json
from pathlib import Path

from system_campaign_p10_ahl2_contract import (HERE, PRIOR, PRIOR_SHA, CURSOR, POLICY, TAINT,
    digest, sha, need, specification, validate_map, function)
from system_campaign_p10_ahl2_wire import object_bytes


def retained_source(module):
    raw = (HERE / PRIOR).read_bytes()
    need(sha(raw) == PRIOR_SHA, 'P10_EXACT_427_REQUEST_FOR_REUSED_DRIVER')
    sources = json.loads(raw)['sources']
    need(len(sources) == 427, 'P10_ALL427_RETAINED_DRIVER_IDENTITIES')
    path = Path(module.__file__)
    body = path.read_bytes()
    need(sha(body) == sources[path.name], 'P10_EXACT_RETAINED_DRIVER:' + path.name)
    return body


def read_checkpoint(path):
    return object_bytes(Path(path).read_bytes(), gzip_declared=True)


def validate_checkpoint(saved, spec):
    need(saved['schema'] == 'research.disposable-trading-discovery-checkpoint/1'
         and saved['authority'] == TAINT and saved['financial_authority'] is False
         and saved['account_performance_computed'] is False
         and saved['strict_parent_outer_sha256'] == spec['strict_parent_outer_sha256']
         and saved['source_cursor'] == CURSOR and type(saved['discovery_transitions']) is int
         and saved['discovery_transitions'] == 1
         and all(saved[k] == spec[k] for k in ('journals', 'events', 'retained_source_anchors',
             'retained_anchor_qualifications', 'transition_chain_sha256', 'strict_client_admission_sha256')),
         'P10_ONLY_EXACT_COMMITTED_OWN_ONE_TRANSITION_CP')
    cp = saved['runtime_checkpoint']
    need(cp['checkpoint_sha256'] == digest({k:v for k,v in cp.items() if k != 'checkpoint_sha256'})
         == spec['runtime_checkpoint_sha256'] and digest(cp['state']) == cp['state_sha256'] == spec['state_sha256']
         and cp['policy'] == POLICY and cp['input_sha256'] == spec['input_sha256']
         and cp['state']['last_processed_session'] == CURSOR,
         'P10_ORIGINAL_RUNTIME_STATE_POLICY_INPUT_CURSOR')
    return saved


def stopped(value, entry, spec):
    import system_campaign_p02_close_diagnostics as original
    fn = function(retained_source(original), 'stopped')
    sites = [n for n in ast.walk(fn) if isinstance(n, ast.Constant)
             and n.value == '/capital-system-factual-p02-']
    need(len(sites) == 1, 'P10_ONE_OLD_NATIVE_STOP_NAMESPACE_SITE')
    sites[0].value = '/capital-system-parallel-discovery-p10-'
    cmd, = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == "c['Cmd']"]
    mode = 'qualify' if entry['role'] == 'qualify' else 'discovery'
    cmd.comparators = [ast.parse(repr(['-B', '-u', '/driver/system_campaign_volatility_native_run.py',
        '--mode', mode, '--arm', 'P10', '--spec', '/out/spec.json']), mode='eval').body]
    if mode == 'qualify':
        mounts, = [n for n in ast.walk(fn) if isinstance(n, ast.Set)
                   and ast.unparse(n) == "{'/variant', '/frozen', '/driver', '/out', '/old'}"]
        mounts.elts.append(ast.Constant('/previous'))
    scope = dict(vars(original))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<exact-old-p10-stop>', 'exec'), scope)
    metadata = dict(stopped=True, oom_killed=False, exit_code=entry['exit_code'])
    scope['stopped'](value, metadata, entry['role'], str(spec['run_id']), PRIOR)
    need(value['Id'] == entry['id'] and value['Name'] == entry['name']
         and value['Config']['User'].split(':')[0] not in ('', '0', 'root'),
         'P10_EXACT_OLD_STOP_IDENTITY_AND_NONROOT')


def validate_contents(root, spec, inventory=None):
    from system_campaign_discovery_suffix_parent import verify_prefix, verify_chain
    from system_campaign_anchor_proofs import proof_prefix_evidence
    root = Path(root)
    need(spec == specification() and (inventory is None or inventory == spec['full_inventory']),
         'P10_EXACT_OLD_SELECTED_SPEC_AND_FULL_INVENTORY')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual == set(spec['full_inventory']), 'P10_EVERY_ORIGINAL_CP_PROOF_STREAM_AND_TAIL_PRESENT')
    for name, entry in spec['full_inventory'].items():
        raw = (root / name).read_bytes()
        need(len(raw) == entry['bytes'] and sha(raw) == entry['sha256'], 'P10_ALL_OLD_IMMUTABLE_BYTES:' + name)
    need((root / 'request.json').read_bytes() == (HERE / PRIOR).read_bytes()
         and sha((root / 'request.json').read_bytes()) == PRIOR_SHA, 'P10_OLD427_RAW_REQUEST_NO_426_EXCEPTION')
    binding_raw = (root / 'source-bindings.json').read_bytes()
    need(sha(binding_raw) == spec['source_binding_sha256'], 'P10_OWN_ORIGINAL_SOURCE_MAP_NOT_P01')
    validate_map(json.loads(binding_raw), spec)
    strict = read_checkpoint(root / 'strict-parent.json.gz')
    need(strict['sha256'] == spec['strict_parent_outer_sha256']
         and strict['sha256'] == digest({k:v for k,v in strict.items() if k != 'sha256'})
         and strict['base'] == spec['base'] and strict['repairs'] == spec['old_descriptors'],
         'P10_DISTINCT_ORIGINAL_FINANCIAL_PARENT_SOURCE_AND_THREE_DOCUMENTS')
    saved = validate_checkpoint(read_checkpoint(root / spec['diagnostic_checkpoint']), spec)
    for name, commitment in saved['journals'].items():
        verify_prefix((root / 'diagnostic-book' / (name + '.jsonl')).read_bytes(), commitment, last=True)
    verify_chain((root / 'discovery-events.jsonl').read_bytes(), saved['events'])
    verify_chain((root / 'retained-anchor-events.jsonl').read_bytes(), saved['retained_source_anchors'], anchor=True)
    evidence = proof_prefix_evidence(root, saved['retained_anchor_qualifications'])
    need(evidence['committed_proofs'] == [] and evidence['uncommitted_index']['bytes'] == 0
         and not evidence['uncommitted_proof_files'], 'P10_EXACT_ORIGINAL_EMPTY_VERSIONED_PROOF_EPOCH')
    for name, entry in spec['inspections'].items():
        stopped(json.loads((root / name).read_bytes()), entry, spec)
    proof = json.loads((root / 'qualification/discovery-canonical-qualification.json').read_bytes())
    need(proof['status'] == 'QUALIFIED' and proof['synthetic_canonical_transitions'] == 3
         and proof['actual_fast_reference_full_runtime_paths_equal'] is True
         and proof['reference_recomputed'] is False,
         'P10_REUSE_COMPLETED_NATIVE_GATE_NO_REEXECUTION')
    return saved


def admission_tree():
    import system_campaign_factual_admit as crypto
    fn = function(retained_source(crypto), 'admit')
    boundary, = [i for i,n in enumerate(fn.body) if isinstance(n, ast.For)
                  and ast.unparse(n.iter) == "spec['inspections'].items()"]
    fn.body = fn.body[:boundary] + ast.parse('validate_contents(dest,spec,inventory)\nreturn dest').body
    sets = [n for n in ast.walk(fn) if isinstance(n, ast.Set) and ast.unparse(n) ==
            "{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
    need(len(sets) == 1, 'P10_ONE_OLD_ZIP_MEMBER_SCOPE_SITE')
    # Replace only the exact public member collection, preserving all cipher/GCM predicates.
    class Members(ast.NodeTransformer):
        def visit_Set(self, node):
            if node is sets[0]:
                return ast.copy_location(ast.parse("set(spec['public_members']) | {asset['name']}", mode='eval').body, node)
            return self.generic_visit(node)
    fn = Members().visit(fn)
    container, = [n for n in fn.body if isinstance(n, ast.With)
                   and ast.unparse(n.items[0].context_expr) == 'zipfile.ZipFile(archive)']
    at, = [i for i,n in enumerate(container.body) if isinstance(n, ast.Assign)
           and ast.unparse(n.targets[0]) == '(header, tag)']
    container.body[at:at] = ast.parse("""
for name,entry in spec['public_members'].items():
    raw_public=z.read(name)
    need(len(raw_public)==entry['bytes'] and hashlib.sha256(raw_public).hexdigest()==entry['sha256'],
         'P10_ALL_ORIGINAL_PUBLIC_MARKER_PHASE_RECEIPT_STAGING_BYTES')
need(r['status']=='DISCOVERY_REFUSED_KNOWN_STOP' and r['worker']['stopped'] is True
     and r['worker']['exit_code']==1 and r['worker']['oom_killed'] is False
     and r['financial_authority'] is False and r['encrypted_output_exported'] is True,
     'P10_ORIGINAL_KNOWN_FAILURE_NOT_RELABELLED')
""").body
    return ast.fix_missing_locations(fn)


def admit(root, key, spec):
    import system_campaign_factual_admit as crypto
    need(spec == specification(), 'P10_ONLY_EXACT_OWN_SELECTED_ARCHIVE')
    scope = dict(vars(crypto), validate_contents=validate_contents)
    exec(compile(ast.Module(body=[admission_tree()], type_ignores=[]), '<exact-own-p10-admission>', 'exec'), scope)
    return scope['admit'](spec, root, key, max_zip_bytes=1024**3)
