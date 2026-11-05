"""Separate root authority, immutable stopped bytes and review-view falsifiers."""
import ast
from copy import deepcopy
import io
import gzip
import json
from pathlib import Path
import sys
import zipfile
import pytest


class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('REQUALIFIED_DATA_ONLY:'+fullname)


sys.meta_path.insert(0, Fence())
import system_campaign_financial_requalified_parent as data
import system_campaign_financial_partial as partial


def target():
    p = Path(data.__file__).parent/'system-campaign-financial-partials.json'
    return json.loads(p.read_bytes())['arms']['P07']


def rooted(monkeypatch):
    value = target()
    value.pop(data.quarantine.FLAG)
    value[data.FLAG] = True
    value['qualified_review_transport_sha256'] = data.CATALOG_SHA
    review = data.transport()
    value['root_admission'] = dict(failed_review_requalification=dict(review_transport_sha256=data.CATALOG_SHA,
        original_quarantine_target_sha256=data.QUARANTINE_SHA,core_review_sha256=review['core_review_sha256'],
        branch_review_sha256=review['branch_review_sha256'],independent_validation_sha256='3eb2e4182f5ff02d406d1477be44faedb0c7642c4ee9b21351a6e74ac1b21470',
        independent_review_sha256='dd1a0a1d5deb2fce3181baabecaab738d2c9ad00dacd7c8148b94de67201c533',
        original_failed_stops_preserved=True,financial_transitions_reexecuted=0))
    root_id = 'synthetic-separate-root-authority-DTO'
    value['root_admission_sha256'] = root_id
    monkeypatch.setattr(partial,'validate_root_spec',lambda actual:None if actual.get('root_admission_sha256') == root_id else (_ for _ in ()).throw(ValueError('wrong root')))
    return value


def test_exact_two_artifacts_are_separate_from_root_authority(monkeypatch):
    value = rooted(monkeypatch)
    old, review = data.validated(value)
    assert old == target() and old['prior_stops']['reviewer']['exit_code'] == 1
    assert review['prior_stops']['repair_reviewer']['exit_code'] == 0
    assert data.quarantine.applies(old) and not data.quarantine.applies(value)


def test_actual_root1196_has_separate_authority_and_preserves_initial_policy():
    import system_campaign_financial_additional_sensor as sensor
    spec = partial.root_spec('P07')
    old, review = data.validated(spec)
    phase = sensor.phase(spec)
    assert spec['root_admission_sha256'] == '75e0e1cfee3007e1ff47a638e62597ed49820c1ecc8a7c1cfc7675c9db800719'
    assert phase['adoption_mode'] == 'RETAINED' and phase['proof_rows'] == 742
    assert sensor.retained_origin(phase)['root_admission_sha256'] == data.quarantine.ORIGIN
    assert old == target() and spec['financial_authority'] is False
    path, pin = data.accounting_review(spec)
    assert path == 'stopped-review/core-review.json' and pin == '93cb1130f8ae3016ffc1f8d3698b612e8cec20eaa1ef64527ec5057ea9451300'
    assert pin != spec['review_sha256']  # Original failed-artifact reference is preserved.


def test_preflight_uses_admitted_current_review_and_restoring_old_reference_refuses(tmp_path,monkeypatch):
    import system_campaign_financial_resume as resume
    from research.capital_risk.forecast_tests.test_financial_retention import preflight_fixture
    old,out,spec,calls = preflight_fixture(tmp_path,monkeypatch)
    current = partial.root_spec('P07')
    spec.clear();spec.update(current)
    metadata,_ = resume.actual_parent()
    metadata.update(sha256=spec['outer_sha256'],completed=1196,source_cursor='2022-09-30')
    # Synthetic three-field metadata DTO; never a canonical checkpoint or book.
    (old/'book/checkpoint.json.gz').write_bytes(gzip.compress(json.dumps(metadata).encode()))
    fixture=json.loads((Path(__file__).parent/'fixtures/requalified-review300-protocol-metadata.json').read_bytes())
    raw=data.encoded(fixture['core']);(old/'stopped-review/core-review.json').write_bytes(raw)
    resume.preflight(old,out,spec)
    assert (out/'old-prefix-canonical-review.json').read_bytes()==raw and calls==[]
    monkeypatch.setattr(data,'accounting_review',lambda actual:(partial.review_name(actual),actual['review_sha256']))
    with pytest.raises(ValueError,match='CLOSED_ROOT_ACCOUNTING_REVIEW_BYTES'):resume.preflight(old,out,spec)


