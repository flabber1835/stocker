"""Missing transfer imports are detected before staging; metadata only."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

import system_campaign_wwe_import_probe as probe


def test_actual_metadata_import_probe_qualifies_request_without_financial_imports():
    request = probe.expected_request()
    proof = probe.qualify(request)
    assert proof['status'] == 'METADATA_IMPORT_AND_SCHEMA_REQUEST_QUALIFIED'
    assert proof['source_files'] == 236 and proof['dependency_versions'] == probe.VERSIONS
    assert proof['actual_financial_runtime_imports'] is False
    assert proof['financial_sessions_advanced'] == 0


def test_wrong_dependency_version_and_request_refuse(monkeypatch):
    request = probe.expected_request()
    original = probe.version
    monkeypatch.setattr(probe, 'version', lambda name: '0.0' if name == 'pydantic' else original(name))
    with pytest.raises(ValueError): probe.qualify(request)
    monkeypatch.setattr(probe, 'version', original)
    wrong = deepcopy(request); wrong['predecessor_sha256'] = '0'*64
    with pytest.raises(ValueError): probe.qualify(wrong)


def test_actual_previous_missing_pydantic_import_failure_is_reproduced():
    code = '''import sys
class Absent:
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='pydantic': raise ModuleNotFoundError("No module named 'pydantic'")
sys.meta_path.insert(0,Absent())
import system_campaign_p02_wwe_job
'''
    actual = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True)
    assert actual.returncode != 0 and b"ModuleNotFoundError: No module named 'pydantic'" in actual.stderr


def test_dependency_lock_and_workflow_cover_the_actual_failed_import_boundary():
    root = Path(__file__).resolve().parents[3]
    workflow = (root / '.github/workflows/capital-system-p02-wwe.yml').read_text(encoding='utf8')
    install = '--require-hashes --only-binary=:all: -r research/capital_risk/wwe-transfer-requirements.lock'
    assert workflow.index(install) < workflow.index('system_campaign_wwe_import_probe.py') < workflow.index('stage.py --request')
    lock = (root / 'research/capital_risk/wwe-transfer-requirements.lock').read_text(encoding='utf8')
    lines = [v for v in lock.splitlines() if v and not v.startswith('#')]
    assert len(lines) == len(probe.VERSIONS)
    for line in lines:
        match = re.fullmatch(r'([a-z-]+)==([0-9.]+) --hash=sha256:([0-9a-f]{64})', line)
        assert match is not None and probe.VERSIONS[match[1]] == match[2]
