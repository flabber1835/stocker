"""Physical backing-disk admission; boundaries never grant deletion authority."""
import base64
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sentinel_storage_capacity as capacity
from test_shell_lifecycle import ShellLab


def test_two_copies_on_same_drive_are_added_not_checked_separately():
    # 25 GiB can fit either 11 GiB copy + reserve, but cannot fit both.
    with pytest.raises(capacity.Refused, match="insufficient physical"):
        capacity.require_capacity("C:", "C:", {"C:": 25 * capacity.GIB},
                                  base_bytes=11 * capacity.GIB, restore_bytes=11 * capacity.GIB)
    result = capacity.require_capacity("C:", "C:", {"C:": 32 * capacity.GIB},
                                       base_bytes=11 * capacity.GIB, restore_bytes=11 * capacity.GIB)
    assert result["required_bytes"] == {"C:": 22 * capacity.GIB}


def test_separate_backup_drive_cannot_hide_a_full_docker_drive():
    with pytest.raises(capacity.Refused):
        capacity.require_capacity("D:", "C:", {"D:": 500 * capacity.GIB, "C:": capacity.GIB},
                                  base_bytes=11 * capacity.GIB, restore_bytes=11 * capacity.GIB)


@pytest.mark.parametrize("observed", [None, True, -1, "99999999999999"])
def test_unknown_or_malformed_capacity_is_not_a_pass(observed):
    with pytest.raises(capacity.Refused):
        capacity.require_capacity("C:", "C:", {"C:": observed}, restore_bytes=1)


def test_wsl_uses_windows_capacity_even_when_virtual_disk_has_terabytes(monkeypatch):
    real_read = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **k:
                        "microsoft-standard-WSL2" if str(p) == "/proc/sys/kernel/osrelease" else real_read(p, *a, **k))
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda p: False if str(p) == "/.dockerenv" else real_exists(p))
    monkeypatch.setattr(Path, "stat", lambda p, **_: SimpleNamespace(st_dev=1))
    monkeypatch.setattr(capacity, "windows_storage", lambda _: {
        "distro_path": "C:\\Users\\operator\\Ubuntu", "docker_path": "C:\\Docker\\docker_data.vhdx",
        "free": {"C:": capacity.GIB}})
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda _: pytest.fail("virtual capacity was queried"))
    backup, restore, free = capacity.destinations("/home/operator/backup", "/var/lib/docker", "Docker Desktop")
    assert (backup, restore) == ("C:", "C:")
    with pytest.raises(capacity.Refused):
        capacity.require_capacity(backup, restore, free, base_bytes=1, restore_bytes=1)


@pytest.mark.parametrize("backup_path,expected", [("/mnt/d/backup", "D:"), ("/mnt/usb/backup", "linux:2")])
def test_wsl_external_target_is_checked_on_its_actual_disk(monkeypatch, backup_path, expected):
    real_read, real_exists = Path.read_text, Path.exists
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **k:
                        "microsoft-standard-WSL2" if str(p) == "/proc/sys/kernel/osrelease" else real_read(p, *a, **k))
    monkeypatch.setattr(Path, "exists", lambda p: False if str(p) == "/.dockerenv" else real_exists(p))
    monkeypatch.setattr(Path, "stat", lambda p, **_: SimpleNamespace(st_dev=1 if str(p) == "/" else 2))
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda _: SimpleNamespace(free=500 * capacity.GIB))
    monkeypatch.setattr(capacity, "windows_storage", lambda _: {
        "distro_path": "C:\\Ubuntu", "docker_path": "C:\\Docker\\docker_data.vhdx",
        "free": {"C:": capacity.GIB, "D:": 500 * capacity.GIB}})
    backup, restore, free = capacity.destinations(backup_path, "/var/lib/docker", "Docker Desktop")
    assert (backup, restore) == (expected, "C:")
    with pytest.raises(capacity.Refused):
        capacity.require_capacity(backup, restore, free, base_bytes=1, restore_bytes=1)


def test_host_capacity_module_retains_python38_syntax():
    import ast
    ast.parse((ROOT / "scripts/sentinel_storage_capacity.py").read_text(), feature_version=(3, 8))