@pytest.mark.parametrize('change',['missing_root','old_readonly_flag','unregistered_review','changed_checkpoint',
                                  'changed_original_stop','changed_current_review','changed_DATA','replay','bool_replay','root_id'])
def test_unadmitted_or_foreign_parent_cannot_restore(change,monkeypatch):
    value = rooted(monkeypatch)
    if change == 'missing_root': value.pop('root_admission')
    elif change == 'old_readonly_flag': value[data.quarantine.FLAG] = True
    elif change == 'unregistered_review': value['qualified_review_transport_sha256'] = '0'*64
    elif change == 'changed_checkpoint': value['outer_sha256'] = '0'*64
    elif change == 'changed_original_stop': value['prior_stops']['reviewer']['exit_code'] = 0
    elif change == 'changed_current_review': value['root_admission']['failed_review_requalification']['core_review_sha256'] = '0'*64
    elif change == 'changed_DATA': value['root_admission']['failed_review_requalification']['independent_validation_sha256'] = '0'*64
    elif change == 'replay': value['root_admission']['failed_review_requalification']['financial_transitions_reexecuted'] = 1
    elif change == 'bool_replay': value['root_admission']['failed_review_requalification']['financial_transitions_reexecuted'] = False
    else: value['root_admission_sha256'] = 'foreign'
    with pytest.raises(ValueError): data.validated(value)


def views(tmp_path):
    financial, reviewed = tmp_path/'original',tmp_path/'readonly'
    (financial/'book').mkdir(parents=True);(reviewed/'requalified-review').mkdir(parents=True)
    (financial/'book/checkpoint.json.gz').write_bytes(b'SYNTHETIC_NOT_A_FINANCIAL_CHECKPOINT')
    (financial/'book/daily.jsonl').write_bytes(b'synthetic immutable journal and tail')
    (financial/'uncertainty-certificate-review.json').write_bytes(b'original old proof stays preserved')
    (financial/'stopped-review').mkdir();(financial/'stopped-review/worker.log').write_bytes(b'original failed review')
    fixture = json.loads((Path(__file__).parent/'fixtures/requalified-review300-protocol-metadata.json').read_bytes())
    for name,key in [('core-review.json','core'),('uncertainty-certificate-review.json','branch')]:
        (reviewed/'requalified-review'/name).write_bytes(data.encoded(fixture[key]))
    (reviewed/'failed-review-requalification.json').write_bytes(data.encoded(fixture['proof']))
    return financial,reviewed,tmp_path/'qualified',target(),data.transport()


def test_qualified_view_preserves_original_artifacts_and_every_book_byte(tmp_path):
    args = views(tmp_path);financial,reviewed,view,old,proof = args
    data.qualified_view(*args)
    assert (view/'book/checkpoint.json.gz').read_bytes() == (financial/'book/checkpoint.json.gz').read_bytes()
    assert (view/'stopped-review/worker.log').read_bytes() == b'original failed review'
    assert (financial/'uncertainty-certificate-review.json').read_bytes() == b'original old proof stays preserved'
    provenance = view/'lineage/root-review-requalification'
    assert (provenance/'original-uncertainty-certificate-review.json').read_bytes() == b'original old proof stays preserved'
    assert json.loads((provenance/'receipt.json').read_bytes())['financial_transitions_reexecuted'] == 0


