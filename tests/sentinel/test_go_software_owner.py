"""Validation and promotion share signed proof only inside their one GO owner."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import sentinel_go_ci_runtime as runtime
import sentinel_go_promote as promotion
from tests.sentinel.test_ci_certified_paper_installation import (
    verification_owner, COMMIT, RUNTIME, SOURCE, REFERENCE,
)


@pytest.fixture
def go_owner(verification_owner, monkeypatch, tmp_path):
    owner,state,calls=verification_owner
    monkeypatch.setattr(runtime.go_lock,'current_run_token',lambda:'a'*64)
    monkeypatch.setattr(runtime,'_boot_hash',lambda:'b'*64)
    monkeypatch.setattr(runtime,'_certified_pass_count',lambda *a,**k:100)
    monkeypatch.setattr(runtime,'_ensure_exact_image',lambda *a,**k:RUNTIME)
    monkeypatch.setattr(runtime,'_runtime_identity',lambda *a,**k:SOURCE)
    monkeypatch.setattr(runtime,'_write_binding',lambda **k:None)
    monkeypatch.setattr(runtime,'load_binding',lambda **k:dict(certified_image=REFERENCE,
        registry_digest=RUNTIME,local_image_id=RUNTIME))
    inspections=[];pointers=[]
    def inspect(reference):inspections.append(reference);return RUNTIME,COMMIT
    monkeypatch.setattr(promotion.runtime,'_inspect',inspect)
    monkeypatch.setattr(promotion.runtime,'_write_pointer',pointers.append)
    monkeypatch.setattr(runtime.go,'ROOT',tmp_path)
    return owner,state,calls,inspections,pointers


def qualify(go_owner):
    owner,state,calls,inspections,pointers=go_owner
    git=runtime.go.GitIdentity(commit=COMMIT,branch_is_main=True,clean=True,origin_main=COMMIT)
    summary,gate=runtime.certify_from_ci(object(),git=git,now_text='2031-04-21T20:00:00Z',
        run_suite=True,software_verification=owner)
    assert summary.complete and gate.status==runtime.go.PASS
    assert promotion._promote_ci(head=COMMIT,runner=object(),software_verification=owner)==REFERENCE
    assert len(calls)==1 and inspections==[REFERENCE] and pointers==[REFERENCE]


def test_one_go_owner_authenticates_once_and_still_inspects_local_image(go_owner):
    qualify(go_owner)


def test_new_independent_promotion_owner_authenticates_again(go_owner):
    qualify(go_owner)
    assert promotion._promote_ci(head=COMMIT,runner=object())==REFERENCE
    assert len(go_owner[2])==2


def test_context_drift_cannot_consume_prior_signed_proof(go_owner):
    qualify(go_owner)
    owner,state,calls,_,pointers=go_owner
    state['dirty']=' M changed.py'
    with pytest.raises(promotion.runtime.RuntimeSelectionRefused):
        promotion._promote_ci(head=COMMIT,runner=object(),software_verification=owner)
    assert len(calls)==1 and pointers==[REFERENCE]


def test_removed_shared_owner_reintroduces_verification_and_fails_qualification(go_owner,monkeypatch):
    original=promotion._promote_ci
    monkeypatch.setattr(promotion,'_promote_ci',lambda **k:original(head=k['head'],runner=k['runner']))
    with pytest.raises(AssertionError):qualify(go_owner)