def test_windows_observer_resolves_paths_and_reports_only_disk_metadata(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    def runner(argv):
        script = base64.b64decode(argv[-1]).decode("utf-16le")
        assert "HKCU:" in script and "settings-store.json" in script
        assert "__DISTRO__" not in script
        assert "ConvertTo-Json -Compress" in script
        return json.dumps({"distro_path": "D:\\Ubuntu", "docker_path": "E:\\Docker\\docker_data.vhdx",
                           "free": {"D:": 40 * capacity.GIB, "E:": 80 * capacity.GIB}})
    assert capacity.windows_storage(runner)["free"]["D:"] == 40 * capacity.GIB


@pytest.mark.parametrize("name", ["Ubuntu';bad", "../Ubuntu"])
def test_unknown_wsl_identity_does_not_guess_a_drive(monkeypatch, name):
    monkeypatch.setenv("WSL_DISTRO_NAME", name)
    with pytest.raises(capacity.Refused, match="WSL_DISTRO_NAME"):
        capacity.windows_storage(lambda _: pytest.fail("unvalidated script launched"))


def test_systemd_wsl_observer_resolves_current_root_without_login_environment(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    calls = []
    def runner(argv):
        calls.append(argv)
        if argv[0] == "wslpath":
            return "\\\\wsl.localhost\\Ubuntu\\"
        script = base64.b64decode(argv[-1]).decode("utf-16le")
        assert "$distro = 'Ubuntu'" in script
        return json.dumps({"distro_path": "D:\\Ubuntu", "docker_path": "E:\\Docker\\docker_data.vhdx",
                           "free": {"D:": 40 * capacity.GIB, "E:": 80 * capacity.GIB}})
    assert capacity.windows_storage(runner)["free"]["D:"] == 40 * capacity.GIB
    assert len(calls) == 2


def test_missing_wsl_identity_cannot_guess_default_distribution(monkeypatch):
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    with pytest.raises(capacity.Refused, match="WSL_DISTRO_NAME"):
        capacity.windows_storage(lambda argv: "C:\\wrong-root" if argv[0] == "wslpath" else pytest.fail("guessed distro"))


@pytest.mark.parametrize("path", ["\\\\server\\share", "relative", "C:relative", "/mnt/c"])
def test_unresolved_windows_paths_are_refused(path):
    with pytest.raises(capacity.Refused):
        capacity.windows_drive(path)


def test_producer_estimate_accounts_for_base_and_future_restore(monkeypatch):
    monkeypatch.setattr(capacity, "destinations", lambda *a, **k: ("C:", "C:", {"C:": 100 * capacity.GIB}))
    calls = []
    def runner(argv):
        calls.append(argv)
        if argv[:2] == ["docker", "info"]:
            return "/var/lib/docker|Docker Desktop"
        assert argv[-1] == "SELECT sum(pg_database_size(oid))::bigint FROM pg_database"
        return str(10 * capacity.GIB)
    result = capacity.check("base", "/backup", runner=runner)
    assert result["required_bytes"] == {"C:": 32 * capacity.GIB}
    assert len(calls) == 2


def test_restore_checks_actual_base_before_allocating_a_volume(monkeypatch):
    monkeypatch.setattr(capacity, "destinations", lambda *a, **k: ("D:", "C:", {"D:": 100 * capacity.GIB, "C:": 100 * capacity.GIB}))
    def runner(argv):
        if argv[:2] == ["docker", "info"]:
            return "/var/lib/docker|Linux"
        assert "du -sb" in argv[-3] and argv[-1] == "base-20261006T010000Z"
        return str(12 * capacity.GIB)
    result = capacity.check("restore", "/backup", "base-20261006T010000Z", runner)
    assert result["required_bytes"] == {"D:": 0, "C:": 19 * capacity.GIB}


@pytest.mark.parametrize("size", ["0", "-1", "bad", "1\n2", str(2 ** 63)])
def test_failed_size_probe_cannot_allocate(size, monkeypatch):
    monkeypatch.setattr(capacity, "destinations", lambda *a, **k: pytest.fail("capacity granted after bad size"))
    with pytest.raises(capacity.Refused):
        capacity.check("base", "/backup", runner=lambda _: size)


def test_shell_capacity_failure_precedes_base_copy(tmp_path):
    lab = ShellLab(tmp_path)
    lab.env["BACKUP_LAB_FAULT"] = "physical-capacity:before"
    result = lab.run()
    assert result.returncode != 0
    assert "base-copy" not in lab.events()
    assert not list(lab.base.glob("base-*"))


def test_shell_restore_capacity_failure_preserves_existing_base(tmp_path):
    lab = ShellLab(tmp_path)
    assert lab.run().returncode == 0
    base = lab.base / "base-20260910T120000Z"
    before = (base / "relation-data").read_bytes()
    lab.env["BACKUP_LAB_FAULT"] = "physical-capacity:before"
    result = lab.run("sentinel-restore-drill.sh", "--backup", str(base), "--physical-only")
    assert result.returncode != 0
    assert "restore-copy" not in lab.events()
    assert not list((tmp_path / "volumes").glob("sentinel-restore-drill-*"))
    assert (base / "relation-data").read_bytes() == before


def test_all_production_services_bound_docker_logs():
    import yaml
    for name in ("docker-compose.sentinel.yml", "docker-compose.sentinel-automation.yml",
                 "docker-compose.sentinel-automation-standby.yml"):
        for service in yaml.safe_load((ROOT / name).read_text())["services"].values():
            assert service["logging"] == {
                "driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}
