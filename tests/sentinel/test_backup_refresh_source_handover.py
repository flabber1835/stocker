"""Backup proof refresh retain the complete installed source and economic map."""
import hashlib
import json
import pytest
from sentinel import runtime_admission as admission, url_selected_source_basis as basis
from tests.support.source_history import expanded_profile, encoded_profile

REVISION='3f7a8eb072cdc661a2800d1a9bf409b687a34f32'
CLOSURE='a7b294d88bdcabf4499ddbb00d07bb4946ed82b086571133cb4c0596c3daeb11'
CHANGED=frozenset(['backup_integrity_reuse.py', 'backup_maintenance_integrity.py', 'backup_runtime_authority.py', 'url_selected_source_basis.py'])


def test_backup_refresh_successor_preserves_every_installed_map():
    profile=basis._profile();assert basis.BACKUP_REFRESH_PREDECESSOR_REVISION==REVISION
    before=profile['retained_predecessors'][REVISION]['files']
    assert len(before)==469 and admission.source_closure(before)==CLOSURE
    actual=profile['retained_predecessors'][basis.BACKUP_MARGIN_PREDECESSOR_REVISION]['files']
    assert set(actual)==set(before)
    assert {n for n in actual if actual[n]!=before.get(n)}==CHANGED
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=before)==before
    assert len(set(profile['retained_predecessors']) - {basis.MARKET_BUY_PREDECESSOR_REVISION, basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION}) == 43 and profile['authority_effect']=='NONE'
    originals={rev:value for rev,value in profile['retained_predecessors'].items()
               if rev not in {REVISION,basis.BACKUP_MARGIN_PREDECESSOR_REVISION,basis.OPENING_STABILITY_PREDECESSOR_REVISION,basis.MARKET_BUY_PREDECESSOR_REVISION, basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION}}
    raw=json.dumps(originals,sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(raw).hexdigest()=='1aa0adbbf956d0bb909ccd809a23f216cdfcdeb6cf23b623cca5c35723a6dccf'


def test_renewal_margin_preserves_the_exact_installed_inventory_and_earlier_history():
    profile = basis._profile()
    revision = '047b3910cbb107fd303d214b4945069bdc688948'
    assert basis.BACKUP_MARGIN_PREDECESSOR_REVISION == revision
    before = profile['retained_predecessors'][revision]['files']
    assert admission.source_closure(before) == '3cd7fe2e6195939cec67a2e459ac542b6b30ba24b0ca7f9226bc4467f43e1726'
    actual = profile['retained_predecessors'][basis.OPENING_STABILITY_PREDECESSOR_REVISION]['files']
    assert set(actual) == set(before)
    assert {name for name in actual if actual[name] != before[name]} == {
        'backup_integrity_reuse.py', 'url_selected_source_basis.py'}
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent), previous=before) == before
    earlier = {key: value for key, value in profile['retained_predecessors'].items() if key not in {revision, basis.OPENING_STABILITY_PREDECESSOR_REVISION,basis.MARKET_BUY_PREDECESSOR_REVISION, basis.CLOSE_RELIABILITY_PREDECESSOR_REVISION}}
    raw = json.dumps(earlier, sort_keys=True, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == '83527a8bd784a676a7d60c8978a3670398259cc32afed3b02d4932537a01d181'


@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_unknown_or_partial_retry_runtime_cannot_translate(fault):
    profile=basis._profile();previous=profile['retained_predecessors'][REVISION]['files']
    actual=admission._source_files(basis.PROFILE.parent)
    if fault=='changed':actual['backup_integrity_reuse.py']='0'*64
    elif fault=='missing':actual.pop('backup_maintenance_integrity.py')
    else:actual['unqualified.py']='0'*64
    assert basis.predecessor_view(actual,previous=previous)==actual


@pytest.mark.parametrize('revision', [REVISION, basis.BACKUP_MARGIN_PREDECESSOR_REVISION])
@pytest.mark.parametrize('fault',['changed','missing','extra'])
def test_independent_predecessor_pin_cannot_be_replaced(tmp_path,monkeypatch,fault,revision):
    profile=expanded_profile();before=profile['retained_predecessors'][revision]
    if fault=='changed':before['files']['backup_integrity_reuse.py']='0'*64
    elif fault=='missing':before['files'].pop('backup_runtime_authority.py')
    else:before['files']['unqualified.py']='0'*64
    before['source_sha256']=basis._closure(before['files'])
    raw=encoded_profile(profile);path=tmp_path/'forged.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path);monkeypatch.setattr(basis,'PROFILE_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError,match='RETAINED_PREDECESSOR_CHANGED'):basis._profile()
