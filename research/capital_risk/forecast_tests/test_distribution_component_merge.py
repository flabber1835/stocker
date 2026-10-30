"""Regression for the actual create-only writer used before any replay."""
import ast,json
from pathlib import Path
import pytest
from system_campaign_distribution_run import merge_components


def components(tmp_path):
    value={'schema':'terminal-repair/1','predecessor_checkpoint_sha256':'a'*64,
           'source_evidence':[{'reference':'distribution'}],'suppress':[],'add':[{'security_id':'D'}]}
    other={**value,'source_evidence':[{'reference':'early'}],'add':[{'security_id':'E'}]}
    a,b=tmp_path/'distribution-input-overlay.json',tmp_path/'early2019-component.json'
    a.write_text(json.dumps(value));b.write_text(json.dumps(other));return a,b


def test_real_create_only_writer_preserves_both_components(tmp_path):
    a,b=components(tmp_path);before=a.read_bytes(),b.read_bytes()
    target=merge_components(a,b,tmp_path);value=json.loads(target.read_bytes())
    assert target not in (a,b) and (a.read_bytes(),b.read_bytes())==before
    assert value['add']==[{'security_id':'D'},{'security_id':'E'}]
    assert value['source_evidence']==[{'reference':'distribution'},{'reference':'early'}]
    with pytest.raises(FileExistsError):merge_components(a,b,tmp_path)
    assert (a.read_bytes(),b.read_bytes())==before


def test_different_own_predecessor_refused_without_new_output(tmp_path):
    a,b=components(tmp_path);value=json.loads(b.read_bytes());value['predecessor_checkpoint_sha256']='b'*64;b.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='SAME_OWN_PREDECESSOR'):merge_components(a,b,tmp_path)
    assert not (tmp_path/'distribution-early2019-input-overlay.json').exists()


def test_actual_old_destination_falsifier(tmp_path):
    a,b=components(tmp_path)
    node=next(n for n in ast.parse(Path(merge_components.__code__.co_filename).read_bytes()).body
              if isinstance(n,ast.FunctionDef) and n.name=='merge_components')
    # Reintroduce the exact old mistake with the real save(open='x') function.
    target=next(n for n in node.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='target' for t in n.targets))
    target.value=ast.Name(id='distribution',ctx=ast.Load())
    node.body=[n for n in node.body if not any(isinstance(v,ast.Constant) and v.value=='DISTRIBUTION_DISJOINT_COMPOUND_DOCUMENT' for v in ast.walk(n))]
    scope=dict(merge_components.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<actual-original-output-destination-bug>','exec'),scope)
    with pytest.raises(FileExistsError):scope['merge_components'](a,b,tmp_path)
