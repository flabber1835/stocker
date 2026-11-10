"""Independent immutable facts share one image bootstrap, never financial authority."""
from contextlib import redirect_stdout
from copy import deepcopy
import inspect
import io
import json
import textwrap
from types import SimpleNamespace

import pytest

from tests.scripts.test_sentinel_local_delivery_cli import (
    OLD,NEW,OLD_IMAGE,NEW_IMAGE,builder,host_module as hosts,model,
    inputs,fake_host,run_build)  # noqa: F401

IDENTITY=dict(source='1'*64,shadow_config='2'*64,wealth='3'*64)
STRATEGY='4'*64


def probe_host():
    host=object.__new__(hosts.Host)
    host.config=dict(SENTINEL_SHADOW_OBSERVATION_ID='primary',SENTINEL_SHADOW_STARTING_CASH='50000',
        SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY='qualified-policy')
    host.calls=[];host.renders=[];host.output=dict(IDENTITY,strategy=STRATEGY)
    host.load_values=lambda:{}
    def compose(values,*args):
        host.renders.append(deepcopy(host.config))
        return SimpleNamespace(stdout=json.dumps({'services':{'sentinel-shadow':{'environment':host.config}}}).encode())
    def run(command,**kwargs):
        host.calls.append(command)
        value=host.output if 'identity.rehearsal_identity()' in command[command.index('-c')+1] else {'strategy':STRATEGY}
        return SimpleNamespace(stdout=json.dumps(value).encode())
    host.compose=compose;host.run=run
    return host


def test_public_identity_shape_and_two_fewer_workers_for_both_exact_images():
    host=probe_host()
    for commit,image in ((NEW,NEW_IMAGE),(OLD,OLD_IMAGE)):
        assert host.probe(commit,image)==IDENTITY
    assert builder._economic(host,NEW,NEW_IMAGE)==builder._economic(host,OLD,OLD_IMAGE)==STRATEGY
    assert len(host.calls)==2  # Previously two identity plus two economic workers.
    assert len(host.renders)==4  # Reuse still freshly renders the exact semantic configuration.
    assert set(host.probe(NEW,NEW_IMAGE))=={'source','shadow_config','wealth'}


@pytest.mark.parametrize('change',['image','commit','config'])
def test_economic_fact_requires_the_same_immutable_probe_key(change):
    host=probe_host();host.probe(NEW,NEW_IMAGE)
    commit,image=NEW,NEW_IMAGE
    if change=='image':image=OLD_IMAGE
    elif change=='commit':commit=OLD
    else:host.config['SENTINEL_SHADOW_STARTING_CASH']='50001'
    assert builder._economic(host,commit,image)==STRATEGY
    assert len(host.calls)==2 and 'identity.rehearsal_identity()' not in host.calls[-1][-1]


def test_economic_facts_are_private_to_one_host_and_have_a_cold_fallback():
    first=probe_host();second=probe_host()
    first.probe(NEW,NEW_IMAGE)
    assert builder._economic(first,NEW,NEW_IMAGE)==STRATEGY and len(first.calls)==1
    assert builder._economic(second,NEW,NEW_IMAGE)==STRATEGY and len(second.calls)==1
    assert 'identity.rehearsal_identity()' not in second.calls[0][-1]


def test_legacy_complete_identity_never_invents_an_economic_fact():
    host=probe_host();host.output=IDENTITY.copy()
    assert host.probe(NEW,NEW_IMAGE)==IDENTITY
    assert getattr(host,'_image_economic_facts',{})=={}
    assert builder._economic(host,NEW,NEW_IMAGE)==STRATEGY and len(host.calls)==2


@pytest.mark.parametrize('fault',['missing_source','missing_wealth','wrong_strategy','extra_field','failed'])
def test_incomplete_malformed_or_failed_bootstrap_populates_neither_fact_cache(fault):
    host=probe_host()
    if fault=='failed':
        def failed(*args,**kwargs):raise model.DeliveryRefused('private worker failed')
        host.run=failed
    elif fault.startswith('missing_'):host.output.pop(fault.removeprefix('missing_'))
    elif fault=='wrong_strategy':host.output['strategy']=False
    else:host.output['foreign_image']=OLD_IMAGE
    with pytest.raises(model.DeliveryRefused):host.probe(NEW,NEW_IMAGE)
    assert getattr(host,'_image_identity_probes',{})==getattr(host,'_image_economic_facts',{})=={}


@pytest.mark.parametrize('output',[{}, {'strategy':False},{'strategy':'short'},{'strategy':STRATEGY,'foreign':True}])
def test_fallback_economic_worker_requires_its_closed_digest_shape(output):
    host=probe_host();host.run=lambda *args,**kwargs:SimpleNamespace(stdout=json.dumps(output).encode())
    with pytest.raises(model.DeliveryRefused,match='ECONOMIC_PROBE_MALFORMED'):
        builder._economic(host,NEW,NEW_IMAGE)


