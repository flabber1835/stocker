"""Pure typed-input and source-row guards; no canonical financial execution."""
import ast
from dataclasses import asdict, dataclass
import hashlib
import inspect
import io
import json
from types import SimpleNamespace
import zipfile

import pytest

import system_campaign_chinook_facts as facts
import system_campaign_chinook_input as model


@dataclass(frozen=True)
class Term:
    session: str = model.NATIVE
    security_id: str = model.SID
    cash_per_share: float | None = None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def document():
    return dict(schema=model.SCHEMA, predecessor_checkpoint_sha256='a' * 64,
        native_session=model.NATIVE, session=model.DAY, security_id=model.SID,
        native_term_sha256=digest(asdict(Term())), sensor_only=True,
        require_unowned_and_unordered=True,
        consideration_range='40<=cash_plus_nontransferable_right<=44',
        treatment='RECALENDAR_INCOMPLETE_TERM_AND_CERTIFY_ALL_COMPARISONS',
        source_evidence=[dict(reference=f'test:{n}', description='metadata fixture',
                             sha256=str(n) * 64) for n in range(6)])


def parse(tmp_path, doc=None, **changed):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document() if doc is None else doc), encoding='utf8')
    kwargs = dict(resume_session='2023-07-31', predecessor_checkpoint_sha256='a' * 64,
        expected_evidence=document()['source_evidence'], native_sha256=digest(asdict(Term())))
    kwargs.update(changed)
    return model.parse(path, **kwargs)


def test_distinct_type_retains_the_original_incomplete_term_boundary(tmp_path):
    value = parse(tmp_path)
    assert value.earliest_affected_session == '2023-08-10'
    assert value.session == '2023-08-11' and value.sha256
    assert not hasattr(value, 'cash_per_share') and not hasattr(value, 'add')


@pytest.mark.parametrize('change', [{'sensor_only': False}, {'sensor_only': 1},
    {'require_unowned_and_unordered': False}, {'security_id': 'OTHER'},
    {'native_session': model.DAY}, {'session': '2023-08-14'},
    {'cash_per_share': 40.0}, {'consideration_range': '40<=cash_plus_nontransferable_right<=40'},
    {'native_term_sha256': '0' * 64}])
def test_foreign_scope_cash_relabel_or_truncated_right_refuses(tmp_path, change):
    with pytest.raises(ValueError):
        parse(tmp_path, {**document(), **change})


def test_consumed_wrong_predecessor_and_wrong_source_refuse(tmp_path):
    for changed in [dict(resume_session=model.NATIVE),
                    dict(predecessor_checkpoint_sha256='b' * 64),
                    dict(expected_evidence=[])]:
        with pytest.raises(ValueError):
            parse(tmp_path, **changed)


def test_actual_predecessor_guard_removal_falsifier(tmp_path):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(document()), encoding='utf8')
    kwargs = dict(resume_session='2023-07-31', predecessor_checkpoint_sha256='b' * 64,
        expected_evidence=document()['source_evidence'], native_sha256=digest(asdict(Term())))
    with pytest.raises(ValueError, match='EXACT_OWN_PREDECESSOR'):
        model.parse(path, **kwargs)
    raw = inspect.getsource(model.parse)
    broken = raw.replace('obj.predecessor_checkpoint_sha256==predecessor_checkpoint_sha256', 'True')
    assert broken != raw
    ns = dict(vars(model))
    exec(broken, ns)
    ns['parse'](path, **kwargs)


def test_position_pending_scope_and_actual_guard_removal():
    empty = SimpleNamespace(wealth_core={'episodes': {}}, pending=[])
    model.require_no_position(empty)
    owned = SimpleNamespace(wealth_core={'episodes': {'x': {'security_id': model.SID}}}, pending=[])
    pending = SimpleNamespace(wealth_core={'episodes': {}}, pending=[{'security_id': model.SID}])
    for value in (owned, pending):
        with pytest.raises(ValueError, match='MUST_NOT_BE_'):
            model.require_no_position(value)
    raw = inspect.getsource(model.require_no_position)
    broken = raw.replace("and v['security_id']!=SID for v in episodes.values()", 'for v in episodes.values()')
    assert broken != raw
    ns = dict(vars(model))
    exec(broken, ns)
    ns['require_no_position'](owned)


def test_inverse_provider_row_is_not_omitted_and_guard_removal_is_detected():
    csv = ('date,action,ticker,name,value,contraticker,contraname\n'
           '2023-08-10,acquisitionof,NVS,NOVARTIS,1,KDNY,CHINOOK\n'
           '2023-08-10,acquisitionby,KDNY,CHINOOK,1,NVS,NOVARTIS\n'
           '2023-08-10,delisted,KDNY,CHINOOK,1,N/A,N/A\n')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('actions.csv', csv)
    raw = buffer.getvalue()
    rows = facts.provider_rows(raw)
    assert len(rows) == 3 and rows[0]['action'] == 'acquisitionof'
    omitted = rows[1:]
    wrong = dict(provider_archive_sha256=hashlib.sha256(raw).hexdigest(),
        provider_rows_sha256=digest(omitted), provider_row_sha256=[digest(r) for r in omitted])
    with pytest.raises(ValueError, match='ALL_ORIGINAL_PROVIDER_ROWS'):
        facts.verify_provider_rows(raw, wrong)
    fn, = [n for n in ast.parse(inspect.getsource(facts.verify_provider_rows)).body
           if isinstance(n, ast.FunctionDef)]
    fn.body = [n for n in fn.body if not (isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call) and len(n.value.args) == 2
        and isinstance(n.value.args[1], ast.Constant)
        and n.value.args[1].value == 'CHINOOK_ALL_ORIGINAL_PROVIDER_ROWS')]
    ns = dict(vars(facts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-provider-guard-removed>', 'exec'), ns)
    assert ns['verify_provider_rows'](raw, wrong) == rows
