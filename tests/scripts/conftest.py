from __future__ import annotations

import os
from pathlib import Path


# The certified test image deliberately keeps the full repository under
# /work/repo off PYTHONPATH. A few operator-script tests resolve the script under
# test relative to /work/tests/scripts, so expose only those inspection targets
# inside the ephemeral test container. This does not alter the deployable image
# and does not make the repository package importable.
_INSPECTION_TARGETS = (
    "sentinel-base-backup.sh",
    "sentinel-backup-lib.sh",
    "split-sharadar-zip.sh",
)


def pytest_configure(config):
    del config
    if os.environ.get("SENTINEL_IN_IMAGE") != "1":
        return
    test_root = Path(__file__).resolve().parents[2]
    repo_root = Path(os.environ["SENTINEL_REPO_ROOT"]).resolve()
    if test_root == repo_root:
        return

    target_dir = test_root / "scripts"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in _INSPECTION_TARGETS:
        source = repo_root / "scripts" / name
        target = target_dir / name
        if target.exists() or target.is_symlink():
            continue
        if not source.is_file():
            raise RuntimeError(f"missing operator-script inspection target: {source}")
        target.symlink_to(source)
