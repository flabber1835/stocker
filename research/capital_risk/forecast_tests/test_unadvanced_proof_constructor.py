"""Only the exact unadvanced wrapper refusal may reuse its predecessor."""
import ast,copy,hashlib,json
from pathlib import Path
import pytest
from system_campaign_factual_admit import prove_unadvanced_buffer_constructor


def fixture(tmp_path):
    (tmp_path/'lineage').mkdir();(tmp_path/'independent-review-stop').mkdir()
    raw=b'File "/driver/system_campaign_acceleration.py", line 56, in __enter__\nAttributeError: \'function\' object has no attribute \'prepare\'\n'
    (tmp_path/'economic-worker.log').write_bytes(raw);(tmp_path/'request.json').write_bytes(b'{}')
    meta={'bytes':3,'sha256':'file-sha'}
    journals={n:{'bytes':3,'sha256':n+'-sha'} for n in ('formation','daily','monthly','watch')}
    spec={'receipt_schema':'research.system-campaign-basis-equivalence-receipt/1',
        'unadvanced_receipt_status':'STOPPED_FACTUAL_PREFIX_PRESERVED','selected_file':meta,
        'unadvanced_original_selected_file':meta,'unadvanced_original_journals':journals,
        'unadvanced_complete_ancestor_zip_sha256':'zip-sha','unadvanced_worker_log_sha256':hashlib.sha256(raw).hexdigest(),
        'request_sha256':hashlib.sha256(b'{}').hexdigest(),'outer_sha256':'outer',
        'unadvanced_review_counts':{'formation':11,'daily':0}}
    inventory={'book/checkpoint.json.gz':meta,'lineage/verified-ancestor.zip':{'bytes':123,'sha256':'zip-sha'},
        **{'book/'+n+'.jsonl':v for n,v in journals.items()}}
    files={'lineage/ancestor.json':{'zip_bytes':123,'zip_sha256':'zip-sha'},
        'old-branch-canonical-review.json':{'complete':True,'counts':{'formation':126,'daily':2156},
            'all_prefixes_verified':True,'all_daily_factors_and_chains_verified':True},
        'independent-review-stop/core-review.json':{'checkpoint_sha256':'outer','counts':spec['unadvanced_review_counts'],
            'all_prefixes_verified':True,'all_daily_factors_and_chains_verified':True}}
    for n,v in files.items():(tmp_path/n).write_text(json.dumps(v))
    return spec,inventory


def test_exact_zero_advancement_evidence_and_mutated_full_journal(tmp_path):
    spec,inventory=fixture(tmp_path);prove_unadvanced_buffer_constructor(spec,inventory,tmp_path)
    inventory['book/daily.jsonl']={'bytes':4,'sha256':'changed'}
    with pytest.raises(ValueError,match='NO_FINANCIAL_OR_JOURNAL_ADVANCEMENT'):prove_unadvanced_buffer_constructor(spec,inventory,tmp_path)


def test_any_financial_entry_or_changed_failure_log_refuses(tmp_path):
    spec,inventory=fixture(tmp_path);inventory['book/status.json']={'bytes':1,'sha256':'x'}
    with pytest.raises(ValueError,match='NEVER_ENTERED'):prove_unadvanced_buffer_constructor(spec,inventory,tmp_path)
    inventory.pop('book/status.json');(tmp_path/'economic-worker.log').write_bytes(b'OTHER FAILURE')
    with pytest.raises(ValueError,match='EXACT_PRE_FINANCIAL'):prove_unadvanced_buffer_constructor(spec,inventory,tmp_path)


def test_actual_full_journal_guard_removal_falsifier(tmp_path):
    spec,inventory=fixture(tmp_path);inventory['book/daily.jsonl']={'bytes':4,'sha256':'changed'}
    with pytest.raises(ValueError):prove_unadvanced_buffer_constructor(spec,inventory,tmp_path)
    node=next(n for n in ast.parse(Path(prove_unadvanced_buffer_constructor.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='prove_unadvanced_buffer_constructor')
    node.body=[n for n in node.body if not any(isinstance(x,ast.Constant)
        and x.value=='BUFFER_FAILURE_NO_FINANCIAL_OR_JOURNAL_ADVANCEMENT' for x in ast.walk(n))]
    scope=dict(prove_unadvanced_buffer_constructor.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-unadvanced-byte-guard>','exec'),scope)
    scope['prove_unadvanced_buffer_constructor'](spec,inventory,tmp_path)


def test_actual_recovery_file_stat_and_same_length_hash_mutation(tmp_path):
    from system_campaign_equivalence_job import unadvanced_bytes
    old=tmp_path/'old';failed=tmp_path/'failed'
    for root in (old,failed):
        (root/'book').mkdir(parents=True);(root/'book/checkpoint.json.gz').write_bytes(b'EXACT-SYNTHETIC-CP')
        for name in ('formation','daily','monthly','watch'):(root/'book'/(name+'.jsonl')).write_bytes(b'ORIGINAL')
    spec={'selected_checkpoint':'book/checkpoint.json.gz'}
    unadvanced_bytes(failed,old,spec)
    (failed/'book/daily.jsonl').write_bytes(b'CHANGED!')
    with pytest.raises(ValueError,match='ADVANCED_ZERO_BYTES'):unadvanced_bytes(failed,old,spec)
    node=next(n for n in ast.parse(Path(unadvanced_bytes.__code__.co_filename).read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='unadvanced_bytes')
    node.body=[ast.Pass()];scope=dict(unadvanced_bytes.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<removed-actual-recovery-byte-guard>','exec'),scope)
    scope['unadvanced_bytes'](failed,old,spec)
