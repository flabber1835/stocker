"""Construct a source-pinned disposable application runtime for the research lab."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from . import authority as a

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_once(path, before, after):
    text = path.read_text()
    if text.count(before) != 1:
        raise ValueError(f"staging source seam differs: {path.name}: {before[:70]}")
    path.write_text(text.replace(before, after, 1))


def extract_controllers(source: Path, output: Path):
    if sha(source) != a.CHAMPION_SHA256:
        raise ValueError("frozen champion source digest differs")
    tree = ast.parse(source.read_text())
    names = {"ORD_DD", "FAST", "SLOW", "LDRC_DD", "LDRC_R20", "LDRC_CEIL", "LDRC_REC", "LDRC_V"}
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in {"finite", "Native", "CandidateA"}:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets):
            nodes.append(node)
    found = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    if found != {"finite", "Native", "CandidateA"}:
        raise ValueError("controller definitions are incomplete")
    selected = ast.Module(body=nodes, type_ignores=[])
    content = ('"""Exact controller AST from the frozen research champion."""\n'
               f'# Source SHA256: {a.CHAMPION_SHA256}\nimport numpy as np\n\n' + ast.unparse(selected) + "\n")
    reparsed = ast.parse(content)
    if ast.dump(ast.Module(body=reparsed.body[2:], type_ignores=[]), include_attributes=False) != ast.dump(selected, include_attributes=False):
        raise ValueError("controller AST changed during extraction")
    output.write_text(content)


def integrate(runtime: Path, champion: Path):
    extract_controllers(champion, runtime / "sentinel/controller/champion_frozen.py")
    shutil.copyfile(HERE / "controller.py", runtime / "sentinel/controller/champion_replay.py")
    ex3 = runtime / "sentinel/controller/ex3_v6.py"
    replace_once(ex3, 'STRATEGY_ID = "sentinel-ex3-v6-r40-m04-rec8"', f'STRATEGY_ID = "{a.STRATEGY}"')
    replace_once(ex3, 'def recover(**kwargs):\n    return median5.recover(**kwargs, r40_floor=R40_FLOOR,\n                           rec_sessions=RECOVERY_SESSIONS)',
                 'def recover(**kwargs):\n    from .champion_replay import recover\n    return recover(**kwargs)')
    v5 = runtime / "shared/stock_strategy_shared/wealth_core/v5.py"
    value = ast.parse(v5.read_text())
    old = next(n.value.value for n in value.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "REFERENCE_SOURCE_SHA256" for t in n.targets))
    replace_once(v5, old, a.CHAMPION_SHA256)
    machine = runtime / "sentinel/controller/machine.py"
    replace_once(machine, '        prior_state = validate_controller_state(state)\n        st = dict(prior_state)',
        f'        if self.cfg.strategy_id == "{a.STRATEGY}":\n'
        '            from .champion_replay import native_step\n'
        '            return native_step(observation=observation, state=state)\n'
        '        prior_state = validate_controller_state(state)\n        st = dict(prior_state)')
    med = runtime / "sentinel/controller/median5.py"
    replace_once(med, 'return {"version": 1, "episode": False',
                 'return {"version": 2, "champion_audit": {"episodes": 0, "concordance_releases": 0}, "episode": False')
    replace_once(med, 'raw["version"] != 1', 'raw["version"] != 2')
    replace_once(med, '    json.dumps(raw, allow_nan=False)\n    return raw',
                 '    from .champion_replay import validate_recovery\n'
                 '    validate_recovery(raw)\n'
                 '    json.dumps(raw, allow_nan=False)\n    return raw')
    decision = runtime / "sentinel/core/decision.py"
    replace_once(decision, '    "sentinel.controller.ex3_v6",',
        '    "sentinel.controller.ex3_v6",\n    "sentinel.controller.champion_frozen",\n'
        '    "sentinel.controller.champion_replay",')


def source_manifest(runtime):
    return {str(p.relative_to(runtime)): sha(p)
            for folder in ("sentinel", "shared") for p in sorted((runtime / folder).rglob("*.py"))}


def stage(repo: Path, output: Path, champion: Path):
    if output.exists():
        raise ValueError("staged runtime path exists; preserve prior work")
    if sha(champion) != a.CHAMPION_SHA256:
        raise ValueError("frozen champion source digest differs")
    output.mkdir(parents=True)
    # Archive a named source tree; no inherited credentials, git hooks or worktree edits.
    archive = subprocess.Popen(["git", "archive", a.BASE], cwd=repo, stdout=subprocess.PIPE)
    try:
        subprocess.run(["tar", "-x", "-C", str(output)], stdin=archive.stdout, check=True)
    finally:
        archive.stdout.close()
    if archive.wait() != 0:
        raise RuntimeError("base source archive failed")
    subprocess.run(["git", "apply", str(HERE / "v5-runtime.patch")], cwd=output, check=True)
    integrate(output, champion)
    shutil.copytree(HERE, output / "research/full_system_pit",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = source_manifest(output)
    record = dict(schema="full-system-pit-runtime/1", base=a.BASE, v5_source=a.V5_SOURCE,
        patch_sha256=sha(HERE / "v5-runtime.patch"), stage_sha256=sha(__file__),
        champion_source_sha256=a.CHAMPION_SHA256, strategy=a.STRATEGY, files=files,
        tree_sha256=hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(),
        harness_files={p.name: sha(p) for p in sorted(HERE.glob("*.py"))})
    (output / "REPLAY_RUNTIME.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--champion", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.repo.resolve(), args.output.resolve(), args.champion.resolve()), sort_keys=True))
