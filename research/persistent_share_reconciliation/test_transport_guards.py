"""DATA/AST-only launch-fence falsifiers; no financial module imports."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

PATH = Path(__file__).with_name("job.py")
spec = importlib.util.spec_from_file_location("reconciliation_job_data", PATH)
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


def environment():
    return dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="flabber1835/stocker",
                GITHUB_REPOSITORY_OWNER="flabber1835", GITHUB_ACTOR="flabber1835",
                GITHUB_REF=job.BRANCH, GITHUB_REF_TYPE="branch", GITHUB_EVENT_NAME="push",
                GITHUB_RUN_ATTEMPT="1", RUNNER_ENVIRONMENT="github-hosted", RUNNER_OS="Linux",
                RUNNER_ARCH="X64", ImageOS="ubuntu24", GITHUB_SHA="1" * 40,
                GITHUB_RUN_ID="123", RUNNER_TEMP="/home/runner/work/_temp")


def isolated_context():
    """Exercise the actual function with inert Linux host facts on Windows."""
    class PosixPath(PurePosixPath):
        def resolve(self):
            return self
    tree = ast.parse(PATH.read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "context"]
    namespace = {**vars(job), "os": SimpleNamespace(name="posix"), "Path": PosixPath}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<data-only-host-context>", "exec"), namespace)
    return namespace["context"]


def test_valid_hosted_context_passes():
    isolated_context()(environment())


def test_source_bound_json_has_portable_lf_bytes(tmp_path):
    target = tmp_path / "receipt.json"
    job.save(target, {"ok": True})
    assert target.read_bytes() == b'{\n  "ok": true\n}\n'


@pytest.mark.parametrize("key,value", [
    ("GITHUB_REF", "refs/heads/main"), ("RUNNER_ENVIRONMENT", "self-hosted"),
    ("GITHUB_ACTOR", "other"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("GITHUB_REPOSITORY", "other/stocker"), ("GITHUB_EVENT_NAME", "pull_request"),
    ("ALPACA_API_KEY", "test-never-real"), ("DATABASE_URL", "test-never-real"),
    ("GITHUB_SHA", "bad"), ("GITHUB_RUN_ID", "0"),
])
def test_rejects_wrong_context(key, value):
    env = environment()
    env[key] = value
    with pytest.raises(ValueError):
        isolated_context()(env)


def inspection():
    mounts = [{"Type": "bind", "Destination": p, "RW": p == "/out"}
              for p in ("/variant", "/legacy", "/current", "/frozen", "/p00", "/input", "/out")]
    cmd = ["-B", "-u", "/current/research/persistent_share_reconciliation/worker.py",
           "--source", "/variant", "--legacy", "/legacy", "--current", "/current", "--p00", "/p00",
           "--input", "/input", "--output", "/out/book"]
    return dict(Name="/persistent-reconciliation-worker-123-1", Image=job.IMAGE, Id="a" * 64,
                HostConfig=dict(NetworkMode="none", ReadonlyRootfs=True, Memory=8 * 1024**3,
                                MemorySwap=8 * 1024**3, NanoCpus=2_000_000_000, PidsLimit=64,
                                CapDrop=["ALL"], SecurityOpt=["no-new-privileges"]),
                Config=dict(WorkingDir="/current", User="1001:1001", Env=["PERSISTENT_RECONCILIATION_HOSTED=1"],
                            Labels={"research.study": "fixed-account-reconciliation-20261109", "research.role": "worker"},
                            Entrypoint=["python"], Cmd=cmd), Mounts=mounts)


@pytest.mark.parametrize("mutation", ["network", "image", "credential", "writable_input", "entrypoint", "swap", "identity"])
def test_actual_inspection_rejects_mutations(monkeypatch, mutation):
    value = inspection()
    if mutation == "network":
        value["HostConfig"]["NetworkMode"] = "bridge"
    elif mutation == "image":
        value["Image"] = "sha256:" + "0" * 64
    elif mutation == "credential":
        value["Config"]["Env"].append("GH_TOKEN=test-never-real")
    elif mutation == "writable_input":
        value["Mounts"][0]["RW"] = True
    elif mutation == "entrypoint":
        value["Config"]["Cmd"][-1] = "/different"
    elif mutation == "swap":
        value["HostConfig"]["MemorySwap"] = -1
    else:
        value["Id"] = "b" * 64
    monkeypatch.setattr(job.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, "getgid", lambda: 1001, raising=False)
    monkeypatch.setattr(job.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps([value]).encode()))
    with pytest.raises(ValueError):
        job.inspect("persistent-reconciliation-worker-123-1", "a" * 64)


def test_container_command_has_no_credentials_or_network(monkeypatch):
    monkeypatch.setattr(job.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, "getgid", lambda: 1001, raising=False)
    args = job.command("persistent-reconciliation-worker-123-1", "worker", *([Path("/fixture")] * 6))
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--memory") + 1] == args[args.index("--memory-swap") + 1] == "8g"
    assert not any("TOKEN=" in a or "KEY=" in a or "DATABASE_URL=" in a for a in args)
    assert sum(a.endswith(",readonly") for a in args) == 6


def test_removed_image_guard_is_detectable(monkeypatch):
    tree = ast.parse(PATH.read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "inspect"]
    comparisons = [n for n in ast.walk(fn) if isinstance(n, ast.Compare)
                   and ast.unparse(n) == "value['Image'] == IMAGE"]
    assert len(comparisons) == 1
    target = comparisons[0]
    target.left = ast.Constant(job.IMAGE)
    namespace = dict(vars(job))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<image-falsifier>", "exec"), namespace)
    value = inspection()
    value["Image"] = "sha256:" + "0" * 64
    monkeypatch.setattr(job.os, "getuid", lambda: 1001, raising=False)
    monkeypatch.setattr(job.os, "getgid", lambda: 1001, raising=False)
    monkeypatch.setattr(job.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=json.dumps([value]).encode()))
    with pytest.raises(ValueError):
        job.inspect("persistent-reconciliation-worker-123-1", "a" * 64)
    assert namespace["inspect"]("persistent-reconciliation-worker-123-1", "a" * 64) == value
