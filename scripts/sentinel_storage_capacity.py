#!/usr/bin/env python3
"""Host-only admission for physical backup/restore allocations (Python 3.8+)."""
from __future__ import annotations

import argparse
import base64
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import sys

from sentinel_maintenance_process import run_bounded

GIB = 1024 ** 3
RESERVE = 10 * GIB
COMPOSE = ["docker", "compose", "-f", "docker-compose.sentinel.yml",
           "-f", "docker-compose.sentinel-backup.yml"]


class Refused(RuntimeError):
    pass


def run(argv):
    result = run_bounded(argv, timeout=30, private_group=False)
    if result.returncode:
        raise Refused("capacity observation failed: " + argv[0])
    return result.stdout.strip()


def size_bytes(text):
    if not re.fullmatch(r"[0-9]{1,20}", text) or not 0 < int(text) < 2 ** 63:
        raise Refused("invalid physical copy size")
    return int(text)


def windows_drive(path):
    drive, tail = ntpath.splitdrive(path)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"):
        raise Refused("Windows storage path is not on a resolved local drive")
    return drive.upper()


def windows_storage(runner=run):
    # PowerShell receives only a validated distribution name, never credentials.
    distro = os.environ.get("WSL_DISTRO_NAME", "")
    if not distro:
        # systemd jobs may omit the login environment. wslpath resolves the
        # current root to its own UNC identity without starting another distro.
        path = runner(["wslpath", "-w", "/"])
        match = re.fullmatch(r"\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)\\", path, re.IGNORECASE)
        distro = match[1] if match else ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", distro):
        raise Refused("WSL_DISTRO_NAME is required for host capacity admission")
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$distro = '__DISTRO__'
$entries = @(Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss |
    Get-ItemProperty | Where-Object { $_.DistributionName -eq $distro })
if ($entries.Count -ne 1) { throw 'Distribution backing disk unresolved' }
$distroPath = $entries[0].BasePath -replace '^\\\\\?\\', ''
$dockerPath = Join-Path $env:LOCALAPPDATA 'Docker\wsl\disk\docker_data.vhdx'
$settings = Join-Path $env:APPDATA 'Docker\settings-store.json'
if (Test-Path -LiteralPath $settings) {
    $config = Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json
    if ($config.DiskImageLocation) {
        $dockerPath = Join-Path $config.DiskImageLocation 'docker_data.vhdx'
    }
}
if (!(Test-Path -LiteralPath $dockerPath) -or !(Test-Path -LiteralPath $distroPath)) {
    throw 'Backing path unavailable'
}
$free = @{}
Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    $free[$_.DeviceID] = [long]$_.FreeSpace
}
@{ distro_path=$distroPath; docker_path=$dockerPath; free=$free } | ConvertTo-Json -Compress
""".replace("__DISTRO__", distro)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    executable = shutil.which("powershell.exe") or (
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    record = json.loads(runner([executable, "-NoProfile", "-NonInteractive",
                                "-EncodedCommand", encoded]))
    free = record["free"]
    if not isinstance(free, dict) or any(type(n) is not int or n < 0 for n in free.values()):
        raise Refused("Windows physical free-space observation is invalid")
    return record


def destinations(backup_root, docker_root, operating_system, runner=run):
    """Return (allocation disk, restore disk, actual free bytes by disk)."""
    kernel = Path("/proc/sys/kernel/osrelease").read_text().lower()
    if "microsoft" in kernel and not Path("/.dockerenv").exists():
        record = windows_storage(runner)
        match = re.match(r"^/mnt/([a-zA-Z])(?:/|$)", str(backup_root))
        free = dict(record["free"])
        if match:
            backup = match[1].upper() + ":"
        elif Path(backup_root).stat().st_dev != Path("/").stat().st_dev:
            # A separately mounted Linux/USB filesystem is not inside the WSL
            # VHD. Its own statvfs is physical capacity, unlike the distro root.
            backup = "linux:" + str(Path(backup_root).stat().st_dev)
            free[backup] = shutil.disk_usage(backup_root).free
        else:
            backup = windows_drive(record["distro_path"])
        restore = windows_drive(record["docker_path"]) if "docker desktop" in operating_system.lower() else windows_drive(record["distro_path"])
        return backup, restore, free
    # Linux host paths refer to the local daemon's backing filesystems. A remote
    # or inaccessible Docker root cannot be certified by a guessed fallback.
    backup_path, restore_path = Path(backup_root).resolve(strict=True), Path(docker_root).resolve(strict=True)
    backup, restore = str(backup_path.stat().st_dev), str(restore_path.stat().st_dev)
    free = {backup: shutil.disk_usage(backup_path).free,
            restore: shutil.disk_usage(restore_path).free}
    return backup, restore, free


def require_capacity(backup, restore, free, *, base_bytes=0, restore_bytes=0):
    required = {}
    for disk, amount in ((backup, base_bytes), (restore, restore_bytes)):
        required[disk] = required.get(disk, 0) + amount
    for disk, amount in required.items():
        observed = free.get(disk)
        if type(observed) is not int or observed < amount + RESERVE:
            raise Refused("insufficient physical disk capacity for backup/restore on " + disk)
    return {"storage_capacity_ready": True, "required_bytes": required,
            "reserve_bytes": RESERVE, "free_bytes": {disk: free[disk] for disk in required}}


def check(operation, backup_root, base_name=None, runner=run):
    if operation == "base":
        raw = runner(COMPOSE + ["exec", "-T", "sentinel-postgres", "psql", "-U", "sentinel", "-d", "sentinel",
                               "-v", "ON_ERROR_STOP=1", "-Atc",
                               "SELECT sum(pg_database_size(oid))::bigint FROM pg_database"])
    else:
        if not re.fullmatch(r"base-[0-9]{8}T[0-9]{6}Z", base_name or ""):
            raise Refused("invalid restore base identity")
        raw = runner(COMPOSE + ["exec", "-T", "sentinel-postgres", "sh", "-ceu",
                               'du -sb -- "/sentinel-backup/base/$1" | cut -f1', "sh", base_name])
    estimate = (size_bytes(raw) * 3 + 1) // 2 + GIB
    info = runner(["docker", "info", "--format", "{{.DockerRootDir}}|{{.OperatingSystem}}"])
    parts = info.split("|")
    if len(parts) != 2 or not parts[0].startswith("/"):
        raise Refused("Docker backing filesystem unavailable")
    backup, restore, free = destinations(backup_root, *parts, runner=runner)
    return require_capacity(backup, restore, free,
                            base_bytes=estimate if operation == "base" else 0,
                            restore_bytes=estimate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("base", "restore"))
    parser.add_argument("--backup-root", required=True)
    parser.add_argument("--base-name")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(args.operation, args.backup_root, args.base_name), sort_keys=True))
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("SENTINEL_STORAGE_REASON=PHYSICAL_CAPACITY_UNAVAILABLE", file=sys.stderr)
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
