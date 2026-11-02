"""Only pure facts and process/filesystem stubs; never perform local cleanup."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ephemeral_runner_capacity as capacity


HOST = dict(system="Linux", os_id="ubuntu", os_version="24.04", containerized=False)


def environment():
    return dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY=capacity.REPOSITORY,
                GITHUB_REPOSITORY_OWNER="flabber1835", GITHUB_ACTOR="flabber1835",
                GITHUB_REF=capacity.REF, GITHUB_REF_TYPE="branch", GITHUB_EVENT_NAME="push",
                GITHUB_RUN_ATTEMPT="1", RUNNER_ENVIRONMENT="github-hosted", RUNNER_OS="Linux",
                RUNNER_ARCH="X64", ImageOS="ubuntu24", GITHUB_WORKSPACE=capacity.WORKSPACE,
                RUNNER_TEMP=capacity.TEMP, RUNNER_TOOL_CACHE=capacity.TOOLS,
                ANDROID_HOME=capacity.SDK, ANDROID_SDK_ROOT=capacity.SDK,
                GITHUB_SHA="a" * 40, GITHUB_RUN_ID="12345",
                GITHUB_WORKFLOW_REF=capacity.REPOSITORY + "/.github/workflows/research_capacity.yml@" + capacity.REF)


def path_fact(path, mode=stat.S_IFDIR, *, device=1, inode=25, permissions=0o755):
    return dict(path=path, resolved=path, mode=mode, permissions=permissions,
                uid=0, device=device, inode=inode, symlink=False)


def layout_fact():
    return dict(ancestors=[path_fact(p) for p in capacity.ANCESTORS],
                sdk_directories=[path_fact(p) for p in (
                    capacity.SDK, capacity.SDK + "/cmdline-tools", capacity.SDK + "/cmdline-tools/latest",
                    capacity.SDK + "/cmdline-tools/latest/bin", capacity.SDK + "/platform-tools")],
                markers=[path_fact(p, stat.S_IFREG) for p in capacity.MARKERS], target_children=["sdk"],
                scopes=[path_fact(p) for p in (capacity.WORKSPACE, capacity.TEMP, capacity.TOOLS)],
                commands=[path_fact(p, stat.S_IFREG) for p in ("/usr/bin/sudo", "/usr/bin/rm")],
                mounts=[dict(point="/", filesystem="ext4"), dict(point="/proc", filesystem="proc")])


@pytest.fixture(autouse=True)
def prohibit_any_unstubbed_process(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("LOCAL_TEST_MUST_NEVER_LAUNCH_A_PROCESS")
    monkeypatch.setattr(capacity.subprocess, "run", refuse)
    monkeypatch.setattr(capacity.subprocess, "check_output", refuse)


@pytest.mark.parametrize("key", list(environment()))
def test_every_host_context_field_is_enforced(key):
    env = environment()
    env[key] = "wrong"
    with pytest.raises(capacity.Refusal):
        capacity.context(env, HOST)


@pytest.mark.parametrize("host", [dict(HOST, system="Windows"), dict(HOST, containerized=True),
                                  dict(HOST, os_id="debian"), dict(HOST, os_version="22.04")])
def test_actual_host_is_independent_of_environment(host):
    with pytest.raises(capacity.Refusal, match="ACTUAL_HOST"):
        capacity.context(environment(), host)


@pytest.mark.parametrize("name", ["GITHUB_HEAD_REF", "GITHUB_BASE_REF", *capacity.FORBIDDEN])
def test_shared_pull_request_and_production_credential_scopes_refuse(name):
    env = environment()
    env[name] = "must-never-be-published"
    with pytest.raises(capacity.Refusal, match="SCOPE_OR_CREDENTIAL"):
        capacity.context(env, HOST)


def test_exact_valid_context_and_real_directory_facts_are_admitted():
    capacity.context(environment(), HOST)
    assert capacity.admit_layout(layout_fact()) == (1, 25)


@pytest.mark.parametrize("change,code", [
    (lambda v: v["ancestors"][-1].update(path="/usr/local/lib/android-other"), "FIXED_TARGET"),
    (lambda v: v["ancestors"][-1].update(symlink=True), "PATH_ALIAS"),
    (lambda v: v["ancestors"][2].update(resolved="/shared/local"), "PATH_ALIAS"),
    (lambda v: v["ancestors"][-2].update(permissions=0o777), "PROTECTED_ANCESTORS"),
    (lambda v: v["ancestors"][-2].update(uid=1001), "PROTECTED_ANCESTORS"),
    (lambda v: v.update(target_children=["sdk", "evidence"]), "SDK_IDENTITY"),
    (lambda v: v["sdk_directories"][0].update(mode=stat.S_IFREG), "SDK_IDENTITY"),
    (lambda v: v["markers"][0].update(symlink=True), "PATH_ALIAS"),
    (lambda v: v["markers"][1].update(mode=stat.S_IFDIR), "SDK_MARKERS"),
    (lambda v: v["commands"][0].update(permissions=0o777), "COMMAND_IDENTITY"),
    (lambda v: v["scopes"][0].update(path=capacity.TARGET, resolved=capacity.TARGET), "PROTECTED_SCOPES"),
    (lambda v: v["mounts"].append(dict(point=capacity.TARGET, filesystem="ext4")), "ANDROID_MOUNT"),
    (lambda v: v["mounts"].append(dict(point=capacity.SDK + "/ndk/shared", filesystem="ext4")), "ANDROID_MOUNT"),
    (lambda v: v["mounts"].append(dict(point="/usr/local/lib", filesystem="ext4")), "ANDROID_MOUNT"),
    (lambda v: v["mounts"][0].update(filesystem="nfs"), "SHARED_OR_CONTAINER_FILESYSTEM"),
    (lambda v: v["scopes"][1].update(device=2), "DIFFERENT_FILESYSTEM"),
])
def test_path_mount_scope_and_command_falsifiers(change, code):
    value = layout_fact()
    change(value)
    with pytest.raises(capacity.Refusal, match=code):
        capacity.admit_layout(value)


def test_same_device_bind_mount_and_escaped_mountpoint_are_not_ignored():
    parsed = capacity.mounts("36 25 8:1 / / rw - ext4 /dev/root rw\n"
                             "37 36 8:1 /shared /usr/local/lib/android/sdk/shared\\040mount rw - ext4 /dev/root rw\n")
    value = layout_fact()
    value["mounts"] = parsed
    assert parsed[1]["point"].endswith("shared mount")
    with pytest.raises(capacity.Refusal, match="ANDROID_MOUNT"):
        capacity.admit_layout(value)


def test_documented_writable_sdk_and_unpromised_sdk_ownership_are_not_false_refusals():
    value = layout_fact()
    for item in [value["ancestors"][-1], *value["sdk_directories"], *value["markers"]]:
        item.update(uid=1001, permissions=0o777)
    assert capacity.admit_layout(value) == (1, 25)


def test_negative_target_case_detects_removed_guard():
    tree = ast.parse(Path(capacity.__file__).read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "admit_layout")
    guards = [n for n in ast.walk(fn) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == "REFUSED_CAPACITY_FIXED_TARGET"
                      for a in n.value.args)]
    assert len(guards) == 1
    bad = layout_fact()
    bad["ancestors"][-1]["path"] = "/usr/local/lib/android-other"
    bad["ancestors"][-1]["resolved"] = "/usr/local/lib/android-other"
    with pytest.raises(capacity.Refusal, match="FIXED_TARGET"):
        capacity.admit_layout(bad)
    fn.body.remove(guards[0])
    namespace = dict(vars(capacity))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), "<guard-falsifier>", "exec"), namespace)
    assert namespace["admit_layout"](bad) == (1, 25)


def install_prepare_stubs(monkeypatch):
    receipts, removed = [], []
    source = hashlib.sha256(Path(capacity.__file__).read_bytes()).hexdigest()
    monkeypatch.setattr(capacity, "host_metadata", lambda: dict(HOST))
    monkeypatch.setattr(capacity, "admitted_output", lambda p: p)
    monkeypatch.setattr(capacity, "checkout", lambda e: source)
    monkeypatch.setattr(capacity, "layout", layout_fact)
    free = iter((8_112_300_032, 20 * 1024**3))
    monkeypatch.setattr(capacity, "free_bytes", lambda: next(free))
    monkeypatch.setattr(capacity, "write_receipt", lambda p, v: receipts.append(deepcopy(v)))
    monkeypatch.setattr(capacity, "remove_android", lambda: removed.append(capacity.TARGET))
    monkeypatch.setattr(capacity, "target_absent", lambda: True)
    return receipts, removed, source


def test_actual_sequence_records_before_and_after_capacity_and_one_literal_removal(monkeypatch):
    receipts, removed, source = install_prepare_stubs(monkeypatch)
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    assert [r["phase"] for r in receipts] == ["VALIDATING", "REMOVAL_ATTEMPTED", "PREPARED"]
    assert removed == [capacity.TARGET]
    assert receipts[1]["free_before_bytes"] == 8_112_300_032
    assert value["free_after_bytes"] == 20 * 1024**3
    capacity.validate_prepared_receipt(value, head="a" * 40, run_id="12345", source_sha256=source)


def test_wrong_actual_host_never_writes_receipt_or_attempts_removal(monkeypatch):
    receipts, removed, _ = install_prepare_stubs(monkeypatch)
    monkeypatch.setattr(capacity, "host_metadata", lambda: dict(HOST, system="Windows"))
    with pytest.raises(capacity.Refusal, match="ACTUAL_HOST"):
        capacity.prepare(Path("unused-stub-output.json"), environment())
    assert not receipts and not removed


def test_changed_inode_on_last_check_refuses_before_any_removal(monkeypatch):
    receipts, removed, _ = install_prepare_stubs(monkeypatch)
    one, two = layout_fact(), layout_fact()
    two["ancestors"][-1]["inode"] = 99
    values = iter((one, two))
    monkeypatch.setattr(capacity, "layout", lambda: next(values))
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    assert value["error_code"] == "REFUSED_CAPACITY_TARGET_CHANGED"
    assert receipts[-1]["phase"] == "REFUSED" and not removed


def test_removal_timeout_is_unknown_and_never_retried(monkeypatch):
    receipts, removed, _ = install_prepare_stubs(monkeypatch)
    def unknown():
        removed.append(capacity.TARGET)
        raise capacity.Refusal("UNKNOWN_REMOVAL_OUTCOME")
    monkeypatch.setattr(capacity, "remove_android", unknown)
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    assert value["error_code"] == "UNKNOWN_REMOVAL_OUTCOME" and value["target_removed"] is None
    assert value["free_after_bytes"] is None and removed == [capacity.TARGET]
    assert receipts[-1]["phase"] == "REFUSED"


def test_insufficient_capacity_still_refuses_after_confirmed_removal(monkeypatch):
    _, removed, _ = install_prepare_stubs(monkeypatch)
    values = iter((8_112_300_032, capacity.MIN_FREE - 1))
    monkeypatch.setattr(capacity, "free_bytes", lambda: next(values))
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    assert value["phase"] == "REFUSED" and value["target_removed"] is True
    assert value["error_code"] == "REFUSED_CAPACITY_AFTER_REMOVAL_RESERVE"
    assert removed == [capacity.TARGET]


def test_exception_text_never_enters_public_error_receipt(monkeypatch):
    _, _, _ = install_prepare_stubs(monkeypatch)
    def fail():
        raise RuntimeError("credential-or-private-payload")
    monkeypatch.setattr(capacity, "layout", fail)
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    assert value["error_code"] == "REFUSED_CAPACITY_PREPARATION_OPERATION"
    assert "credential-or-private-payload" not in json.dumps(value)


def test_delete_uses_only_exact_absolute_arguments_no_shell_and_bounded_wait(monkeypatch):
    calls = []
    monkeypatch.setattr(capacity.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    capacity.remove_android()
    assert calls == [((list(capacity.DELETE_COMMAND),), dict(shell=False, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180))]
    assert capacity.DELETE_COMMAND[-2:] == ("--", "/usr/local/lib/android")
    assert "--one-file-system" in capacity.DELETE_COMMAND and "--preserve-root=all" in capacity.DELETE_COMMAND


@pytest.mark.parametrize("error,code", [(subprocess.TimeoutExpired("stub", 180), "UNKNOWN_REMOVAL_OUTCOME"),
                                       (subprocess.CalledProcessError(1, "stub"), "REMOVAL_COMMAND")])
def test_real_delete_adapter_maps_process_failures_to_closed_codes(monkeypatch, error, code):
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(capacity.subprocess, "run", fail)
    with pytest.raises(capacity.Refusal, match=code):
        capacity.remove_android()


@pytest.mark.parametrize("key,value", [("target", "/tmp/other"), ("target_removed", None),
                                     ("free_after_bytes", True), ("head", "b" * 40),
                                     ("phase", "REFUSED"), ("production_contacted", True)])
def test_prepared_receipt_cannot_qualify_different_or_unknown_outcomes(monkeypatch, key, value):
    _, _, source = install_prepare_stubs(monkeypatch)
    result = capacity.prepare(Path("unused-stub-output.json"), environment())
    result[key] = value
    with pytest.raises(capacity.Refusal):
        capacity.validate_prepared_receipt(result, head="a" * 40, run_id="12345", source_sha256=source)


def test_atomic_receipt_file_and_directory_fsync_order(monkeypatch, tmp_path):
    receipts, _, _ = install_prepare_stubs(monkeypatch)
    value = capacity.prepare(Path("unused-stub-output.json"), environment())
    # Exercise the actual writer, replacing only platform directory-fsync operations on Windows.
    tree = ast.parse(Path(capacity.__file__).read_bytes())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "write_receipt")
    namespace = dict(vars(capacity))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<actual-atomic-receipt>", "exec"), namespace)
    output = tmp_path / "receipt.json"
    original_open, original_fsync, original_close, original_replace = capacity.os.open, capacity.os.fsync, capacity.os.close, capacity.os.replace
    events = []
    monkeypatch.setattr(capacity.os, "O_NOFOLLOW", getattr(capacity.os, "O_NOFOLLOW", 0), raising=False)
    monkeypatch.setattr(capacity.os, "O_DIRECTORY", getattr(capacity.os, "O_DIRECTORY", 0), raising=False)
    def open_fd(path, flags, *args):
        if Path(path) == output.parent:
            events.append("open-directory")
            return 987654
        events.append("open-partial")
        return original_open(path, flags, *args)
    def fsync(fd):
        events.append("directory-fsync" if fd == 987654 else "file-fsync")
        if fd != 987654:
            original_fsync(fd)
    def replace(a, b):
        events.append("replace")
        original_replace(a, b)
    monkeypatch.setattr(capacity.os, "open", open_fd)
    monkeypatch.setattr(capacity.os, "fsync", fsync)
    monkeypatch.setattr(capacity.os, "close", lambda fd: None if fd == 987654 else original_close(fd))
    monkeypatch.setattr(capacity.os, "replace", replace)
    namespace["write_receipt"](output, value)
    assert json.loads(output.read_bytes()) == value
    assert events == ["open-partial", "file-fsync", "replace", "open-directory", "directory-fsync"]
