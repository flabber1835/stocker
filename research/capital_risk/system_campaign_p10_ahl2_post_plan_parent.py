"""Authenticate the exact stopped450 Q input and explicit two-root capsule."""
import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

from system_campaign_p10_ahl2_contract import need, sha, digest, HERE, SPEC, specification
from system_campaign_p10_ahl2_parent import admit as admit_own, validate_contents, read_checkpoint, retained_source
from system_campaign_p10_ahl2_context import prior_request as initial_request, frozen_namespace
from system_campaign_p10_ahl2_post_plan import PRIOR, PRIOR_SHA, retained_specification
from system_campaign_p10_ahl2_wire import object_bytes


def inventory_valid(root, inventory):
    root = Path(root)
    paths = list(root.rglob('*'))
    need(not any(p.is_symlink() for p in paths), 'P10_POST_PLAN_NO_INPUT_SYMLINK_OR_FALLBACK')
    actual = {p.relative_to(root).as_posix() for p in paths if p.is_file()}
    need(actual == set(inventory), 'P10_POST_PLAN_FULL_EXACT_RETAINED_Q_INVENTORY')
    for name, entry in inventory.items():
        raw = (root/name).read_bytes()
        need(len(raw) == entry['bytes'] and sha(raw) == entry['sha256'], 'P10_POST_PLAN_RETAINED_MEMBER:'+name)


def validate_retained(root, spec):
    root = Path(root); retained = retained_specification()
    inventory_valid(root, retained['full_inventory'])
    need((root/'request.json').read_bytes() == (HERE/PRIOR).read_bytes()
         and sha((root/'request.json').read_bytes()) == PRIOR_SHA
         and (root/'spec.json').read_bytes() == (HERE/SPEC).read_bytes()
         and sha((root/'source-bindings.json').read_bytes()) == spec['source_binding_sha256'],
         'P10_POST_PLAN_OLD450_REQUEST_SPEC_OWN_SOURCE_DISTINCT_FROM_NEW')
    # Old inspection has its own exact entrypoint; never validate it as new.
    from system_campaign_p10_ahl2_context_job import stopped_record
    inspection = object_bytes((root/'worker-inspect.json').read_bytes())
    stopped_record(inspection,dict(stopped=True,exit_code=1,oom_killed=False,wait_error=None),
                   'qualify',str(retained['run_id']))
    need(inspection['Id'] == retained['inspection']['id'] and inspection['Name'] == retained['inspection']['name'],
         'P10_POST_PLAN_EXACT_AUTHENTICATED_OLD_STOP_IDENTITY')
    need(retained['root_q_only_admission']['status'] == 'ROOT_ACCEPTED_CACHED_CONTROL10_FAST9_FOR_HOSTED_QUALIFICATION_ONLY'
         and retained['root_q_only_admission']['local_Journal_recover_executed'] is False
         and retained['root_q_only_admission']['review_sha256'] == retained['independent_retained_review_sha256'],
         'P10_POST_PLAN_ROOT_Q_ONLY_ADMISSION_NO_LOCAL_RECOVERY_OR_FINANCIAL_AUTHORITY')
    result = {}
    for label, cp_sha, runtime_sha in (
        ('fast','5b9140bb9f438d8eb423b7f606aab081128f3aee870b7deab38e559b7d1c0b65',
         'b6833d7d2c313418e90695e68336a6b2d3fd8641228e04a2496094850d8c2c36'),
        ('old-refusal','6c1f42239d295e679d16e053de28766f85468e936fd3df624236633ecd50044c',
         '68318a079c15f1d1331693f2a7ab2fedf2938fd9509b410fd6110e6a961e2463')):
        branch = root/label
        cp_raw = (branch/'diagnostic-book/discovery-checkpoint.json.gz').read_bytes()
        cp = object_bytes(cp_raw,gzip_declared=True)
        need(sha(cp_raw) == cp_sha and cp_raw == (branch/'diagnostic-book/pre-event/2019-02-15.json.gz').read_bytes()
             and cp['runtime_checkpoint']['checkpoint_sha256'] == runtime_sha
             and cp['source_cursor'] == '2019-02-14' and cp['discovery_transitions'] == 10
             and cp['financial_authority'] is False, 'P10_POST_PLAN_EXACT_COMMITTED_QUALIFIER_PREFIX')
        from system_campaign_anchor_proofs import proof_prefix_evidence
        proof = proof_prefix_evidence(branch,cp['retained_anchor_qualifications'],predecessor=cp['diagnostic_predecessor'])
        need(not proof['committed_proofs'] and proof['full_index']['bytes'] == 0
             and not proof['uncommitted_proof_files'], 'P10_POST_PLAN_ONLY_ACTUAL_EMPTY_PROOF_PREFIX')
        records = [object_bytes(p.read_bytes(),gzip_declared=True,expanded_limit=256*1024**2)
                   for p in sorted((branch/'actual-runtime-path').glob('*.json.gz'))]
        need(len(records) == 10 and records[0]['session'] == '2019-02-04' and records[-1]['session'] == '2019-02-15'
             and all('checkpoint' in r for r in records[:9])
             and records[-1]['prior'] == records[-1]['refused_prior_after_checkpoint'] == cp['runtime_checkpoint']
             and records[-1]['refusal']['committed'] is False
             and records[-1]['refusal']['message'] == ('P10_SENSOR_ACTUAL_CANONICAL_KERNEL_CALLSITE' if label == 'fast'
                                                        else 'REFUSED_VOLATILITY_CAUSAL_AXIS'),
             'P10_POST_PLAN_ALL20_RAW_RECORDS_AND_FAILED_TENTH_NOT_ADOPTED')
        result[label] = dict(checkpoint=cp,records=records)
    need(not (root/'reference').exists(), 'P10_POST_PLAN_REFERENCE_NOT_ALREADY_COMPLETED')
    return result


