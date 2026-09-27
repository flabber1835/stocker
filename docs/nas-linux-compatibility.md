# NAS Linux compatibility audit

This audit accompanies the lock fix based on main
`78fcaa85017e6bcfa0f110f71a1a6fda8c91845b`. The operator reported DSM
7.3.2-86009-4, Linux 3.10.108 x86_64, host Python 3.8.15, Docker 24.0.2 and
Compose v2.20.1-6047-g6817716. PostgreSQL 16 is running. The source checkout is
clean; no GO has passed. Backup/WAL mounts point to a separate USB filesystem.
Its reported free space was 305 GB, versus a roughly 6.3 GB Sentinel database.
These observations are not a backup or deployment certificate.

## Diagnosis and source research

The operator acquired an exclusive flock on a disposable file, then read its
fdinfo: only `pos` and `flags` were present. The helper required a `lock:` record,
so the backup child rejected its inherited descriptor and tried to acquire its
parent's lock again. The apparent concurrent-backup refusal is reproducible
without another backup. GO uses the same helper.

This is an upstream kernel interface compatibility issue exposed on this
Synology, not evidence that Synology's flock is broken. The kernel author's
[March 2015 fdinfo lock patch](https://lkml.rescloud.iu.edu/hypermail/linux/kernel/1503.0/04446.html)
explains both the added interface and why global lock-table PIDs cannot prove
ownership after parent exit. Do not confuse the unrelated fdinfo `mnt_id` field
introduced in 3.15 with the later lock-record addition. Vendor kernels can
backport features: actual capability evidence governs, not the version string.

The [Linux flock contract](https://man7.org/linux/man-pages/man2/flock.2.html)
specifies open-description ownership and independent-open contention. The
[new fallback decision](host-lock-ownership.md) uses those kernel operations,
including an explicit acquisition race contract. It does not infer ownership
from contention or a PID. No sysctl, privilege elevation, lock-file deletion or
kernel replacement is required.

## Reviewed compatibility surfaces

| Surface | Finding and disposition |
| --- | --- |
| Backup, recurring backup subprocesses, GO and bringup | All reach the shared verifier. Add the fdinfo-free ownership path and immediate post-acquisition checks. Keep original paths, UID scope, inherited descriptors and GO token. |
| Autonomous deployment launcher | Its bare inherited flock call lacked exact-path binding. Bind device/inode to the deployment lock and use the same helper. No unrelated descriptor may authorize deployment. |
| Host memory accounting | [MemAvailable is a Linux 3.14 addition](https://www.kernel.org/pub/linux/docs/man-pages/book/man-pages-6.12.pdf). Missing or unreadable data must produce UNMEASURED. Fix the report's former unconditional OBSERVED; emit large awk byte counts as decimal integers, not exponent notation. Do not substitute MemFree as equivalent evidence. |
| CPU, memory, swap and cgroup v1 | [Docker documents kernel-dependent resource limits](https://docs.docker.com/engine/containers/resource_constraints/). Existing `sentinel_host_capabilities.py` performs metadata and an actual NanoCPUs create probe. Preserve the generated no-CPU graph, memory/shm limits and OBSERVED_NOT_BOUNDED declaration. Unknown capabilities never justify deleting limits. The existing Synology regression fixture remains part of validation. |
| Container kernel and security | Containers share the host kernel. Python 3.12 in an image does not add newer syscalls to Linux 3.10. Host scripts do not introduce pidfd, memfd, openat2, statx, renameat2, OFD locks or kcmp. [Docker seccomp support is configuration-dependent](https://docs.docker.com/engine/security/seccomp/); do not disable it to hide an image failure. Exact-image startup still needs NAS evidence. |
| Shell and utility boundary | Host launchers explicitly use Bash; do not invoke them with DSM's interactive `sh`. Host stdlib remains Python 3.8.15 compatible. `sync -f`, GNU `find -printf`, worker `flock`, timeout and physical PostgreSQL tools execute in the pinned Linux container, not as assumed DSM binaries. `/proc/self/fd` inode inspection does not require newer fdinfo lock records. |
| Filesystem semantics and permissions | Keep PostgreSQL UID and root write probes, hard-link publication, fsync and container media locks. The base directory being unreadable to `king` does not warrant chmod/chown. Different paths or Synology snapshot/bind mounts on `/volume1` do not establish independent storage. The USB target must pass actual write, locking and restore checks. Remote NFS/CIFS locking differs from local filesystems; no cross-host qualification is claimed. |
| Scheduler environment | [Synology's scheduler guidance](https://kb.synology.com/da-dk/DSM/tutorial/common_mistake_in_task_scheduler_script) requires deliberate user/permissions, absolute paths and explicit shell. Schedule under the same reviewed host identity; set executable paths/PATH explicitly, cd to the checkout, and keep output on a data volume. No systemd-only assumption or editing DSM-managed cron files. Existing bounded maintenance entry and stderr/exit status remain authoritative. |
| Compose version and health | Existing `up --wait --wait-timeout` requires Compose support; the option was added in [Compose 2.17](https://github.com/docker/compose/releases/tag/v2.17.0), before the observed 2.20.1. Version presence does not prove service health or bounded startup; preserve the outer command deadlines and exact image/source checks. No latest-Compose-only flag is added. |
| Boot identity, randomness, process supervision | Retain the boot-id prerequisite and stdlib secrets, subprocess, selectors, process groups and nonblocking pipes. Do not replace boot identity with uname or weaken source-reuse binding. Missing prerequisites refuse; a modern local Docker kernel cannot qualify the NAS process lifecycle. |

## Operator check and remaining qualification

The shared helper is also a short, standalone diagnostic:

```sh
python3 scripts/sentinel_lock_ownership.py
```

It creates/removes a uniquely named temporary directory and tests real owner,
duplicate, unrelated, shared and unlocked descriptors. It reads no credentials,
database or backup. PASS is host flock compatibility only. In a separate NAS
qualification, preserve the kernel/Python identities and run parent-death and
backup/GO composition tests against disposable data before claiming recovery.

After reviewed merge, the production sequence remains the supported verified
base-backup producer followed by backup-status and then GO. Do not remove lock
files, overwrite old generations, bypass guards or treat stale archives as
current. Actual archive progress, populated restore, maintenance scheduling,
runtime-image startup and provider acceptance remain separate checks.

The research and local regression matrix reduce foreseeable follow-up PRs;
they cannot guarantee every vendor backport, filesystem or deployed image.
The NAS is the final authority for those observations.

## Local validation

All tests ran without network or broker access. The Linux test image used
Python 3.12; the separate minimum-host image used Python 3.8.15. Legacy procfs
tests replace only fdinfo reads; the real kernel still performs every flock.
No claim of running Linux 3.10 locally is made. Test counts overlap.

```text
python -m pytest tests/scripts/test_host_lock_ownership.py tests/scripts/test_host_capabilities.py tests/production_composition/test_go_backup_lock_concurrency.py -q --tb=short --show-capture=no -p no:cacheprovider
105 passed (disposable writable checkout; includes generated Compose paths)

python -m unittest discover -s tests/host_python38 -p test_env_ingestion.py -q
883 passed on Python 3.8.15

python -m unittest discover -s tests/host_python38 -p test_lock_ownership.py -v
3 passed on Python 3.8.15

python scripts/sentinel_lock_ownership.py
PASS on Python 3.8.15 (disposable host diagnostic)

python -m pytest tests/host_python38/test_env_ingestion.py::EnvHarness::test_webhook_valid_file_and_process_reach_bootstrap -q --tb=short -p no:cacheprovider
1 passed on Python 3.12 after fixture correction

PYTHONPATH=.:shared:scripts python -m tools.sentinel_host_lock_falsifiers
9 mutations killed, including legacy contention-only, shared upgrade and probe error
```

The broader relevant run used:

```text
python -m pytest tests/scripts/test_host_lock_ownership.py tests/scripts/test_host_capabilities.py tests/host_python38/test_lock_ownership.py tests/host_python38/test_env_ingestion.py tests/backup/test_shell_lifecycle.py tests/backup/test_recurring_maintenance.py tests/sentinel/test_autonomous_deploy.py tests/sentinel/test_autonomous_deploy_driver.py -q --tb=short --show-capture=no -p no:cacheprovider
```

It produced 1,143 passes and four failures: three Compose fixtures needed a
writable generated-artifact directory; one deployment fixture used an unrelated
temporary descriptor. The writable-copy matrix and both host-version reruns
above cover all four failures. No single 1,147-green rerun is claimed. The new
fixture uses a real exclusive lock on the expected test path; it does not mock
away verification. Backup publication/lifecycle and deployment-driver cases
passed in the broader run.

Executing the real measurement report producer with the old unconditional
OBSERVED expression gives one expected failure (missing MemAvailable) and two
passing controls (zero pressure and observed availability). The corrected
producer passes all three. Changed Python compilation, shell syntax and diff
checks also pass. No strategy golden fixtures or full financial suite changed.
