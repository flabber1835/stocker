"""A semantic negative remains a dated negative while a new subject is checked."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import inspect
import textwrap

import pytest

from sentinel.panel import authority_reader, model, observer_codec, observer_failure
from sentinel.panel.verification_monitor import paper_unknown

NOW=datetime(2026,11,10,14,43,tzinfo=timezone.utc)


def negative_reader(*,detail_size=None):
    state={'key':'a'*64,'tick':0.,'now':NOW}
    reader=authority_reader.Reader(expected_keys=frozenset({'paper_reconciliation'}),
        unknown_factory=paper_unknown,key_factory=lambda *args:state['key'],
        evidence_reader=lambda *args:None,clock=lambda:state['tick'],wall_clock=lambda:state['now'])
    failed=model.paper_reconciliation_row(state='CYCLE_FAILED',cycle_state='SUPERSEDED',
        detail='native cash activity changed; original cycle remains recorded')
    if detail_size is not None:failed=replace(failed,detail='x'*detail_size)
    reader.answer=(state['key'],observer_codec.pack([failed],[],observed_at=NOW),None,NOW)
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert not errors and rows[0].status==model.FAIL
    return reader,state,rows[0]


def test_subject_handoff_keeps_the_completed_negative_without_invented_source_error():
    reader,state,negative=negative_reader()
    state['key']='b'*64
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert errors==[] and len(rows)==1 and rows[0].status==model.FAIL
    assert rows[0].value==negative.value and rows[0].as_of==negative.as_of==NOW
    assert rows[0].valid_until==negative.valid_until and rows[0].freshness==negative.freshness
    assert rows[0].detail.startswith('LAST KNOWN · ')
    assert 'no current positive verification' in rows[0].detail
    assert reader.failure_diagnostic.code=='NEGATIVE_RESULT'


def test_retained_negative_copy_respects_the_existing_financial_wire_bound():
    reader,state,_=negative_reader(detail_size=1000);state['key']='b'*64
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert not errors and rows[0].status==model.FAIL and len(rows[0].detail)==1000
    observer_codec.validate_envelope(observer_codec.pack(rows,errors,observed_at=NOW),{'paper_reconciliation'})


def test_actual_transport_failure_keeps_unknown_source_error_priority():
    reader,state,_=negative_reader();state['key']='b'*64
    reader.read('private',allow_start=False)
    failure=observer_failure.classify(TimeoutError('private transport detail'),transport=True)
    reader.answer=(state['key'],None,failure,NOW)
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert rows[0].status==model.UNKNOWN and errors
    assert reader.failure_diagnostic==failure


def test_subject_identity_failure_cannot_borrow_the_negative_retention_path():
    reader,_,_=negative_reader()
    def broken(*args):raise ValueError('private identity failure')
    reader.key_factory=broken
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert rows[0].status==model.UNKNOWN and errors


def test_original_supersession_exhaustion_remains_explicit_and_finite():
    reader,state,_=negative_reader();state['key']='b'*64
    reader.read('private',allow_start=False)
    state['tick']=observer_failure.SUPERSESSION_SECONDS+1
    state['now']=NOW+timedelta(seconds=state['tick'])
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert rows[0].status==model.UNKNOWN and errors
    assert reader.failure_diagnostic.code=='SUPERSESSION_EXHAUSTED'


def test_completed_success_is_required_to_clear_the_negative():
    reader,state,_=negative_reader();state['key']='b'*64
    reader.read('private',allow_start=False)
    positive=model.Row('paper_reconciliation','Paper','CURRENT',model.OK,as_of=NOW)
    reader.answer=(state['key'],observer_codec.pack([positive],[],observed_at=NOW),None,NOW)
    rows,_,_,errors=reader.read('private',allow_start=False)
    assert rows[0].status==model.OK and not errors
    assert reader.negative_result is None and reader.failure_diagnostic is None


def test_removed_negative_retention_guard_reproduces_the_false_backend_source_failure(monkeypatch):
    code=textwrap.dedent(inspect.getsource(authority_reader.Reader.read))
    guard='and self.negative_result is not None and self.failure_diagnostic is not None'
    assert code.count(guard)==1
    namespace=dict(vars(authority_reader))
    exec(compile(code.replace(guard,'and False and self.failure_diagnostic is not None'),
        '<negative-becomes-source-failure>','exec'),namespace)
    monkeypatch.setattr(authority_reader.Reader,'read',namespace['read'])
    with pytest.raises(AssertionError):
        test_subject_handoff_keeps_the_completed_negative_without_invented_source_error()
