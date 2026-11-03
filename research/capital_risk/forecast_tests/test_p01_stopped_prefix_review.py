"""Source/data/synthetic guards; no canonical runtime or serializer execution."""
import ast
from datetime import date,timedelta
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import p01_iac_namespace_continue as p


def synthetic_axis():
    # A synthetic ordered axis of the same declared size, not a trading calendar.
    days=[];day=date(2018,1,2)
    while day<=date(2026,7,31):
        if day.weekday()<5:days.append(day.isoformat())
        day+=timedelta(days=1)
    extra=len(days)-2156
    return days[:1]+days[extra+1:]


def test_normal_pause_without_result_file_uses_exact_next_source_session():
    axis=synthetic_axis();current=dict(completed=1961,source_cursor=axis[1960])
    assert p.monthly_next_session(current,axis)==axis[1961]
    assert p.monthly_next_session(current,axis,axis[1961])==axis[1961]
    assert p.monthly_next_session(dict(completed=2156,source_cursor=p.END),axis)=='2026-08-03'


@pytest.mark.parametrize('bad',['wrong_count','wrong_cursor','missing_source','wrong_tail','reordered_source'])
def test_normal_pause_does_not_skip_or_invent_a_source_day(bad):
    axis=synthetic_axis();current=dict(completed=1961,source_cursor=axis[1960]);tail=None
    if bad=='wrong_count':current['completed']=1962
    elif bad=='wrong_cursor':current['source_cursor']=axis[1959]
    elif bad=='missing_source':axis.pop(1961)
    elif bad=='wrong_tail':tail=axis[1962]
    else:axis[1961:1963]=reversed(axis[1961:1963])
    with pytest.raises(ValueError):p.monthly_next_session(current,axis,tail)


def test_actual_previous_file_lookup_is_reproduced_and_removed(tmp_path):
    current=dict(completed=1961,source_cursor=synthetic_axis()[1960])
    with pytest.raises(FileNotFoundError):
        following='2026-08-03' if current['source_cursor']==p.END else json.loads((tmp_path/'book/result.json').read_bytes()).get('failed_session')
    assert p.monthly_next_session(current,synthetic_axis())


@pytest.mark.parametrize('mode',['economic','qualify'])
def test_actual_worker_refuses_financial_and_qualification_before_private_imports(monkeypatch,mode):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    monkeypatch.setattr(p,'validate_request',lambda path:None)
    monkeypatch.setattr(p,'read',lambda path:dict(stopped_review_only=True))
    with pytest.raises(ValueError,match='SELECTION_FORBIDS_FINANCE_AND_QUALIFICATION'):p.worker(mode)


def test_finance_falsifier_reaches_sentinel_when_actual_review_only_guard_removed(monkeypatch):
    import full_system_core
    monkeypatch.setattr(full_system_core,'hosted',lambda:None)
    monkeypatch.setattr(p,'validate_request',lambda path:None)
    selected=dict(stopped_review_only=True,financial_predecessor_admitted=True,monthly_review_only=False,
                  repairs=[{}]*13,root_admission_sha256='SYNTHETIC')
    monkeypatch.setattr(p,'read',lambda path:selected)
    module=ModuleType('p01_iac_unit_codec');module.source_rows=lambda **kwargs:([],None)
    monkeypatch.setitem(sys.modules,'p01_iac_unit_codec',module)
    class Sentinel(Exception):pass
    def sentinel(*a,**k):raise Sentinel('SYNTHETIC_FORWARD_CALL_NEVER_EXECUTED')
    monkeypatch.setattr(p,'branch',sentinel)
    fn,=[n for n in ast.parse(Path(p.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='worker']
    fn.body=[n for n in fn.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and len(n.value.args)==2 and isinstance(n.value.args[1],ast.Constant)
        and n.value.args[1].value=='STOPPED_REVIEW_SELECTION_FORBIDS_FINANCE_AND_QUALIFICATION')]
    scope=dict(vars(p));exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual-role-guard-removal-stub-only>','exec'),scope)
    with pytest.raises(Sentinel):scope['worker']('economic')


def test_request_distinguishes_admitted_parent_and_unadmitted_target():
    value=p.expected_request()
    assert value['stopped_review_only'] and not value['financial_resume_authorized']
    assert value['original_sessions']==986 and value['stopped_review_target']['completed']==1961
    assert not value['stopped_review_target']['financial_predecessor_admitted']
    assert value['stopped_review_target']['transport']['original_reviewer']['exit_code']==1
    assert not value['old_qualification_reexecuted']


def test_economic_reviewer_predicates_preserved_from_frozen_published_source():
    # Source-bound old request still identifies the same unchanged review guards;
    # the actual full review only adds a separate target provenance proof.
    source=Path(p.__file__).read_bytes();tree=ast.parse(source)
    fn,=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review']
    reasons={n.args[1].value for n in ast.walk(fn) if isinstance(n,ast.Call) and ast.unparse(n.func)=='need'
             and len(n.args)==2 and isinstance(n.args[1],ast.Constant)}
    assert {'CONTINUE_CURRENT_SOURCE_INPUT_AND_CANONICAL_ROUNDTRIP','CONTINUE_FULL_LEDGER_PREFIX',
        'CONTINUE_EVERY_NEW_DAILY_CHAIN','CONTINUE_FINAL_SUFFIX_CHAIN_AND_ECONOMICS',
        'CONTINUE_EVERY_ORIGINAL_COMMITTED_PREFIX','CONTINUE_OLD_REFUSAL_TAIL_PRESERVED'}<=reasons
    text=ast.unparse(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='host'))
    branch=text[text.index("if request['stopped_review_only']:"):text.index("if request['monthly_review_only']:")]
    assert 'qualification(' not in branch and 'branch(' not in branch
    assert "command(name, 'review'" in branch
