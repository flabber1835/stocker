"""Hosted profile-scoped callbacks around the unchanged qualified account Runtime."""
import hashlib,importlib.util,json,os
from pathlib import Path
from selective_journal import digest

HERE=Path(__file__).resolve().parent
def install(profile):
    if os.environ.get('HOLDING_QUAL_HOSTED')!='1':raise ValueError('REFUSED_LOCAL_SEARCH_RUNTIME')
    spec=importlib.util.spec_from_file_location('private_risk_'+profile.id,HERE/'selective_model.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if profile.family not in ('ORACLE_H0','ORACLE_P2'):
        from risk_policy import step,retention,projection
        original=module.project
        module.step=lambda previous,observations,*,enabled=True:step(profile,previous,observations,enabled=enabled)
        module.retention=lambda states,key:retention(profile,states,key)
        module.project=lambda frame,nav,states,transitions,held_global,execution_session=None:projection(profile,original,frame,nav,states,transitions,held_global,execution_session)
    import selective_screen
    selective_screen.Runtime=module.Runtime
    return module.Runtime

def source_binding(profile,canonical,original_input):
    plan=json.loads((HERE/'selective-protocol.json').read_bytes())
    return dict(schema='research.bounded-risk-account-source/1',profile=profile.model_dump(mode='json'),
        original_financial_protocol_sha256=hashlib.sha256((HERE/'selective-protocol.json').read_bytes()).hexdigest(),
        original_sources={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in plan['account_sources']},
        research_sources={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest() for n in ('risk_profiles.py','risk_policy.py','risk_adapter.py','risk_worker.py')},
        canonical=canonical,original_input=original_input)

def identity(profile,canonical,original_input):return digest(source_binding(profile,canonical,original_input))
