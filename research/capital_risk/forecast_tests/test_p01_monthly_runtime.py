import gzip
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import pytest

CAP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(CAP))
spec=importlib.util.spec_from_file_location('monthly_candidate',CAP/'p01_iac_namespace_continue.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def evidence(tmp_path,monkeypatch):
    book=tmp_path/'book';book.mkdir()
    parent={'sha256':m.OUTER,'completed':697,'stats':{'count':0},'journals':{'daily':{'bytes':0},'monthly':{'bytes':0}}}
    rows=[{'session':day,'comparison_navs':{'pooled':'50000'},'decision':{'target_core_exposure':.5}} for day in ['2020-10-29','2020-10-30']]
    daily=b''.join(m.encoded(row).replace(b'\n',b'')+b'\n' for row in rows)
    reports=[{'session':'2020-10-30','cagr':.1,'slot_retries':{'count':0}}]
    monthly=m.encoded(reports[0]).replace(b'\n',b'')+b'\n'
    (book/'daily.jsonl').write_bytes(daily+b'{"session":"2020-11-02"}\n')
    (book/'monthly.jsonl').write_bytes(monthly)
    source=tmp_path/'monthly.py';source.write_bytes(b'synthetic-source')
    current={'sha256':'b'*64,'completed':699,'source_cursor':'2020-10-30','stats':{'count':2},
             'journals':{'daily':{'bytes':len(daily)},'monthly':{'bytes':len(monthly)}},
             'base':{'sources':{'research/pooled_vacancy_funding/monthly.py':m.sha(source.read_bytes())}}}
    (book/'checkpoint.json.gz').write_bytes(gzip.compress(m.encoded(current)))
    class Stats:
        @classmethod
        def from_dict(cls,value):obj=cls();obj.count=value['count'];return obj
        def advance(self,day,navs,*,core_target,month_end):
            self.count+=1
            return {'session':day,'cagr':.1} if month_end else None
        def to_dict(self):return {'count':self.count}
    for name in ['research','research.pooled_vacancy_funding','research.pooled_vacancy_funding.monthly']:
        module=ModuleType(name);module.__path__=[]
        if name.endswith('.monthly'):module.MonthlyStats=Stats
        monkeypatch.setitem(sys.modules,name,module)
    realpath=Path
    monkeypatch.setattr(m,'Path',lambda value:source if str(value).startswith('/variant/') else realpath(value))
    monkeypatch.setattr(m,'input_origin',lambda *a:parent)
    return tmp_path,current


def test_actual_reporting_function_compares_complete_reports_and_summary(evidence):
    path,cp=evidence;proof=m.monthly_reproduction(path)
    assert proof['passed'] and proof['new_reports']==1 and proof['new_daily_records']==2
    assert proof['financial_transitions_reexecuted']==0


def test_changed_cagr_refuses(evidence):
    path,cp=evidence;file=path/'book/monthly.jsonl'
    raw=file.read_bytes().replace(b'0.1',b'0.2');file.write_bytes(raw)
    with pytest.raises(ValueError,match='REPORTS_AND_FULL_SUMMARY'):m.monthly_reproduction(path)


def test_changed_summary_refuses(evidence):
    path,cp=evidence;cp['stats']['count']=3
    (path/'book/checkpoint.json.gz').write_bytes(gzip.compress(m.encoded(cp)))
    with pytest.raises(ValueError,match='REPORTS_AND_FULL_SUMMARY'):m.monthly_reproduction(path)


def test_changed_monthly_source_refuses(evidence):
    path,cp=evidence;cp['base']['sources']['research/pooled_vacancy_funding/monthly.py']='a'*64
    (path/'book/checkpoint.json.gz').write_bytes(gzip.compress(m.encoded(cp)))
    with pytest.raises(ValueError,match='ACTUAL_FROZEN_SOURCE'):m.monthly_reproduction(path)



@pytest.mark.parametrize('label,passes',[('review',True),('worker',False)])
def test_actual_monthly_inspector_requires_review_role(monkeypatch,label,passes):
    import p01_iac_stopped_review_transport as transport
    from types import SimpleNamespace
    seen=[]
    def fences(value,name,cmd):
        seen.append(cmd)
        return value
    monkeypatch.setattr(transport,'fences',fences)
    monkeypatch.setattr(m,'read',lambda path:{'monthly_review_only':True})
    value={'Id':'a'*64,'Config':{'Labels':{'research.role':label}}}
    monkeypatch.setattr(m.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps([value]).encode()))
    if passes:
        assert m.inspect('capital-system-p01-iac-namespace-review-123-1','a'*64)==value
    else:
        with pytest.raises(ValueError,match='CONTINUE_WORKER_ROLE'):
            m.inspect('capital-system-p01-iac-namespace-review-123-1','a'*64)
    assert seen==[['-B','-u','/driver/p01_iac_namespace_continue.py','--mode','monthly']]
