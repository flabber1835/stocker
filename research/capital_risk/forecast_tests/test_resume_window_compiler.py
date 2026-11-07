"""Source/plan representation tests only; never execute canonical functions."""
import hashlib,struct
from decimal import Decimal
from fractions import Fraction
import pytest
from system_campaign_resume_window import plan,source_contract,plain,exact_buffer,Reconstruction

SOURCE=b'def packets(bundle, archive_path, *, first=None, last=None):\n    yield None\n'


def test_existing_bounded_generator_is_checked_without_recompiling_or_running():
    assert source_contract(SOURCE,hashlib.sha256(SOURCE).hexdigest())==hashlib.sha256(SOURCE).hexdigest()
    with pytest.raises(ValueError,match='EXACT_PINNED'):source_contract(SOURCE,'0'*64)
    changed=SOURCE.replace(b'last=None',b'end=None')
    with pytest.raises(ValueError,match='EXISTING_CANONICAL'):source_contract(changed,hashlib.sha256(changed).hexdigest())


def test_exact_window_plan_preserves_absolute_calendar_index():
    axis=[f'{i:05}' for i in range(1400)];p=plan(axis,axis[1348])
    assert p['window']==axis[1049:1349] and len(p['window'])==300
    assert p['initial_index']==1048 and p['initial_index']+300==p['checkpoint_index']==1348
    assert p['original_first']==axis[0] and p['first']==axis[1049] and p['next_session']==axis[1349]


@pytest.mark.parametrize('kind',('duplicate','unsorted','missing','short','final'))
def test_axis_or_cursor_contract_changes_refuse(kind):
    axis=[f'{i:05}' for i in range(500)];cursor=axis[400]
    if kind=='duplicate':axis.append(axis[-1])
    if kind=='unsorted':axis[0],axis[1]=axis[1],axis[0]
    if kind=='missing':cursor='missing'
    if kind=='short':cursor=axis[298]
    if kind=='final':cursor=axis[-1]
    with pytest.raises(ValueError):plan(axis,cursor)


def test_exact_float_bits_and_container_identity_remain_distinct():
    assert plain(0.)!=plain(-0.) and plain((1.,))!=plain([1.])
    assert plain(Decimal('1.00'))!=plain(1.) and plain(Fraction(1,3))=={'Fraction':[1,3]}
    a=struct.unpack('>d',bytes.fromhex('7ff8000000000001'))[0]
    b=struct.unpack('>d',bytes.fromhex('7ff8000000000002'))[0]
    assert plain(a)!=plain(b)
    with pytest.raises(ValueError,match='UNKNOWN_BUFFER_VALUE_TYPE'):plain(object())


def test_buffer_inspection_and_hooks_refuse_locally_before_canonical_import():
    with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):exact_buffer(None)
    axis=[f'{i:05}' for i in range(500)]
    with pytest.raises(ValueError,match='HOSTED_CORE_ONLY'):
        with Reconstruction(axis,axis[400],input_source_sha256='0'*64,adapter_source_sha256='0'*64):pass
