"""Read-only extraction from the hash-verified independent research source."""
import ast
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np

SOURCE = Path(__file__).with_name("frozen_reference.txt").read_text()
EXPECTED = "11c94a61c145261daac81047cf7b7bb1ea0c97b369476458d83fc29fbc10de95"


def verify():
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "OUT" for t in node.targets):
            node.value = ast.Constant(value="<OUTPUT_PATH>")
    actual = hashlib.sha256(ast.dump(tree, include_attributes=False).encode()).hexdigest()
    assert actual == EXPECTED


def namespace():
    verify()
    symbols = {"N_SLOTS", "ENTRY_W", "COST", "REVIEW_AGE", "COOLDOWN", "STOP_RET",
               "MIN_PRICE", "MIN_ADV20", "MIN_DAY_DV", "TOP", "TERMINAL", "ORD_DD",
               "FAST", "SLOW", "LDRC_DD", "LDRC_R20", "LDRC_CEIL", "LDRC_REC", "LDRC_V",
               "PEER_LOOKBACK", "PEER_MIN_OBS", "PEER_COUNT", "PEER_CORR_FLOOR", "PEER_STATS"}
    tree = ast.parse(SOURCE)
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            nodes.append(node)
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) and t.id in symbols for t in node.targets):
            nodes.append(node)
    scope = dict(np=np, math=math, dataclass=dataclass, field=field,
                 defaultdict=defaultdict, Path=Path)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "frozen_median5_reference", "exec"), scope)
    return scope
