"""Evidence-only admission of a fixed reviewer failure; no replay authorization."""
import ast,hashlib,copy
from pathlib import Path
import pytest
from system_campaign_factual_admit import prove_review_refusal


def example(tmp_path):
    p=tmp_path/'independent-review-stop/worker.log';p.parent.mkdir();p.write_bytes(b'ValueError: REFUSED_LEDGER_SHARES\n')
    spec={'review_refusal':'CONVERSION_IDENTITY_REVIEW','receipt_schema':'research.system-campaign-factual-suffix-receipt/1',
        'review_log_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
        'inspections':{'independent-review-stop/worker-inspect.json':{'exit_code':1}}}
    return spec


@pytest.mark.parametrize('mutation',('hash','success','kind','outcome'))
def test_unproved_reviewer_refusal_cannot_admit(mutation,tmp_path):
    spec=example(tmp_path);prove_review_refusal(spec,{},tmp_path);inventory={}
    if mutation=='hash':spec['review_log_sha256']='0'*64
    elif mutation=='success':inventory['core-review.json']={}
    elif mutation=='kind':spec['review_refusal']='UNKNOWN'
    else:spec['inspections']['independent-review-stop/worker-inspect.json']['exit_code']=0
    with pytest.raises(ValueError,match='REFUSED_'):prove_review_refusal(spec,inventory,tmp_path)


def test_actual_refusal_byte_guard_removal_falsifier(tmp_path):
    spec=example(tmp_path);spec['review_log_sha256']='0'*64
    with pytest.raises(ValueError,match='EXACT_REVIEW_REFUSAL'):prove_review_refusal(spec,{},tmp_path)
    tree=ast.parse(Path(prove_review_refusal.__code__.co_filename).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prove_review_refusal')
    node.body=[n for n in node.body if not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
        and any(isinstance(v,ast.Constant) and v.value=='FACTUAL_EXACT_REVIEW_REFUSAL_BYTES' for v in ast.walk(n)))]
    scope=dict(prove_review_refusal.__globals__)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<removed-refusal-byte-guard>','exec'),scope)
    scope['prove_review_refusal'](spec,{},tmp_path)
