"""Load immutable research helpers from Git objects, recording their hashes."""
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
from types import ModuleType

PARAMETERS = "f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb"
OWNED55 = "181dfef1682b1351fe715059dd5ad99329321f5a"


def load(directory: Path):
    sources = {}

    def source(commit, path):
        raw = subprocess.check_output(["git", "show", f"{commit}:{path}"])
        sources[f"{commit}:{path}"] = hashlib.sha256(raw).hexdigest()
        return raw

    for name in ("__init__", "pipeline", "pipeline_diagnostics", "study", "holdings", "parameters", "account"):
        (directory / f"{name}.py").write_bytes(source(PARAMETERS, f"research/impedance/{name}.py"))
    pkg = ModuleType("research.impedance")
    pkg.__path__ = [str(directory)]
    sys.modules[pkg.__name__] = pkg
    raw = source(OWNED55, "research/owned55_replay/model.py")
    owned = ModuleType("frozen_owned55_model")
    exec(compile(raw, "<frozen-owned55-model>", "exec"), owned.__dict__)
    # Parent policies are also part of the retained identity.
    source(owned.PARENT_COMMIT, owned.PARENT_PATH)
    return tuple(importlib.import_module(f"research.impedance.{name}")
                 for name in ("pipeline", "parameters", "account")) + (owned, sources)