def capsule_manifest():
    retained = retained_specification()
    return dict(schema='research.p10-two-root-readonly-qualification-capsule/1',
        own1_inventory=specification()['full_inventory'], retained_q_inventory=retained['full_inventory'],
        old_request_sha256=PRIOR_SHA, root_q_only_admission_sha256=retained['root_q_only_admission_sha256'],
        independent_retained_review_sha256=retained['independent_retained_review_sha256'],
        financial_authority=False, fresh_suffix_origin='ORIGINAL_OWN1_ONLY', flat_fallback=False)


def validate_capsule(root, spec):
    root = Path(root)
    need({p.name for p in root.iterdir()} == {'own1','retained-qualification','capsule.json'}
         and not any(p.is_symlink() for p in root.iterdir()), 'P10_POST_PLAN_EXPLICIT_TWO_ROOT_CAPSULE_NO_FLAT_FALLBACK')
    need(object_bytes((root/'capsule.json').read_bytes()) == capsule_manifest(), 'P10_POST_PLAN_CAPSULE_COMPLETE_SOURCE_BOUND_MANIFEST')
    validate_contents(root/'own1',spec)
    validate_retained(root/'retained-qualification',spec)
    return root/'own1',root/'retained-qualification'


def admission_tree():
    import system_campaign_factual_admit as crypto
    body = retained_source(crypto)
    fn, = [n for n in ast.parse(body).body if isinstance(n,ast.FunctionDef) and n.name == 'admit']
    boundary, = [i for i,n in enumerate(fn.body) if isinstance(n,ast.For)
                  and ast.unparse(n.iter) == "spec['inspections'].items()"]
    fn.body = fn.body[:boundary]+ast.parse('validate_retained(dest,specification())\nreturn dest').body
    asset, = [n for n in ast.walk(fn) if isinstance(n,ast.Subscript)
               and ast.unparse(n) == "r['encrypted_output']"]
    asset.slice = ast.Constant('qualification_encrypted_output')
    members, = [n for n in ast.walk(fn) if isinstance(n,ast.Set)
                 and ast.unparse(n) == "{spec['receipt_name'], 'full-core-staging.json', asset['name']}"]
    class Bind(ast.NodeTransformer):
        def visit_Set(self,node):
            return ast.copy_location(ast.parse("set(spec['public_members']) | {asset['name']}",mode='eval').body,node) if node is members else self.generic_visit(node)
    fn = Bind().visit(fn)
    container, = [n for n in fn.body if isinstance(n,ast.With)
                   and ast.unparse(n.items[0].context_expr) == 'zipfile.ZipFile(archive)']
    at, = [i for i,n in enumerate(container.body) if isinstance(n,ast.Assign)
           and ast.unparse(n.targets[0]) == '(header, tag)']
    container.body[at:at] = ast.parse("""
for name,entry in spec['public_members'].items():
    raw_public=z.read(name)
    need(len(raw_public)==entry['bytes'] and hashlib.sha256(raw_public).hexdigest()==entry['sha256'],
         'P10_POST_PLAN_ALL_OLD_PUBLIC_BYTES')
need(r['status']=='PRE_SUFFIX_FAILURE_NO_MUTABLE_EXPORT' and r['qualification_exported'] is True
     and r['encrypted_output_exported'] is False and r['qualification_worker']['stopped'] is True
     and r['qualification_worker']['exit_code']==1 and r['qualification_worker']['oom_killed'] is False
     and r['financial_authority'] is False,'P10_POST_PLAN_OLD_KNOWN_Q_FAILURE_NOT_RELABELLED')
""").body
    return ast.fix_missing_locations(fn)


def admit_retained(root,key):
    import system_campaign_factual_admit as crypto
    scope = dict(vars(crypto),validate_retained=validate_retained,specification=specification)
    exec(compile(ast.Module(body=[admission_tree()],type_ignores=[]),'<p10-post-plan-exact-retained-q-admission>','exec'),scope)
    return scope['admit'](retained_specification(),root,key,max_zip_bytes=1024**3)


def admit_capsule(root,key,spec):
    # Host destination guards execute inside each immutable admission before IO.
    own = admit_own(root,key,spec)
    retained = admit_retained(Path(root).with_name(Path(root).name+'-retained'),key)
    capsule = Path(root).with_name('p10-ahl2-readonly-two-root-capsule')
    capsule.mkdir(mode=0o700)
    shutil.copytree(own,capsule/'own1')
    shutil.copytree(retained,capsule/'retained-qualification')
    (capsule/'capsule.json').write_bytes((json.dumps(capsule_manifest(),sort_keys=True,indent=2)+'\n').encode())
    validate_capsule(capsule,spec)
    for path in capsule.rglob('*'):
        os.chmod(path,0o555 if path.is_dir() else 0o444)
    os.chmod(capsule,0o555)
    return capsule/'own1'
