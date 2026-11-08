"""Separately bound future projection using unchanged qualified source logic."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import asdict
import ast
import json
from pathlib import Path
import shutil
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha

HERE = Path(__file__).parent
BINDING = 'system-campaign-own-future-projection.json'
BINDING_SHA = '0398ddba556864a9f8f79ec6c332be83e75fdf4be3c8790ee0628a508ee8993e'
PAYLOAD = 'hydrated-own-future-projection.json'
VIEW = 'derived-own-future-projection.json'
CATALOG = 'research.own-future-projection/catalog/1'
COMPILER = 'research.own-future-projection/adapter/1'
HYDRATED = 'research.own-future-projection/payload/1'
Hex = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class Binding(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.own-future-projection-binding/1'] = Field(alias='schema')
    original_adapter_sha256: Hex
    original_gate_sha256: Hex
    arm: Literal['P07']
    parent_root_admission_sha256: Hex
    bindings: dict[str, str]
    delivered_identity_witness: dict[str, str]


def binding():
    raw = (HERE / BINDING).read_bytes()
    need(sha(raw) == BINDING_SHA, 'OWN_PROJECTION_EXACT_REVIEWED_BINDING_BYTES')
    value = Binding.model_validate_json(raw)
    names = {'OUTER', 'INNER', 'INPUT', 'CUTOVER', 'SID', 'TARGET', 'CORRECT',
             'TARGET_CONTENT', 'CORRECT_CONTENT', 'RETIRED_SUPPRESS', 'RETIRED_ADD', 'PRESERVED_ADD'}
    need(set(value.bindings) == names, 'OWN_PROJECTION_EXACT_BINDING_FIELDS')
    return value


def source_parent():
    from system_campaign_financial_partial import root_spec
    b = binding();spec = root_spec(b.arm, b.parent_root_admission_sha256);v = b.bindings
    need((spec['outer_sha256'], spec['inner_sha256'], spec['input_sha256'], spec['selected_session'])
         == (v['OUTER'], v['INNER'], v['INPUT'], v['CUTOVER']), 'OWN_PROJECTION_SEPARATELY_ADMITTED_SOURCE_PARENT')
    return dict(sha256=spec['outer_sha256'], source_cursor=spec['selected_session'],
        base=deepcopy(spec['base']), repairs=deepcopy(spec['repairs']),
        run=dict(checkpoint_sha256=spec['inner_sha256'], input_sha256=spec['input_sha256']))


def source_logic():
    b = binding();raw = (HERE / 'system_campaign_future_amendment.py').read_bytes()
    need(sha(raw) == b.original_adapter_sha256, 'OWN_PROJECTION_UNCHANGED_ORIGINAL_ADAPTER')
    names = {'documents', 'validate_conflict', 'projection', 'effective_documents'}
    nodes = [deepcopy(n) for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name in names]
    owner, = [deepcopy(n) for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'FutureProjection']
    owner.body = [n for n in owner.body if not isinstance(n, ast.FunctionDef) or n.name != '__init__']
    need(len(nodes) == 4 and {n.name for n in owner.body if isinstance(n, ast.FunctionDef)}
         == {'load', 'apply', '__enter__', '__exit__'}, 'OWN_PROJECTION_EXACT_REUSED_SOURCE_SURFACE')
    namespace = dict(deepcopy=deepcopy, Path=Path, json=json, need=need, save=save, digest=digest, sha=sha,
        CATALOG=CATALOG, COMPILER=COMPILER, HYDRATED=HYDRATED, PAYLOAD_NAME=PAYLOAD,
        OVERLAY_NAME='future-financial-overlay.json', PROJECTION_NAME=VIEW, **b.bindings)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[*nodes, owner], type_ignores=[])),
                 '<unchanged-scoped-future-projection>', 'exec'), namespace)
    return namespace


def references():
    return {CATALOG: BINDING_SHA, COMPILER: sha(Path(__file__).read_bytes())}


def activate_document(document, payload_raw):
    result = deepcopy(document)
    expected = {**references(), HYDRATED: sha(payload_raw)}
    need(not any(v['reference'] in expected for v in result['source_evidence']),
         'OWN_PROJECTION_ACTIVATION_REFERENCES_NOT_PREEXISTING')
    result['source_evidence'].extend(dict(reference=k, sha256=h,
        description='Explicit own-book future projection; all archived input bytes remain unchanged.')
        for k, h in sorted(expected.items()))
    return result


def ordinary_preflight(cp, root, catalog):
    from system_campaign_financial_branches import INPUT, validate_input
    from system_campaign_action_preflight import analyze_new_catalog
    ordinary = [];typed = []
    for entry in cp['repairs']:
        raw = (Path(root) / 'book/repairs' / entry['filename']).read_bytes()
        (typed if json.loads(raw)['schema'] == INPUT else ordinary).append(entry)
    need(cp['sha256'] == binding().bindings['OUTER'] and len(typed) == 1
         and validate_input(Path(root), cp) == typed[0]['sha256'],
         'OWN_PROJECTION_PREFLIGHT_ONLY_EXACT_RETAINED_BRANCH_INPUT')
    report = analyze_new_catalog(dict(cp, repairs=ordinary), root, catalog)
    report['retained_branch_input_sha256'] = typed[0]['sha256']
    return report


def cash_hydration_function():
    import system_campaign_cash_batch as original
    raw = (HERE / 'system_campaign_cash_batch.py').read_bytes()
    prior_raw = (HERE / 'system-campaign-parallel-discovery-request-001.json').read_bytes()
    need(sha(prior_raw) == '863f6c7983fc2cdc1a86bd58a9c4987744d180e8bb56568608eda77d29f85fcd'
         and sha(raw) == json.loads(prior_raw)['sources']['system_campaign_cash_batch.py'],
         'OWN_PROJECTION_UNCHANGED_ORIGINAL_CASH_HYDRATION')
    owner, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'CashBatch']
    node, = [deepcopy(n) for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'hydrate']
    namespace = dict(vars(original), analyze_new_catalog=ordinary_preflight)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 '<unchanged-cash-hydration-with-qualified-typed-preflight>', 'exec'), namespace)
    return namespace['hydrate']


def prepare_overlay(cp, out, arm, document):
    b = binding()
    if arm != b.arm or cp['sha256'] != b.bindings['OUTER']:
        return document
    from system_campaign_cash_batch import CashBatch
    original = source_parent();logic = source_logic()
    need(cp['base'] == original['base'] and cp['repairs'] == original['repairs'],
         'OWN_PROJECTION_EXACT_ORIGINAL_INPUT_HISTORY')
    policy, view = logic['projection'](cp, logic['documents'](out, cp), references())
    cash = CashBatch(json.loads((HERE / 'system-campaign-future-input-amendment-catalog.json').read_bytes()))
    witnesses = cash_hydration_function()(cash, cp, out, out, extra_witnesses=(b.delivered_identity_witness,))
    payload = dict(schema='research.own-future-projection-payload/1', binding_sha256=BINDING_SHA,
        parent_root_admission_sha256=b.parent_root_admission_sha256,
        projection_evidence=references(), policy=policy, derived_projection=view,
        new_patch={k: deepcopy(document[k]) for k in ('suppress', 'add')}, cash_witnesses=witnesses,
        financial_state_changed=False, production_contacted=False)
    path = Path(out) / PAYLOAD
    save(path, payload);save(Path(out) / VIEW, view)
    return activate_document(document, path.read_bytes())


def verify_payload(root):
    root = Path(root);b = binding();raw = (root / PAYLOAD).read_bytes();p = json.loads(raw)
    need(set(p) == {'schema', 'binding_sha256', 'parent_root_admission_sha256', 'projection_evidence',
                    'policy', 'derived_projection', 'new_patch', 'cash_witnesses',
                    'financial_state_changed', 'production_contacted'}
         and p['schema'] == 'research.own-future-projection-payload/1'
         and p['binding_sha256'] == BINDING_SHA and p['parent_root_admission_sha256'] == b.parent_root_admission_sha256
         and p['projection_evidence'] == references()
         and p['financial_state_changed'] is p['production_contacted'] is False,
         'OWN_PROJECTION_EXACT_PAYLOAD_AUTHORITY_AND_SOURCE_REFERENCES')
    parent = source_parent();logic = source_logic();docs = logic['documents'](root, parent)
    policy, view = logic['projection'](parent, docs, references())
    need(p['policy'] == policy and p['derived_projection'] == view
         and json.loads((root / VIEW).read_bytes()) == view, 'OWN_PROJECTION_EXACT_POLICY_AND_DERIVED_VIEW')
    from system_campaign_cash_batch import CashBatch
    from system_campaign_2021_completions_facts import require_witness
    cash = CashBatch(json.loads((HERE / 'system-campaign-future-input-amendment-catalog.json').read_bytes()))
    wanted = {(t['identity_witness']['session'], t['security_id']): t['identity_witness'] for t in cash.catalog['terms']}
    w = b.delivered_identity_witness;wanted[w['session'], w['security_id']] = w
    rows = p['cash_witnesses']['witnesses']
    need(p['cash_witnesses'] == dict(schema='research.factual-cash-batch-private-witnesses/1',
         witnesses=rows, source_metadata_unchanged=True, annual_scans=len({r['session'][:4] for r in rows}),
         requested_events=len(cash.catalog['terms']), auxiliary_witnesses=1),
         'OWN_PROJECTION_UNCHANGED_WITNESS_SCOPE_AND_METADATA')
    need(len(rows) == len(wanted) and {(r['session'], r['security_id']) for r in rows} == set(wanted),
         'OWN_PROJECTION_EXACT_CASH_AND_DELIVERED_WITNESSES')
    for row in rows:
        require_witness(row, wanted[row['session'], row['security_id']])
    cash.rows = {(r['session'], r['security_id']): r for r in rows}
    return p, raw, parent, logic, docs, cash


class OwnProjection:
    def __init__(self, root, overlay_name='future-financial-overlay.json'):
        self.root = Path(root)
        self.payload, self.payload_raw, self.cp, self.logic, self.original_docs, self.cash = verify_payload(self.root)
        self.overlay = self.root / overlay_name;self.overlay_raw = self.overlay.read_bytes();self.activation_sha = sha(self.overlay_raw)
        activation = json.loads(self.overlay_raw);v = binding().bindings
        expected = {**references(), HYDRATED: sha(self.payload_raw)}
        found = [e for e in activation['source_evidence'] if e['reference'] in expected]
        need(len(found) == len(expected) and {e['reference']: e['sha256'] for e in found} == expected
             and activation['predecessor_checkpoint_sha256'] == v['INNER']
             and all(activation[k] == self.payload['new_patch'][k] for k in ('suppress', 'add')),
             'OWN_PROJECTION_EXACT_CANONICAL_ACTIVATION_DOCUMENT')
        self.projection_path = self.root / VIEW
        self.active = False;self.loaded_target = [];self.projected_packets = 0

    def load(self, path, *, resume_session, predecessor_checkpoint_sha256):
        return self.logic['FutureProjection'].load(self, path, resume_session=resume_session,
                                                   predecessor_checkpoint_sha256=predecessor_checkpoint_sha256)

    def apply(self, packet, obj):
        return self.logic['FutureProjection'].apply(self, packet, obj)

    def __enter__(self):
        return self.logic['FutureProjection'].__enter__(self)

    def __exit__(self, *args):
        return self.logic['FutureProjection'].__exit__(self, *args)


def initial_context(cp, root, arm):
    b = binding()
    return OwnProjection(root) if arm == b.arm and cp['sha256'] == b.bindings['OUTER'] else nullcontext()


def review_overlay(cp, evidence, arm, document):
    b = binding()
    if arm != b.arm or cp['sha256'] != b.bindings['OUTER']:
        return document
    payload, raw, _, _, _, _ = verify_payload(evidence)
    need(payload['new_patch'] == {k: document[k] for k in ('suppress', 'add')},
         'OWN_PROJECTION_REVIEW_RECONSTRUCTS_ORIGINAL_NEW_PATCH')
    return activate_document(document, raw)


def retained_activation(root, cp):
    root = Path(root);found = []
    for entry in cp['repairs']:
        raw = (root / 'book/repairs' / entry['filename']).read_bytes()
        need(sha(raw) == entry['sha256'], 'OWN_PROJECTION_RETAINED_INPUT_BYTES')
        document = json.loads(raw)
        if any(e['reference'] == CATALOG for e in document.get('source_evidence', [])):
            found.append(entry)
    if not found:
        need(not (root / PAYLOAD).exists(), 'OWN_PROJECTION_PAYLOAD_REQUIRES_COMMITTED_ACTIVATION')
        return None
    need(len(found) == 1 and cp['source_cursor'] >= binding().bindings['CUTOVER'],
         'OWN_PROJECTION_ONE_COMMITTED_UNCONSUMED_POLICY')
    entry, = found
    projection = OwnProjection(root, 'book/repairs/' + entry['filename'])
    need(entry['resume_session'] == binding().bindings['CUTOVER']
         and entry['predecessor_checkpoint_sha256'] == binding().bindings['INNER'],
         'OWN_PROJECTION_RETAINED_ACTIVATION_BOUNDARY')
    return projection


def preserve(root, cp, out):
    projection = retained_activation(root, cp)
    if projection is None:
        return
    for name in (PAYLOAD, VIEW):
        raw = (Path(root) / name).read_bytes();target = Path(out) / name
        if target.exists():
            need(target.read_bytes() == raw, 'OWN_PROJECTION_RETAINED_PAYLOAD_AND_VIEW_BYTES')
        else:
            target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(raw)


def retained_context(root, cp):
    projection = retained_activation(root, cp)
    return projection if projection is not None else nullcontext()


def branch_loader_owner(loader):
    owner = getattr(loader, '__self__', None)
    if isinstance(owner, OwnProjection):
        need(owner.active, 'OWN_PROJECTION_BRANCH_CODEC_ONLY_AFTER_ACTIVATION')
        return getattr(owner.original_load, '__self__', None)
    return owner


def qualify_initial(projection, out, cp):
    if not isinstance(projection, OwnProjection):
        return
    import system_campaign_amendment_gate as original
    raw = (HERE / 'system_campaign_amendment_gate.py').read_bytes()
    need(sha(raw) == binding().original_gate_sha256, 'OWN_PROJECTION_UNCHANGED_ORIGINAL_CANONICAL_GATE')
    nodes = [deepcopy(n) for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)]
    need({n.name for n in nodes} == {'expect_refusal', 'qualify'}, 'OWN_PROJECTION_EXACT_GATE_SURFACE')
    namespace = dict(vars(original), **binding().bindings)
    namespace.update(validate_conflict=projection.logic['validate_conflict'], projection=projection.logic['projection'])
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 '<unchanged-own-projection-canonical-qualification>', 'exec'), namespace)
    from system_campaign_sprint_facts import PACKET_SOURCE_PATH
    loaded = namespace['qualify'](cp, Path(out), projection.cash, projection, cp['base']['sources'][PACKET_SOURCE_PATH])
    need(loaded.sha256 == projection.activation_sha and projection.projected_packets > 0,
         'OWN_PROJECTION_ACTUAL_QUALIFIED_CANONICAL_ACTIVATION')
