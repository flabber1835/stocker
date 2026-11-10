"""DATA-only archived-container admission tests; no runtime or account calls."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def transport(monkeypatch):
    job = load("archive_guard_job_data", HERE / "job.py")
    monkeypatch.setitem(sys.modules, "job", job)
    return load("archive_guard_transport_data", HERE / "transport.py")


def inspection(image, role):
    command = ["-B", "-u", f"/current/research/persistent_share_reconciliation/{role}.py",
               "--source", "/variant", "--legacy", "/legacy", "--current", "/current",
               "--p00", "/p00", "--input", "/input", "--output",
               "/out/book" if role == "worker" else "/out/review"]
    destinations = ["/variant", "/legacy", "/current", "/frozen", "/p00", "/input", "/out"]
    if role == "review":
        command += ["--work", "/work/book"]
        destinations.append("/work")
    return dict(
        Name=f"/persistent-reconciliation-{role}-123-1", Image=image, Id="a" * 64,
        State=dict(Running=False, OOMKilled=False, ExitCode=0),
        HostConfig=dict(NetworkMode="none", ReadonlyRootfs=True, Memory=8 * 1024**3,
                        MemorySwap=8 * 1024**3, NanoCpus=2_000_000_000, PidsLimit=64,
                        CapDrop=["ALL"], SecurityOpt=["no-new-privileges"]),
        Config=dict(WorkingDir="/current", User="1001:1001",
                    Labels={"research.study": "fixed-account-reconciliation-20261109",
                            "research.role": role}, Entrypoint=["python"], Cmd=command,
                    Env=["PERSISTENT_RECONCILIATION_HOSTED=1", "OPENBLAS_NUM_THREADS=1"]),
        Mounts=[dict(Type="bind", Source="/inert-fixture" + destination,
                     Destination=destination, RW=destination == "/out")
                for destination in destinations])


@pytest.mark.parametrize("role", ["worker", "review"])
def test_complete_positive_archived_fixture_is_accepted(transport, role):
    value = inspection(transport.IMAGE, role)
    original = deepcopy(value)
    assert transport.stopped(value, role, "123") is None
    assert value == original


MUTATIONS = [
    ("wrong_name", "POSITIVE_STOPPED_IDENTITY"),
    ("wrong_run_id", "POSITIVE_STOPPED_IDENTITY"),
    ("archive_index_instead_of_image", "POSITIVE_STOPPED_IDENTITY"),
    ("invalid_container_id", "POSITIVE_STOPPED_IDENTITY"),
    ("still_running", "POSITIVE_STOPPED_IDENTITY"),
    ("oom", "POSITIVE_STOPPED_IDENTITY"),
    ("nonzero_exit", "POSITIVE_STOPPED_IDENTITY"),
    ("network", "ARCHIVED_FENCES"),
    ("writable_root", "ARCHIVED_FENCES"),
    ("unbounded_swap", "ARCHIVED_FENCES"),
    ("wrong_cpu", "ARCHIVED_FENCES"),
    ("capabilities", "ARCHIVED_FENCES"),
    ("privilege_escalation", "ARCHIVED_FENCES"),
    ("writable_input", "ARCHIVED_MOUNTS"),
    ("readonly_output", "ARCHIVED_MOUNTS"),
    ("missing_input", "ARCHIVED_MOUNTS"),
    ("extra_bind", "ARCHIVED_MOUNTS"),
    ("wrong_role_label", "ARCHIVED_ENTRYPOINT"),
    ("wrong_entrypoint", "ARCHIVED_ENTRYPOINT"),
    ("altered_command_argument", "ARCHIVED_ENTRYPOINT"),
    ("extra_command_argument", "ARCHIVED_ENTRYPOINT"),
    ("wrong_working_directory", "ARCHIVED_ENTRYPOINT"),
    ("root_user", "ARCHIVED_ENTRYPOINT"),
    ("missing_user_group", "ARCHIVED_ENTRYPOINT"),
    ("transfer_secret", "ARCHIVED_CREDENTIALS"),
    ("github_secret", "ARCHIVED_CREDENTIALS"),
    ("provider_secret", "ARCHIVED_CREDENTIALS"),
]


def mutate(value, name):
    if name == "wrong_name":
        value["Name"] += "-other"
    elif name == "wrong_run_id":
        value["Name"] = value["Name"].replace("-123-", "-124-")
    elif name == "archive_index_instead_of_image":
        value["Image"] = "sha256:97b69cf2f8487785e55a4ecafe2497829d021a9d58b5e4af001e8dcc6a981309"
    elif name == "invalid_container_id":
        value["Id"] = "unidentified"
    elif name == "still_running":
        value["State"]["Running"] = True
    elif name == "oom":
        value["State"]["OOMKilled"] = True
    elif name == "nonzero_exit":
        value["State"]["ExitCode"] = 2
    elif name == "network":
        value["HostConfig"]["NetworkMode"] = "bridge"
    elif name == "writable_root":
        value["HostConfig"]["ReadonlyRootfs"] = False
    elif name == "unbounded_swap":
        value["HostConfig"]["MemorySwap"] = -1
    elif name == "wrong_cpu":
        value["HostConfig"]["NanoCpus"] = 0
    elif name == "capabilities":
        value["HostConfig"]["CapDrop"] = []
    elif name == "privilege_escalation":
        value["HostConfig"]["SecurityOpt"] = []
    elif name == "writable_input":
        next(m for m in value["Mounts"] if m["Destination"] == "/input")["RW"] = True
    elif name == "readonly_output":
        next(m for m in value["Mounts"] if m["Destination"] == "/out")["RW"] = False
    elif name == "missing_input":
        value["Mounts"] = [m for m in value["Mounts"] if m["Destination"] != "/input"]
    elif name == "extra_bind":
        value["Mounts"].append(dict(Type="bind", Destination="/unexpected", RW=False))
    elif name == "wrong_role_label":
        value["Config"]["Labels"]["research.role"] = "other"
    elif name == "wrong_entrypoint":
        value["Config"]["Entrypoint"] = ["sh"]
    elif name == "altered_command_argument":
        value["Config"]["Cmd"][-1] = "/different"
    elif name == "extra_command_argument":
        value["Config"]["Cmd"].append("--unexpected")
    elif name == "wrong_working_directory":
        value["Config"]["WorkingDir"] = "/tmp"
    elif name == "root_user":
        value["Config"]["User"] = "0:0"
    elif name == "missing_user_group":
        value["Config"]["User"] = "1001"
    elif name == "transfer_secret":
        value["Config"]["Env"].append("CAPITAL_RISK_RESEARCH_KEY_20261027=test-never-real")
    elif name == "github_secret":
        value["Config"]["Env"].append("GITHUB_TOKEN=test-never-real")
    elif name == "provider_secret":
        value["Config"]["Env"].append("ALPACA_SECRET_KEY=test-never-real")
    else:
        raise AssertionError("UNREGISTERED_MUTATION:" + name)


@pytest.mark.parametrize("role", ["worker", "review"])
@pytest.mark.parametrize("mutation,guard", MUTATIONS)
def test_actual_archive_guard_rejects_mutation(transport, role, mutation, guard):
    value = inspection(transport.IMAGE, role)
    mutate(value, mutation)
    with pytest.raises(ValueError, match="^" + guard + "$"):
        transport.stopped(value, role, "123")


def test_removed_complete_command_guard_accepts_rejected_mutant(transport):
    tree = ast.parse((HERE / "transport.py").read_bytes())
    fn, = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "stopped"]
    comparisons = [node for node in ast.walk(fn) if isinstance(node, ast.Compare)
                   and ast.unparse(node) == "c['Cmd'] == command"]
    assert len(comparisons) == 1
    comparison = comparisons[0]
    comparison.left = ast.Name(id="command", ctx=ast.Load())
    namespace = dict(vars(transport))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 "<removed-archive-command-guard>", "exec"), namespace)
    value = inspection(transport.IMAGE, "review")
    mutate(value, "altered_command_argument")
    with pytest.raises(ValueError, match="^ARCHIVED_ENTRYPOINT$"):
        transport.stopped(value, "review", "123")
    assert namespace["stopped"](value, "review", "123") is None