@pytest.mark.parametrize('commit,image',[('HEAD',NEW_IMAGE),(NEW,'mutable:latest'),(NEW,'repository@'+NEW_IMAGE)])
def test_invalid_economic_subject_refuses_before_cache_or_process(commit,image):
    host=probe_host()
    with pytest.raises(model.DeliveryRefused,match='SUBJECT_INVALID'):builder._economic(host,commit,image)
    assert host.calls==host.renders==[]


def combined_build_host(inputs,monkeypatch,*,drift=False,program_transform=lambda text:text):
    """Execute the actual worker program, with controlled image-local identities."""
    from sentinel import identity,shadow_runtime,strategy
    config=dict(SENTINEL_SHADOW_OBSERVATION_ID='primary',SENTINEL_SHADOW_STARTING_CASH='50000',
        SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY=shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY)
    base=fake_host(inputs)
    class Host(base):
        workers=[]
        probe=hosts.Host.probe
        _probe_inputs=hosts.Host._probe_inputs
        _economic_probe_fact=hosts.Host._economic_probe_fact
        load_values=lambda self:{}
        def compose(self,values,*args):
            return SimpleNamespace(stdout=json.dumps({'services':{'sentinel-shadow':{'environment':config}}}).encode())
        def run(self,command,**kwargs):
            if command[:2]!=['docker','run']:return super().run(command,**kwargs)
            image=command[command.index('--entrypoint')+2]
            code=command[command.index('-c')+1]
            self.workers.append((image,code))
            # This controls only the package's immutable inputs. The actual
            # worker still executes the canonical SHA function independently.
            semantic={'production_rule':'changed' if drift and image==NEW_IMAGE else 'same'}
            with monkeypatch.context() as mp:
                mp.setattr(identity,'rehearsal_identity',lambda:dict(identity_hash='a'*64,
                    environment=dict(compatible=True,wealth_core_source={'hash':'b'*64})))
                mp.setattr(strategy,'production_strategy',lambda:(None,semantic))
                mp.setattr('sys.argv',['private image worker',json.dumps(config)])
                output=io.StringIO()
                with redirect_stdout(output):exec(compile(program_transform(code),'<actual image bootstrap>','exec'),{})
            return SimpleNamespace(stdout=output.getvalue().encode())
    return Host


def test_actual_combined_program_and_builder_keep_both_economic_proofs(inputs,monkeypatch):
    from sentinel.authority import canonical_sha256
    host=combined_build_host(inputs,monkeypatch)
    result,_,_=run_build(inputs,monkeypatch,host_type=host)
    assert len(host.workers)==2 and {image for image,_ in host.workers}=={OLD_IMAGE,NEW_IMAGE}
    assert all('canonical_sha256(production_strategy()[1])' in code for _,code in host.workers)
    assert result['strategy_sha256']==canonical_sha256({'production_rule':'same'})
    assert set(result['source_identity'])=={'source','shadow_config','wealth'}


def test_identical_wealth_does_not_hide_changed_canonical_strategy(inputs,monkeypatch):
    host=combined_build_host(inputs,monkeypatch,drift=True)
    with pytest.raises(model.DeliveryRefused,match='ECONOMIC_RUNTIME_CHANGED'):
        run_build(inputs,monkeypatch,host_type=host)
    assert len(host.workers)==2
    assert not (inputs.folder/'build.json').exists()


def test_substituting_wealth_for_strategy_has_an_executed_falsifier(inputs,monkeypatch):
    def omit(code):
        needle='strategy=canonical_sha256(production_strategy()[1])'
        assert code.count(needle)==1
        return code.replace(needle,"strategy=r['environment']['wealth_core_source']['hash']")
    host=combined_build_host(inputs,monkeypatch,drift=True,program_transform=omit)
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(model.DeliveryRefused,match='ECONOMIC_RUNTIME_CHANGED'):
            run_build(inputs,monkeypatch,host_type=host)


def test_removed_exact_semantic_key_guard_is_detected(monkeypatch):
    text=textwrap.dedent(inspect.getsource(hosts.Host._economic_probe_fact))
    needle='value=facts.get(key)'
    assert text.count(needle)==1
    namespace=dict(vars(hosts));exec(text.replace(needle,'value=next(iter(facts.values()))'),namespace)
    monkeypatch.setattr(hosts.Host,'_economic_probe_fact',namespace['_economic_probe_fact'])
    with pytest.raises(AssertionError):test_economic_fact_requires_the_same_immutable_probe_key('config')
