from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def test_verified_entry_installs_source_final_before_install_authority():
    source = (ROOT / "scripts" / "sentinel_go_verified_entry.py").read_text(
        encoding="utf-8")
    source_import = "import sentinel_go_24x7_entry as source_final"
    install_import = "import sentinel_go_install_entry as install_anytime"
    assert source_import in source
    assert install_import in source
    assert source.index(source_import) < source.index(install_import)
    assert source.index("source_final.install()") < source.index(
        "install_anytime._install_overlay()")


def test_public_go_launcher_remains_the_vetted_verified_entry():
    launcher = (ROOT / "scripts" / "sentinel-go-validate.sh").read_text(
        encoding="utf-8")
    assert 'scripts/sentinel_go_verified_entry.py "$@"' in launcher
    assert "scripts/sentinel_go_24x7_entry.py" not in launcher
    assert "scripts/sentinel_go_install_entry.py" not in launcher
