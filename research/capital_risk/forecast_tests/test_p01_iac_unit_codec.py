"""Pure typed-input/arithmetic/stub checks; prices and positions are synthetic."""
from copy import deepcopy
from dataclasses import dataclass,replace
from pathlib import Path
import sys
from types import ModuleType

import pytest

HERE=Path(__file__).parents[1];sys.path.insert(0,str(HERE))
import p01_iac_unit_contract as contract
import p01_iac_unit_codec as codec
from p01_iac_unit_parent import INNER


def row(day,raw='10',signal=None,split='1'):
    return dict(session=day,security_id=contract.SOURCE,raw_close=raw,raw_open='9',
        signal_close=raw if signal is None else signal,split_ratio=split,raw_compatible_volume='99')


def domain(rows):return codec.NativeDomain(rows,contract.facts()['normalizer'])


def test_exact_forward_factor_then_raw_and_pre_event_history_unchanged():
    before=row('2020-06-30');first=row('2020-07-01');second=row('2020-07-02','12')
    native=domain([before,first,second])
    assert native.rows['2020-06-30']==before and '2020-06-30' not in native.days
    assert native.days[first['session']]['logical_signal_close']==10.0*float('2.1584')
    assert native.days[second['session']]['logical_signal_close']==12.0*float('2.1584')
    assert native.days[first['session']]['effective_split_ratio']==float('2.1584')
    assert native.days[second['session']]['effective_split_ratio']==1.0


@pytest.mark.parametrize('rows',[[row('2020-07-02'),row('2020-07-01')],
    [row('2020-07-01'),row('2020-07-01')]])
def test_original_source_csv_order_and_duplicates_never_repaired_by_sorting(rows):
    with pytest.raises(ValueError,match='CSV_ORDER'):domain(rows)


def test_unknown_native_basis_is_recorded_and_blocks_later_basis_without_price_guess():
    native=domain([row('2020-07-01'),row('2020-07-02',signal='11'),row('2020-07-06')])
    assert 'UNKNOWN_NATIVE_SIGNAL_RAW_SPLIT_BASIS' in native.failures['2020-07-02']
    assert native.failures['2020-07-06']=='EARLIER_NATIVE_BASIS_REFUSAL'
    assert '2020-07-02' not in native.days


def test_later_native_split_composes_in_frozen_chronological_order():
    native=domain([row('2020-07-01'),row('2020-07-02',raw='12',signal='24',split='2')])
    item=native.days['2020-07-02'];factor=float('2.1584');factor*=2.0
    assert item['logical_signal_close']==12.0*factor
    assert item['effective_split_ratio']==2.0


def test_parenthesized_published_times_ratio_is_not_assumed_equivalent():
    candidates=[(raw,split) for raw in (1.3,7.1,13.7,23.2,101.3) for split in (1.1,1.3,1.7,3.3)]
    failing=[(raw,split) for raw,split in candidates
        if (raw*split)*float('2.1584')!=raw*(float('2.1584')*split)]
    assert failing
    raw,split=failing[0];a,b=codec.forward(1.0,float('2.1584'),split)
    assert a==split and raw*b!= (raw*a)*float('2.1584')


@dataclass(frozen=True)
class Bar:
    security_id:str=contract.SOURCE
    raw_close:float=10.0
    raw_open:float=9.0
    signal_close:float=10.0
    split_ratio:float=1.0
    volume:int=99


@dataclass(frozen=True)
class Packet:
    day:str
    bars:tuple=()
    meta:dict=None
    spins:tuple=()


def loaded_subject():
    subject=codec.InputCodec.__new__(codec.InputCodec)
    subject.expected=contract.document();subject.objects=[];subject.registered={}
    loaded=subject.load(HERE/contract.INPUT,resume_session='2020-06-30',predecessor_checkpoint_sha256=INNER)
    return subject,loaded


def test_fresh_equivalent_parse_is_bound_to_registered_raw_sha_and_entire_model():
    subject,original=loaded_subject()
    fresh=contract.parse(HERE/contract.INPUT,resume_session='2020-06-30',predecessor_checkpoint_sha256=INNER)
    assert fresh is not original and subject.is_registered(fresh)
    assert subject.apply(Packet('2020-06-30'),fresh).day=='2020-06-30'
    altered=fresh.model_copy(update={'unit_ratio_decimal':'2'})
    assert altered.sha256==fresh.sha256 and not subject.is_registered(altered)
    with pytest.raises(ValueError,match='FULL_MODEL'):subject.apply(Packet('2020-06-30'),altered)
    subject.registered.clear()
    with pytest.raises(ValueError,match='DESCRIPTOR'):subject.apply(Packet('2020-06-30'),fresh)


def test_public_input_raw_bytes_context_and_duplicate_keys_are_strict(tmp_path):
    path=tmp_path/'input.json';path.write_bytes((HERE/contract.INPUT).read_bytes()+b' ')
    with pytest.raises(ValueError,match='RAW_DOCUMENT'):contract.parse(path,resume_session='2020-06-30',predecessor_checkpoint_sha256=INNER)
    subject,loaded=loaded_subject();path.write_bytes(b'{"schema":"x","schema":"y"}')
    with pytest.raises(ValueError,match='DUPLICATE'):subject.load(path,resume_session='2020-06-30',predecessor_checkpoint_sha256=INNER)


def test_apply_preserves_raw_volume_spins_other_ids_and_retains_error_before_advance(monkeypatch):
    subject,loaded=loaded_subject();subject.domain=domain([row('2020-07-01'),row('2020-07-02',signal='11')])
    subject.applied=[];subject.refusals={};subject.control=False;subject.controls=[]
    module=ModuleType('research.bounded_20y.run');module.vendor=lambda value:Bar()
    monkeypatch.setitem(sys.modules,'research.bounded_20y.run',module)
    source=Bar();other=Bar(security_id=contract.CHILD,raw_close=7,signal_close=7)
    packet=Packet('2020-07-01',(source,other),{contract.SOURCE:None},('opaque-native-spin',))
    result=subject.apply(packet,loaded)
    assert result is not packet and result.bars[1] is other and result.spins is packet.spins
    assert result.bars[0].raw_close==source.raw_close and result.bars[0].volume==source.volume
    assert result.bars[0].signal_close==10.0*float('2.1584')
    bad=replace(packet,day='2020-07-02')
    assert subject.apply(bad,deepcopy(loaded)) is bad
    assert subject.refusals[bad.day]['packet_left_unchanged'] is True
    assert subject.refusals[bad.day]['financial_advance_authorized'] is False
