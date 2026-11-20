"""Host readiness requires the published rolling source proof and never runs provider ingestion."""
from pathlib import Path
import os

ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT", Path(__file__).resolve().parents[2]))


def test_installer_has_one_publication_writer_and_no_vendor_polling():
    driver = (ROOT / "scripts/sentinel_autonomous_deploy_driver.py").read_text()
    installer = (ROOT / "scripts/sentinel_autonomous_deploy_install_entry.py").read_text()
    assert "def _vendor_publication_probe" not in driver + installer
    assert "operational_snapshot.require_alpaca_openfigi" in driver
    assert "from sentinel_install_source_refresh import refresh" in installer
    assert "refresh(self, timing=timing, deadline=deadline)" in installer
