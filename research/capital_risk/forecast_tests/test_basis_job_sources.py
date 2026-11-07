"""The proof request must bind every local Python dependency it imports."""
import ast
from pathlib import Path
from system_campaign_equivalence_job import SOURCES


def dependencies(names):
    root=Path(__file__).parents[1];todo=[n for n in names if n.endswith('.py')];seen=set()
    while todo:
        name=todo.pop()
        if name in seen:continue
        seen.add(name)
        for node in ast.walk(ast.parse((root/name).read_bytes())):
            modules=([node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module and not node.level
                else [n.name.split('.')[0] for n in node.names] if isinstance(node,ast.Import) else [])
            for module in modules:
                target=module+'.py'
                if (root/target).is_file() and target not in seen:todo.append(target)
    return seen


def test_exact_proof_dependency_closure_and_omission_falsifier():
    assert not dependencies(SOURCES)-set(SOURCES)
    broken=tuple(n for n in SOURCES if n!='system_campaign_compare.py')
    assert 'system_campaign_compare.py' in dependencies(broken)-set(broken)
