"""Exact independently admitted P01 own419 parent; never P02 state."""
import ast
import json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha,digest
import system_campaign_factual_admit as crypto

SPEC='system-campaign-p01-discovery-predecessor.json'
SPEC_SHA='9da42e06f7c0b44f85fad5a922340519f6e8db06b679433cf79d9ba12f640ff7'
PATH='lineage/p01-strict-parent-reference.json'
PROVENANCE='system-campaign-p01-original-driver-provenance.json'
PROVENANCE_SHA='5095b00a6bb3bdb9c2643287c34b165a2b7a482e5417d6049768400a1732c467'
SUCCESSORS=frozenset(('system_campaign_factual_admit.py','system_campaign_factual_run.py',
    'system_campaign_basis.py','system_campaign_distribution_run.py'))


def verify_original_drivers(raw,driver=None):
    """Read SHA-bound original code as evidence; never import or execute it."""
    driver=Path(__file__).parent if driver is None else Path(driver)
    encoded=(driver/PROVENANCE).read_bytes()
    need(sha(encoded)==PROVENANCE_SHA,'P01_EXACT_ORIGINAL_DRIVER_PROVENANCE')
    proof=json.loads(encoded);request=json.loads(raw)
    need(proof['schema']=='research.p01-original-driver-provenance/1'
         and proof['arm']=='P01' and proof['original_head']=='74d6359d740080a94b27fcd298fc3210973fa648'
         and proof['evidence_only_never_executed'] is True
         and sha(raw)==proof['original_request_sha256']
         and request['sources']==proof['original_sources'] and len(request['sources'])==78
         and set(proof['successors'])==SUCCESSORS,'P01_EXACT_ORIGINAL78_AND_FOUR_SUCCESSORS')
    for name,original_hash in request['sources'].items():
        current=(driver/name).read_bytes()
        if name not in SUCCESSORS:
            need(sha(current)==original_hash,'P01_ORIGINAL74_UNCHANGED')
            continue
        entry=proof['successors'][name];original=entry['original_source_text'].encode('utf-8')
        need(sha(original)==entry['original_sha256']==original_hash
             and sha(current)==entry['current_sha256'],'P01_EXACT_RETAINED_ORIGINAL_AND_CURRENT_SUCCESSOR')
        old_defs={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(original).body
                  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        new_defs={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(current).body
                  if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
        changed=sorted(n for n in old_defs.keys()|new_defs.keys() if old_defs.get(n)!=new_defs.get(n))
        need(changed==entry['changed_top_level_definitions'],'P01_EXACT_ORCHESTRATION_DEFINITION_CHANGES')
        for protected in entry['protected_unchanged_definitions']:
            need(protected in old_defs and old_defs[protected]==new_defs.get(protected),
                 'P01_CRYPTO_AND_PACKET_QUALIFIER_UNCHANGED')
    return dict(status='ORIGINAL78_PROVENANCE_VERIFIED',unchanged_current_files=74,
        explicitly_retained_original_successors=4,original_code_executed=False,
        provenance_sha256=PROVENANCE_SHA)

def scope(spec):
    need(sha((json.dumps(spec,sort_keys=True,indent=2)+'\n').encode())==SPEC_SHA,
         'P01_DISCOVERY_EXACT_PUBLIC_PARENT')
    need(spec['arm']=='P01' and spec['run_id']==41000113747 and spec['artifact_id']==12953254547
         and spec['head']=='74d6359d740080a94b27fcd298fc3210973fa648'
         and spec['selected_session']=='2019-08-30' and spec['measured_closes']==419
         and len(spec['repairs'])==8
         and spec['outer_sha256']=='84d44463c7288711a97fa8f36fdec0734e0c2a6bf47153494684d5739c599262',
         'P01_DISCOVERY_ONLY_OWN419_NOT_SEPTEMBER_TAIL_OR_OTHER_ARM')
    full=spec['full_client_admission']
    need(full['inventory_members']==77 and full['all_actual_members_verified'] is True
         and full['accounting_snapshots']==1090 and full['committed_months_all_four_series']==20
         and full['diagnostic_cursor_adopted'] is False,'P01_DISCOVERY_INDEPENDENT_STRICT_PREFIX_ADMISSION')
    return spec

def reference(spec):
    scope(spec)
    return dict(schema='research.p01-strict-parent-content-reference/1',arm='P01',
        run_id=spec['run_id'],head=spec['head'],artifact_id=spec['artifact_id'],
        zip_bytes=spec['zip_bytes'],zip_sha256=spec['zip_sha256'],receipt_sha256=spec['receipt_sha256'],
        encrypted_asset_sha256=spec['encrypted_output']['sha256'],
        manifest_sha256=spec['encrypted_output']['manifest_sha256'],selected_file=spec['selected_file'],
        selected_outer_sha256=spec['outer_sha256'],selected_inner_sha256=spec['inner_sha256'],
        selected_state_sha256=spec['state_sha256'],selected_input_sha256=spec['input_sha256'],
        base_sha256=digest(spec['base']),original_eight_repairs_sha256=digest(spec['repairs']),
        selected_journals_sha256=digest(spec['journals']),source_binding_sha256=spec['source_binding_sha256'],
        hosted_review_sha256=spec['review_sha256'],client_admission=spec['full_client_admission'],
        complete_parent_transport_copied_into_new_output=False,production_contacted=False)

def admit(spec,root,key):
    scope(spec)
    need(sha(Path(crypto.__file__).read_bytes())=='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'P01_DISCOVERY_UNCHANGED_COMPLETE_AUTHENTICATOR')
    value=crypto.admit(spec,root,key,max_zip_bytes=512*1024**2)
    verify_original_drivers((value/'request.json').read_bytes())
    return value