def test_book_guard_removal_really_accepts_copy_corruption(tmp_path,monkeypatch):
    args = views(tmp_path);copy = data.shutil.copytree
    def corrupt(source,destination,*rest,**kwargs):
        result = copy(source,destination,*rest,**kwargs)
        if Path(source) == args[0]: (destination/'book/checkpoint.json.gz').write_bytes(b'changed')
        return result
    monkeypatch.setattr(data.shutil,'copytree',corrupt)
    with pytest.raises(ValueError,match='EVERY_FINANCIAL_BOOK_BYTE_UNCHANGED'): data.qualified_view(*args)
    fn, = [n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='qualified_view']
    class Remove(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and any(isinstance(v,ast.Constant) and v.value=='REQUALIFIED_EVERY_FINANCIAL_BOOK_BYTE_UNCHANGED' for v in node.value.args):return None
            return self.generic_visit(node)
    fn=Remove().visit(fn);scope=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-book-copy-guard>','exec'),scope)
    args = (*args[:2],tmp_path/'corrupt-accepted',*args[3:])
    scope['qualified_view'](*args)
    assert (args[2]/'book/checkpoint.json.gz').read_bytes()==b'changed'


def test_review_crypto_prefix_retains_every_original_authentication_and_stop_statement():
    whole=partial.admission_tree();prefix=data.review_admission_tree()
    assert ast.dump(ast.Module(body=prefix.body[:-1],type_ignores=[]),include_attributes=False)==ast.dump(
        ast.Module(body=whole.body[:len(prefix.body)-1],type_ignores=[]),include_attributes=False)
    assert ast.unparse(prefix.body[-1])=='return dest'
    names={n.value for n in ast.walk(prefix) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
    assert {'FACTUAL_OLD_MANIFEST_HASH','FACTUAL_OLD_MEMBER_HASH','FACTUAL_OLD_COMPLETE_INVENTORY',
            'FACTUAL_OLD_FENCES','FACTUAL_OLD_ACTUAL_STOP','FACTUAL_OLD_INPUT_MOUNTS','FACTUAL_OLD_SOURCE_REVIEW'}<=names


def public_archive(monkeypatch, change):
    spec = data.transport()
    receipt = dict(status=data.STATUS,performance_admitted=False,financial_resume_authorized=False,
        readonly_partial_review=True,readonly_source_witnesses=False,**deepcopy(spec['prior_stops']))
    if change == 'stop': receipt['repair_reviewer']['exit_code'] = 1
    elif change == 'unknown': receipt['repair_reviewer']['stopped'] = False
    elif change == 'oom': receipt['repair_reviewer']['oom_killed'] = True
    elif change == 'finance': receipt['financial_resume_authorized'] = True
    elif change == 'worker': receipt['worker'] = dict(stopped=True,exit_code=0)
    spec['prior_stops'] = {k:deepcopy(receipt[k]) for k in spec['prior_stops']}
    stage = dict(status='STAGING_PASSED',run_id=str(spec['run_id']),source_commit=spec['head'],
        protocol_sha256=partial.PROTOCOL,runtime_image=partial.IMAGE,execution_image=partial.EXECUTION_IMAGE,
        source_files_verified=514,members_verified=591,authenticated_before_parsing=True,offline_image_source_verified=True,
        runtime_index_config_layer_chain_verified=True,replay_started=False)
    marker = dict(status='REAL_SYNTHETIC_ENCRYPTED_EXPORT_ROUNDTRIP_PASSED',arm='P07',financial_sessions_advanced=0,credentials_saved=False)
    values = {spec['receipt_name']:receipt,'full-core-staging.json':stage,'ephemeral-runner-capacity.json':{},
              'resume-export-qualification-P07.json':marker}
    raw = {name:data.encoded(value) for name,value in values.items()}
    spec['public_members'] = {name:dict(bytes=len(value),sha256=data.sha(value)) for name,value in raw.items()}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for name,value in raw.items():archive.writestr(name,value)
        archive.writestr(spec['encrypted_output']['name'],b'SYNTHETIC_NOT_DECRYPTED')
    monkeypatch.setattr(data,'transport',lambda:deepcopy(spec))
    return spec,zipfile.ZipFile(io.BytesIO(stream.getvalue()))


@pytest.mark.parametrize('change',['stop','unknown','oom','finance','worker'])
def test_readonly_review_public_scope_cannot_hide_finance_or_nonzero_stop(monkeypatch,change):
    spec,archive=public_archive(monkeypatch,change)
    with archive,pytest.raises(ValueError,match='POSITIVE_READONLY_ONLY_STOPS'):data.public_names(spec,archive)


def test_positive_stop_guard_removal_really_accepts_failed_reviewer(monkeypatch):
    spec,archive=public_archive(monkeypatch,'stop')
    with pytest.raises(ValueError,match='POSITIVE_READONLY_ONLY_STOPS'):data.public_names(spec,archive)
    fn, = [n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='public_names']
    fn.body=[n for n in fn.body if not(isinstance(n,ast.Expr)and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant)and v.value=='REQUALIFIED_POSITIVE_READONLY_ONLY_STOPS'for v in n.value.args))]
    scope=dict(vars(data));exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-positive-readonly-stop-guard>','exec'),scope)
    with archive:assert scope['public_names'](spec,archive)


@pytest.mark.parametrize('prefix',['research.pooled_','stock_strategy_shared','sentinel','numpy','pandas'])
def test_financial_import_fence(prefix):
    with pytest.raises(ImportError):Fence().find_spec(prefix)
