"""The moved sealed-source guard still has its actual recovery falsifier."""
import ast
from pathlib import Path


def test_ready_dataset_falsifier_targets_the_actual_pipeline(capsys):
    script=Path(__file__).with_name('verify_acquisition_recovery_falsifiers.py')
    tree=ast.parse(script.read_bytes(),filename=str(script))
    assignment=next(node for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='cases' for target in node.targets))
    assert isinstance(assignment.value,ast.List)
    selected=[case for case in assignment.value.elts
        if isinstance(case,ast.Tuple) and ast.literal_eval(case.elts[0])=='ready_dataset_repin']
    assert len(selected)==1
    assignment.value.elts=selected
    # Execute the unchanged tool's import/loop/result checks with its one moved
    # guard. The mutant and its real PostgreSQL consumer run in a child pytest;
    # production source files remain unchanged.
    exec(compile(tree,str(script),'exec'),{'__name__':'selected_acquisition_falsifier'})
    output=capsys.readouterr().out
    assert 'KILLED ready_dataset_repin' in output
    assert '1 deliberately broken implementations detected' in output
