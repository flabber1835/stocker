"""Reuse immutable PR #438 code and evidence without copying its book."""
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
from types import ModuleType

BRIDGE = "3c98d99aeb3646ff0883bdf2c76221492ef9b3bb"


def source(path):
    return subprocess.check_output(["git", "show", f"{BRIDGE}:{path}"])


def load(directory):
    directory = Path(directory)
    bridge_dir = directory / "bridge"
    bridge_dir.mkdir()
    hashes = {}
    for name in ("__init__", "model", "sources", "scenarios", "run", "audit"):
        path = f"research/recovery_bridge/{name}.py"
        raw = source(path)
        (bridge_dir / f"{name}.py").write_bytes(raw)
        hashes[f"{BRIDGE}:{path}"] = hashlib.sha256(raw).hexdigest()
    package = ModuleType("research.recovery_bridge")
    package.__path__ = [str(bridge_dir)]
    sys.modules[package.__name__] = package
    original = importlib.import_module("research.recovery_bridge.run")
    helpers = original.load(directory)
    hashes.update(helpers[-1])
    return original, helpers, hashes
