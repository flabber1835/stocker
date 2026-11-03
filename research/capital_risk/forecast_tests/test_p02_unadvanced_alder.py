"""Exact no-advancement admission metadata; no financial state execution."""
import ast,hashlib,json
from pathlib import Path
import pytest
import system_campaign_factual_admit as module


def fixture(tmp_path):
    sha=lambda b:hashlib.sha256(b).hexdigest()
    selected={'bytes':7,'sha256':'a'*64};journals={n:{'bytes':11,'sha256':'b'*64} for n in ('daily','formation','monthly','watch')}
    spec={'receipt_schema':'research.system-campaign-factual-suffix-receipt/1','unadvanced_receipt_status':'STOPPED_FACTUAL_PREFIX_PRESERVED',
        'selected_file':selected,'unadvanced_original_selected_file':selected,'unadvanced_original_journals':journals,
        'unadvanced_complete_ancestor_zip_sha256':'c'*64,'outer_sha256':'d'*64,'unadvanced_prefix_reviews':{}}
    inventory={'book/checkpoint.json.gz':selected,'lineage/verified-ancestor.zip':{'bytes':19,'sha256':'c'*64},
        **{'book/'+n+'.jsonl':v for n,v in journals.items()}}
    (tmp_path/'lineage').mkdir();(tmp_path/'independent-review-stop').mkdir()
    (tmp_path/'lineage/ancestor.json').write_text(json.dumps({'zip_bytes':19,'zip_sha256':'c'*64}))
    raw=b"facts.qualify(loaded\npacket.session\nAttributeError: 'Packet' object has no attribute 'session'\n"
    review=b'ValueError: REFUSED_FULL_SYSTEM_FACTUAL_EXACT_RECOVERED_TAIL\n'
    (tmp_path/'economic-worker.log').write_bytes(raw);(tmp_path/'independent-review-stop/worker.log').write_bytes(review)
    spec.update(unadvanced_worker_log_sha256=sha(raw),unadvanced_reviewer_log_sha256=sha(review))
    for name in ('old-branch-canonical-review.json','independent-review-stop/core-review.json'):
        raw=json.dumps({'all_prefixes_verified':True,'all_daily_factors_and_chains_verified':True,'checkpoint_sha256':'d'*64,'complete':False}).encode()
        (tmp_path/name).write_bytes(raw);spec['unadvanced_prefix_reviews'][name]=sha(raw)
    return spec,inventory


def test_exact_unadvanced_proof_and_actual_guard_removal(tmp_path):
    spec,inventory=fixture(tmp_path);module.prove_unadvanced_alder_packet(spec,inventory,tmp_path)
    bad={**inventory,'book/daily.jsonl':{'bytes':12,'sha256':'b'*64}}
    with pytest.raises(ValueError,match='NO_FINANCIAL_ADVANCEMENT'):module.prove_unadvanced_alder_packet(spec,bad,tmp_path)
    tree=ast.parse(Path(module.__file__).read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prove_unadvanced_alder_packet')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant) and x.value=='ALDER_PACKET_FAILURE_NO_FINANCIAL_ADVANCEMENT' for x in ast.walk(n))]
    scope=dict(module.__dict__);exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-no-journal-advancement-guard-removed>','exec'),scope)
    scope[node.name](spec,bad,tmp_path)


@pytest.mark.parametrize('name',('book/result.json','book/status.json','alder-input-qualification.json','recovered-tail-proof.json'))
def test_any_financial_entry_evidence_refuses(tmp_path,name):
    spec,inventory=fixture(tmp_path);inventory[name]={'bytes':0,'sha256':'e'*64}
    with pytest.raises(ValueError,match='BEFORE_FINANCIAL_ENTRY'):module.prove_unadvanced_alder_packet(spec,inventory,tmp_path)
