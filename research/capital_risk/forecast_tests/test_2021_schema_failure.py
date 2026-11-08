"""Exact failed-prefix admission guard; synthetic bytes, no financial execution."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
import system_campaign_factual_admit as module

def fixture(tmp_path):
    root=tmp_path/'evidence';root.mkdir()
    spec=dict(receipt_schema='research.system-p02-uncertainty-suffix-receipt/1',
        unadvanced_failure_kind='COMPLETIONS2021_NULL_CONVERSION_CASH_SCHEMA',
        unadvanced_receipt_status='STOPPED_P02_UNCERTAINTY_PREFIX_PRESERVED',
        run_id=41113691657,head='b64c05cb315f798251f1d82bd8d2909f16a77ade',
        arm='P02',selected_session='2020-12-31',
        outer_sha256='cbca264ce9e9b47f251e21b975d27d489607441ae781a9b562312c974d028a29',inner_sha256='a'*64,
        inspections={'economic-worker-inspect.json':dict(exit_code=1),
                     'independent-review-stop/worker-inspect.json':dict(exit_code=1)})
    inventory={}
    def put(name,value):
        raw=value if isinstance(value,bytes) else json.dumps(value,sort_keys=True).encode()
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        inventory[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        return inventory[name]['sha256']
    put('book/checkpoint.json.gz',b'synthetic checkpoint')
    spec['selected_file']=deepcopy(inventory['book/checkpoint.json.gz'])
    spec['unadvanced_original_selected_file']=deepcopy(spec['selected_file'])
    for n in ('formation','daily','monthly','watch'):put('book/'+n+'.jsonl',('committed '+n+'\nunsent tail').encode())
    spec['unadvanced_original_journals']={n:deepcopy(inventory['book/'+n+'.jsonl']) for n in ('formation','daily','monthly','watch')}
    put('lineage/verified-ancestor.zip',b'exact ancestor')
    put('lineage/ancestor.json',dict(zip_bytes=inventory['lineage/verified-ancestor.zip']['bytes'],zip_sha256=inventory['lineage/verified-ancestor.zip']['sha256']))
    spec['unadvanced_complete_ancestor_zip_sha256']=inventory['lineage/verified-ancestor.zip']['sha256']
    spec['unadvanced_worker_log_sha256']=put('economic-worker.log',b'loaded=facts.overlay(cp,overlay)\nValidationError: 1 validation error for Repair\npure conversion cash must be explicitly null')
    spec['unadvanced_reviewer_log_sha256']=put('independent-review-stop/worker.log',b'REFUSED_FULL_SYSTEM_FACTUAL_EXACT_RECOVERED_TAIL')
    spec['unadvanced_input_overlay_sha256']=put('2021-completions-input-overlay.json',dict(predecessor_checkpoint_sha256=spec['inner_sha256'],add=[dict(kind='CONVERSION',cash_per_share=0.)]))
    spec['unadvanced_hydrated_catalog_sha256']=put('hydrated-2021-completions-terminal-catalog.json',dict(unadopted=True))
    proof=dict(all_prefixes_verified=True,all_daily_factors_and_chains_verified=True,checkpoint_sha256=spec['outer_sha256'],complete=False,counts=dict(formation=126,daily=756))
    spec['unadvanced_prefix_reviews']={n:put(n,proof) for n in ('old-branch-canonical-review.json','independent-review-stop/core-review.json')}
    spec['unadvanced_certificate_review_sha256']=put('old-uncertainty-certificate-review.json',dict(status='COMMITTED_PREFIX_INTERVAL_INVARIANT',checkpoint_sha256=spec['outer_sha256'],through='2020-12-31',rows=302,comparisons=608,financial_path_invariant_over_declared_sensor_interval=True))
    return root,spec,inventory


def test_exact_unadvanced_schema_failure_is_accepted(tmp_path):
    root,spec,inventory=fixture(tmp_path);module.prove_unadvanced(spec,inventory,root)


@pytest.mark.parametrize('mutation',('scope','worker_exit','reviewer_exit','checkpoint','daily_tail','formation','watch','monthly','worker_log','reviewer_log','overlay','hydration','prefix_review','certificate','financial_entry'))
def test_unexpected_identity_progress_or_proof_refuses(tmp_path,mutation):
    root,spec,inventory=fixture(tmp_path)
    if mutation=='scope':spec['run_id']+=1
    elif mutation.endswith('_exit'):
        n='economic-worker-inspect.json' if mutation=='worker_exit' else 'independent-review-stop/worker-inspect.json';spec['inspections'][n]['exit_code']=0
    elif mutation in ('checkpoint','daily_tail','formation','watch','monthly'):
        n='book/checkpoint.json.gz' if mutation=='checkpoint' else 'book/'+('daily' if mutation=='daily_tail' else mutation)+'.jsonl'
        inventory[n]={**inventory[n],'sha256':'0'*64}
    elif mutation=='financial_entry':inventory['book/status.json']=dict(bytes=2,sha256='0'*64)
    else:
        n={'worker_log':'economic-worker.log','reviewer_log':'independent-review-stop/worker.log','overlay':'2021-completions-input-overlay.json','hydration':'hydrated-2021-completions-terminal-catalog.json','prefix_review':'old-branch-canonical-review.json','certificate':'old-uncertainty-certificate-review.json'}[mutation]
        (root/n).write_bytes(b'changed')
    with pytest.raises(ValueError):module.prove_unadvanced(spec,inventory,root)


def test_actual_financial_byte_guard_removal_admits_changed_tail(tmp_path):
    root,spec,inventory=fixture(tmp_path);inventory['book/daily.jsonl']={**inventory['book/daily.jsonl'],'sha256':'0'*64}
    with pytest.raises(ValueError,match='NO_FINANCIAL_ADVANCEMENT'):module.prove_unadvanced_completions_schema(spec,inventory,root)
    tree=ast.parse(Path(module.__file__).read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prove_unadvanced_completions_schema')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='COMPLETIONS2021_SCHEMA_FAILURE_NO_FINANCIAL_ADVANCEMENT' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-guard-removed>','exec'),scope)
    scope[node.name](spec,inventory,root)
